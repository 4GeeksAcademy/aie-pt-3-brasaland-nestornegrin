import { apiFetch, readApiError } from "@/lib/api-client";

/** Autenticación federada (Google). Dos flujos separados: VINCULAR (con sesión, desde el perfil) y ENTRAR (solo cuentas ya vinculadas). */
export type Flow = "link" | "login";

export type LinkedProvider = { provider: string; linked: boolean; email_at_link_time: string | null; linked_at: string | null };
export type LinkedAccounts = { has_password: boolean; access_methods: number; providers: LinkedProvider[] };
export type ProvidersInfo = { enabled: boolean; providers: { provider: string; configured: boolean }[] };

const FLOW_KEY = "brasaland_federated_flow";
const NOTICE_KEY = "brasaland_federated_notice";

export const NOT_LINKED_FALLBACK =
  "Esta cuenta de Google no está vinculada a ninguna cuenta de Brasaland. Regístrate primero con tu correo y contraseña y vincula Google desde tu perfil.";

/** `redirect_uri` del callback: coincide EXACTAMENTE con uno de los permitidos en la API (OAUTH_REDIRECT_URI / OAUTH_ALLOWED_REDIRECT_URIS). */
export function callbackUri(): string {
  return `${window.location.origin}/auth/callback/google`;
}

function store(key: string, value: string | null): void {
  try {
    if (value === null) window.sessionStorage.removeItem(key);
    else window.sessionStorage.setItem(key, value);
  } catch {
    // sessionStorage puede no estar disponible (modo privado): el callback pedirá reiniciar el flujo.
  }
}

function read(key: string): string | null {
  try {
    return window.sessionStorage.getItem(key);
  } catch {
    return null;
  }
}

export const rememberFlow = (flow: Flow) => store(FLOW_KEY, flow);
export const recallFlow = (): Flow | null => (read(FLOW_KEY) === "link" ? "link" : read(FLOW_KEY) === "login" ? "login" : null);
export const forgetFlow = () => store(FLOW_KEY, null);
export const setNotice = (message: string) => store(NOTICE_KEY, message);
export function takeNotice(): string | null {
  const message = read(NOTICE_KEY);
  store(NOTICE_KEY, null);
  return message;
}

export async function fetchProviders(): Promise<ProvidersInfo | null> {
  try {
    const response = await apiFetch("/auth/federated/providers", {}, false);
    return response.ok ? ((await response.json()) as ProvidersInfo) : null;
  } catch {
    return null;
  }
}

export async function fetchAccounts(): Promise<LinkedAccounts> {
  const response = await apiFetch("/auth/federated");
  if (!response.ok) throw new Error(await readApiError(response, "No se pudieron cargar tus cuentas vinculadas."));
  return (await response.json()) as LinkedAccounts;
}

/** Pide la URL de autorización y navega a Google. El `state` lo emite y valida la API. */
export async function startFlow(flow: Flow, provider = "google"): Promise<void> {
  const response = await apiFetch(`/auth/federated/${provider}/${flow}/start`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ redirect_uri: callbackUri() }),
  }, flow === "link");
  if (!response.ok) throw new Error(await readApiError(response, "No se pudo iniciar la conexión con Google."));
  const { authorization_url } = (await response.json()) as { authorization_url: string };
  rememberFlow(flow);
  window.location.assign(authorization_url);
}

export async function unlinkProvider(provider = "google"): Promise<LinkedAccounts> {
  const response = await apiFetch(`/auth/federated/${provider}`, { method: "DELETE" });
  if (!response.ok) throw new Error(await readApiError(response, "No se pudo desvincular la cuenta."));
  return ((await response.json()) as { accounts: LinkedAccounts }).accounts;
}
