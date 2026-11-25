/** Visor del audit log: solo Supervisor+, alcance explicado, filtros → query string, paginación y verificación solo para Tecnología. */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { AuditViewer } from "../components/audit-viewer";
import { buildAuditQuery, EMPTY_FILTERS, formatActor, type AuditEntry } from "@/lib/audit";
import { apiFetch } from "@/lib/api-client";
import type { Me } from "@/lib/access";

jest.mock("@/lib/api-client", () => ({ apiFetch: jest.fn(), readApiError: jest.fn(async () => "error"), AUTH_CHANGE_EVENT: "x" }));
const mockedUseMe = jest.fn();
jest.mock("@/lib/access", () => ({ ...jest.requireActual("@/lib/access"), useMe: () => mockedUseMe() }));

const base: Me = { email: "a@b.c", role: "employee", role_id: 1, role_label: "Empleado", rank: 1, department: "marketing", department_id: 3, department_label: "Marketing", capabilities: ["read", "create"] };
const supervisor: Me = { ...base, role: "supervisor", role_label: "Supervisor", rank: 2, department: "procurement", department_label: "Compras", capabilities: ["read", "create", "update", "approve"] };
const platformAdmin: Me = { ...base, role: "admin", role_label: "Admin", rank: 3, department: "technology", department_label: "Tecnología", capabilities: ["read", "create", "update", "approve", "delete", "administer", "cross_department"] };

const entry = (seq: number, patch: Partial<AuditEntry> = {}): AuditEntry => ({
  seq, id: `id-${seq}`, timestamp: "2026-11-24T10:00:00Z", actor_type: "user", actor_id: "2", actor_label: "lucia.procurement@brasaland.example", actor_role: "supervisor",
  actor_department: "procurement", action: "supplier.rate_change", category: "data", resource_type: "supplier", resource_id: "11", department: "procurement",
  outcome: "success", origin: "10.0.0.1", channel: "http", details: { rate: { from: 3, to: 4 } }, hash: "a".repeat(64), ...patch,
});
const json = (body: unknown) => ({ ok: true, status: 200, json: async () => body }) as Response;

let container: HTMLDivElement;
let root: Root;
beforeAll(() => { (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true; });
beforeEach(() => { container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container); (apiFetch as jest.Mock).mockReset(); });
afterEach(() => { act(() => root.unmount()); container.remove(); });
const render = async () => { await act(async () => { root.render(<AuditViewer />); }); };

function mockApi(facets = { actions: ["supplier.rate_change"], resource_types: ["supplier"], categories: ["data"], can_view_security: false }, page: unknown = { items: [entry(2)], total: 1, limit: 50, next_before_seq: null }) {
  (apiFetch as jest.Mock).mockImplementation(async (path: string) => (path.startsWith("/audit-log/facets") ? json(facets) : path.startsWith("/audit-log/verify") ? json({ valid: false, entries: 3, head_seq: 3, head_hash: "b".repeat(64), broken_at_seq: 2, reason: "alterado" }) : json(page)));
}

test("un empleado ve 403 y no se llama a la API", async () => {
  mockedUseMe.mockReturnValue({ me: base, loading: false });
  await render();
  expect(container.textContent).toContain("403");
  expect(apiFetch).not.toHaveBeenCalled();
});

test("un supervisor ve su alcance departamental y las entradas, sin botón de verificación", async () => {
  mockedUseMe.mockReturnValue({ me: supervisor, loading: false });
  mockApi();
  await render();
  expect(container.querySelector("[data-testid=audit-scope]")?.textContent).toContain("solo las acciones sobre datos de negocio de tu departamento");
  expect(container.textContent).toContain("supplier.rate_change");
  expect(container.textContent).toContain("lucia.procurement@brasaland.example");
  expect(container.textContent).not.toContain("Verificar integridad");
});

test("el filtro envía solo los campos rellenos y el visor pide la página al servidor", async () => {
  mockedUseMe.mockReturnValue({ me: supervisor, loading: false });
  mockApi();
  await render();
  const input = container.querySelector('input[placeholder="correo o id"]') as HTMLInputElement;
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
    setter.call(input, "lucia");
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () => { (container.querySelector("form") as HTMLFormElement).dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })); });
  const urls = (apiFetch as jest.Mock).mock.calls.map((c) => c[0] as string);
  expect(urls.at(-1)).toBe("/audit-log?actor=lucia&limit=50");
});

test("«Cargar más» usa el cursor y añade entradas sin repetir", async () => {
  mockedUseMe.mockReturnValue({ me: supervisor, loading: false });
  mockApi(undefined, { items: [entry(5)], total: 2, limit: 50, next_before_seq: 5 });
  await render();
  (apiFetch as jest.Mock).mockImplementation(async (path: string) => (path.startsWith("/audit-log/facets") ? json({ actions: [], resource_types: [], categories: [], can_view_security: false }) : json({ items: [entry(4, { action: "supplier.create" })], total: 2, limit: 50, next_before_seq: null })));
  const more = Array.from(container.querySelectorAll("button")).find((b) => b.textContent === "Cargar más") as HTMLButtonElement;
  await act(async () => { more.click(); });
  const last = (apiFetch as jest.Mock).mock.calls.at(-1)[0] as string;
  expect(last).toContain("before_seq=5");
  expect(container.textContent).toContain("supplier.create");
  expect(container.textContent).toContain("supplier.rate_change");
});

test("el Admin de Tecnología ve todo y puede verificar la cadena; una cadena rota se muestra claramente", async () => {
  mockedUseMe.mockReturnValue({ me: platformAdmin, loading: false });
  mockApi({ actions: ["auth.login"], resource_types: ["session"], categories: ["auth", "data"], can_view_security: true });
  await render();
  expect(container.querySelector("[data-testid=audit-scope]")?.textContent).toContain("Ves TODO el registro");
  const verify = Array.from(container.querySelectorAll("button")).find((b) => b.textContent === "Verificar integridad") as HTMLButtonElement;
  await act(async () => { verify.click(); });
  expect(container.textContent).toContain("CADENA ROTA en la entrada #2");
});

test("agentes y procesos se muestran distintos de las personas", () => {
  expect(formatActor(entry(1, { actor_type: "system", actor_id: "celery-worker", actor_label: "celery-worker" }))).toBe("celery-worker");
  expect(buildAuditQuery({ ...EMPTY_FILTERS, actor_type: "agent", outcome: "denied" }, 50)).toBe("actor_type=agent&outcome=denied&limit=50");
  expect(buildAuditQuery(EMPTY_FILTERS, 50, 9)).toBe("limit=50&before_seq=9");
});
