/** Interfaz por capacidades: la vista de administración solo existe para Admin y las acciones se ocultan según el rol. */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { AccessAdmin } from "../components/access-admin";
import { Can } from "../components/can";
import { can, seesAllDepartments, type Me } from "@/lib/access";
import { apiFetch } from "@/lib/api-client";

jest.mock("@/lib/api-client", () => ({ apiFetch: jest.fn(), readApiError: jest.fn(async () => "error"), AUTH_CHANGE_EVENT: "x" }));
const mockedUseMe = jest.fn();
jest.mock("@/lib/access", () => ({
  ...jest.requireActual("@/lib/access"),
  useMe: () => mockedUseMe(),
}));

const base: Me = { email: "a@b.c", role: "employee", role_id: 1, role_label: "Empleado", rank: 1, department: "marketing", department_id: 3, department_label: "Marketing", capabilities: ["read", "create"] };
const supervisor: Me = { ...base, role: "supervisor", role_label: "Supervisor", rank: 2, capabilities: ["read", "create", "update", "approve"] };
const admin: Me = { ...base, role: "admin", role_label: "Admin", rank: 3, capabilities: ["read", "create", "update", "approve", "delete", "administer", "cross_department"] };

let container: HTMLDivElement;
let root: Root;
beforeAll(() => { (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true; });
beforeEach(() => { container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container); (apiFetch as jest.Mock).mockReset(); });
afterEach(() => { act(() => root.unmount()); container.remove(); });

const render = async (node: React.ReactNode) => { await act(async () => { root.render(node); }); };
const json = (body: unknown) => ({ ok: true, status: 200, json: async () => body }) as Response;

test("can() y seesAllDepartments() leen las capacidades del rol", () => {
  expect(can(base, "create")).toBe(true);
  expect(can(base, "update")).toBe(false);
  expect(can(supervisor, "approve")).toBe(true);
  expect(can(supervisor, "delete")).toBe(false);
  expect(can(null, "read")).toBe(false); // sin sesión, nunca se asume permiso
  expect(seesAllDepartments(admin)).toBe(true);
  expect(seesAllDepartments(supervisor)).toBe(false);
});

test("<Can> oculta la acción a quien no tiene la capacidad", async () => {
  mockedUseMe.mockReturnValue({ me: base, loading: false });
  await render(<Can capability="approve"><button>Aprobar</button></Can>);
  expect(container.textContent).not.toContain("Aprobar");
  mockedUseMe.mockReturnValue({ me: supervisor, loading: false });
  await render(<Can capability="approve"><button>Aprobar</button></Can>);
  expect(container.textContent).toContain("Aprobar");
});

test.each([["employee", base], ["supervisor", supervisor]])("la vista de administración muestra 403 y no llama a la API para %s", async (_name, me) => {
  mockedUseMe.mockReturnValue({ me, loading: false });
  await render(<AccessAdmin />);
  expect(container.querySelector("[role=alert]")?.textContent).toContain("403");
  expect(apiFetch).not.toHaveBeenCalled();
});

test("el Admin lista roles, departamentos y usuarios y asigna rol y departamento por separado", async () => {
  mockedUseMe.mockReturnValue({ me: admin, loading: false });
  const roles = [{ id: 1, code: "employee", name: "Employee", label: "Empleado", rank: 1, description: "", capabilities: ["read", "create"] }, { id: 2, code: "supervisor", name: "Supervisor", label: "Supervisor", rank: 2, description: "", capabilities: ["read"] }];
  const departments = [{ id: 1, code: "marketing", name: "Marketing", label: "Marketing", responsible: "", description: "" }, { id: 2, code: "procurement", name: "Procurement", label: "Compras", responsible: "", description: "" }];
  const users = [{ id: 7, email: "lucia@x.test", role_id: 2, role: "supervisor", department_id: 2, department: "procurement", is_active: true }];
  (apiFetch as jest.Mock).mockImplementation(async (path: string, init?: RequestInit) => {
    if (init?.method === "PATCH") return json({});
    return json(path === "/roles" ? roles : path === "/departments" ? departments : users);
  });
  await render(<AccessAdmin />);
  const select = container.querySelector<HTMLSelectElement>("select[aria-label='Departamento de lucia@x.test']")!;
  await act(async () => { select.value = "1"; select.dispatchEvent(new Event("change", { bubbles: true })); });
  const save = Array.from(container.querySelectorAll("button")).find((b) => b.textContent === "Guardar")!;
  await act(async () => { save.click(); });
  const patch = (apiFetch as jest.Mock).mock.calls.find(([, init]) => init?.method === "PATCH")!;
  expect(patch[0]).toBe("/users/7/assignment");
  expect(JSON.parse(patch[1].body)).toEqual({ department_id: 1 }); // solo el departamento: el rol no viaja
});
