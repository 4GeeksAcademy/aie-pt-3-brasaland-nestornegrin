/** Autenticación federada en el backoffice: botón de login, panel de cuentas vinculadas (perfil) y vuelta desde Google. */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { FederatedCallback } from "../components/federated-callback";
import { GoogleLoginButton } from "../components/google-login-button";
import { LinkedAccountsPanel } from "../components/linked-accounts";
import { apiFetch, saveAccessToken } from "@/lib/api-client";
import { rememberFlow } from "@/lib/federated";

jest.mock("@/lib/api-client", () => ({
  apiFetch: jest.fn(),
  readApiError: jest.fn(async (response: Response, fallback: string) => {
    try {
      const body = (await response.json()) as { detail?: string };
      return body.detail ?? fallback;
    } catch {
      return fallback;
    }
  }),
  saveAccessToken: jest.fn(),
}));
jest.mock("@/services/telemetry", () => ({ startTelemetrySession: jest.fn() }));
const replace = jest.fn();
let search = new URLSearchParams();
jest.mock("next/navigation", () => ({ useRouter: () => ({ replace }), useSearchParams: () => search }));

const mockedFetch = apiFetch as jest.MockedFunction<typeof apiFetch>;

function json(body: unknown, status = 200, headers: Record<string, string> = {}): Response {
  return { ok: status < 400, status, json: async () => body, headers: new Headers(headers) } as Response;
}

const PROVIDERS_ON = { enabled: true, providers: [{ provider: "google", configured: true }] };
const accounts = (linked: boolean, methods: number) => ({
  has_password: methods - (linked ? 1 : 0) > 0, access_methods: methods,
  providers: [{ provider: "google", linked, email_at_link_time: linked ? "camila@gmail.example" : null, linked_at: linked ? "2026-11-01T10:00:00Z" : null }],
});

let container: HTMLDivElement;
let root: Root;
beforeAll(() => { (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true; });
beforeEach(() => {
  // jsdom no implementa la navegación (`location.assign` hacia Google): se silencia solo ese aviso.
  const original = console.error;
  jest.spyOn(console, "error").mockImplementation((...args: unknown[]) => {
    if (!String(args[0]).includes("Not implemented: navigation") && !String((args[0] as Error)?.message).includes("Not implemented: navigation")) original(...args);
  });
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  mockedFetch.mockReset();
  replace.mockReset();
  (saveAccessToken as jest.Mock).mockReset();
  window.sessionStorage.clear();
  search = new URLSearchParams();
});
afterEach(() => { act(() => root.unmount()); container.remove(); jest.restoreAllMocks(); });

const render = async (node: React.ReactNode) => { await act(async () => { root.render(node); }); };
const button = (label: string) => Array.from(container.querySelectorAll("button")).find((b) => b.textContent?.includes(label));
const click = async (label: string) => { await act(async () => { button(label)!.click(); }); };

describe("botón «Continuar con Google»", () => {
  test("aparece solo si el despliegue lo permite y Google está configurado", async () => {
    mockedFetch.mockResolvedValue(json(PROVIDERS_ON));
    await render(<GoogleLoginButton />);
    expect(container.textContent).toContain("Continuar con Google");
    expect(container.textContent).toContain("Solo para cuentas que ya vincularon");
  });

  test.each([
    ["interruptor apagado (tablets compartidas)", { enabled: false, providers: [{ provider: "google", configured: false }] }],
    ["Google sin configurar", { enabled: true, providers: [{ provider: "google", configured: false }] }],
  ])("no aparece con %s", async (_name, body) => {
    mockedFetch.mockResolvedValue(json(body));
    await render(<GoogleLoginButton />);
    expect(container.textContent).toBe("");
  });

  test("el inicio del login no envía credenciales de sesión (es público)", async () => {
    mockedFetch.mockResolvedValue(json(PROVIDERS_ON));
    await render(<GoogleLoginButton />);
    mockedFetch.mockResolvedValue(json({ authorization_url: "about:blank#google" }));
    await click("Continuar con Google");
    const [path, , authenticated] = mockedFetch.mock.calls.at(-1)!;
    expect(path).toBe("/auth/federated/google/login/start");
    expect(authenticated).toBe(false);
  });
});

describe("perfil · cuentas vinculadas", () => {
  const load = async (acc: unknown) => {
    mockedFetch.mockImplementation(async (path) => json(path === "/auth/federated/providers" ? PROVIDERS_ON : acc));
    await render(<LinkedAccountsPanel />);
  };

  test("sin vincular ofrece vincular desde el perfil (con sesión)", async () => {
    await load(accounts(false, 1));
    expect(container.textContent).toContain("No vinculada");
    mockedFetch.mockImplementation(async () => json({ authorization_url: "about:blank#google" }));
    await click("Vincular con Google");
    const [path, , authenticated] = mockedFetch.mock.calls.at(-1)!;
    expect(path).toBe("/auth/federated/google/link/start");
    expect(authenticated).toBe(true);
  });

  test("muestra qué cuenta quedó vinculada", async () => {
    await load(accounts(true, 2));
    expect(container.textContent).toContain("camila@gmail.example");
    expect(button("Vincular con Google")).toBeUndefined();
  });

  test("si Google es el único método de acceso, avisa y no deja confirmar", async () => {
    await load(accounts(true, 1));
    await click("Desvincular");
    expect(container.querySelector("[role=alertdialog]")?.textContent).toContain("único método de acceso");
    expect((button("Sí, desvincular") as HTMLButtonElement).disabled).toBe(true);
  });

  test("con otro método de acceso desvincula y lo comunica", async () => {
    await load(accounts(true, 2));
    await click("Desvincular");
    expect(container.querySelector("[role=alertdialog]")?.textContent).toContain("Seguirás pudiendo entrar con tu contraseña");
    mockedFetch.mockResolvedValue(json({ message: "ok", accounts: accounts(false, 1) }));
    await click("Sí, desvincular");
    expect(mockedFetch.mock.calls.at(-1)![0]).toBe("/auth/federated/google");
    expect(mockedFetch.mock.calls.at(-1)![1]).toMatchObject({ method: "DELETE" });
    expect(container.textContent).toContain("Cuenta de Google desvinculada");
    expect(container.textContent).toContain("No vinculada");
  });

  test("si la API rechaza la desvinculación se muestra su motivo", async () => {
    await load(accounts(true, 2));
    await click("Desvincular");
    mockedFetch.mockResolvedValue(json({ detail: "Google es tu único método de acceso." }, 409));
    await click("Sí, desvincular");
    expect(container.querySelector("[role=alert]")?.textContent).toContain("único método de acceso");
  });
});

describe("vuelta desde Google", () => {
  test("login con Google NO vinculado: muestra el rechazo, invita a registrarse y no guarda sesión", async () => {
    rememberFlow("login");
    search = new URLSearchParams({ code: "c", state: "s" });
    mockedFetch.mockResolvedValue(json({ detail: "Esta cuenta de Google no está vinculada a ninguna cuenta de Brasaland. Regístrate primero." }, 403, { "X-Federated-Error": "not_linked" }));
    await render(<FederatedCallback />);
    expect(container.textContent).toContain("no está vinculada");
    expect(container.querySelector("a[href='/register']")?.textContent).toContain("Crear mi cuenta");
    expect(saveAccessToken).not.toHaveBeenCalled();
    expect(replace).not.toHaveBeenCalled();
  });

  test("login con cuenta vinculada guarda la sesión y entra", async () => {
    rememberFlow("login");
    search = new URLSearchParams({ code: "c", state: "s" });
    mockedFetch.mockResolvedValue(json({ access_token: "tok", token_type: "bearer" }));
    await render(<FederatedCallback />);
    expect(saveAccessToken).toHaveBeenCalledWith("tok");
    expect(replace).toHaveBeenCalledWith("/");
    expect(mockedFetch.mock.calls[0][2]).toBe(false); // el login no lleva sesión previa
  });

  test("vincular se completa CON sesión y vuelve al perfil con el aviso", async () => {
    rememberFlow("link");
    search = new URLSearchParams({ code: "c", state: "s" });
    mockedFetch.mockResolvedValue(json({ message: "Listo: tu cuenta de Google (a@b.c) quedó vinculada." }));
    await render(<FederatedCallback />);
    expect(mockedFetch.mock.calls[0][0]).toBe("/auth/federated/google/link/complete");
    expect(mockedFetch.mock.calls[0][2]).toBe(true);
    expect(replace).toHaveBeenCalledWith("/account/profile");
    expect(window.sessionStorage.getItem("brasaland_federated_notice")).toContain("quedó vinculada");
  });

  test("sin state o sin flujo recordado no llama a la API", async () => {
    search = new URLSearchParams({ code: "c" });
    await render(<FederatedCallback />);
    expect(mockedFetch).not.toHaveBeenCalled();
    expect(container.textContent).toContain("no es válida o ha caducado");
  });

  test("si el usuario cancela en Google lo dice", async () => {
    rememberFlow("login");
    search = new URLSearchParams({ error: "access_denied" });
    await render(<FederatedCallback />);
    expect(container.textContent).toContain("Cancelaste");
    expect(mockedFetch).not.toHaveBeenCalled();
  });
});
