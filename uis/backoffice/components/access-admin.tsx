"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import { apiFetch, readApiError } from "@/lib/api-client";
import { can, useMe, type Capability } from "@/lib/access";

type Role = { id: number; code: string; name: string; label: string; rank: number; description: string; capabilities: Capability[] };
type Department = { id: number; code: string; name: string; label: string; responsible: string; description: string };
type UserRow = { id: number; email: string; role_id: number; role: string; department_id: number | null; department: string | null; is_active: boolean };

const ALL_CAPABILITIES: Capability[] = ["read", "create", "update", "approve", "delete", "administer", "cross_department"];
const JSON_HEADERS = { "Content-Type": "application/json" };

async function getJson<T>(path: string): Promise<T> {
  const response = await apiFetch(path);
  if (!response.ok) throw new Error(await readApiError(response, "No se pudo cargar la información."));
  return (await response.json()) as T;
}

export function AccessAdmin() {
  const { me, loading: loadingMe } = useMe();
  const [roles, setRoles] = useState<Role[]>([]);
  const [departments, setDepartments] = useState<Department[]>([]);
  const [users, setUsers] = useState<UserRow[]>([]);
  const [draft, setDraft] = useState<Record<number, { role_id?: number; department_id?: number | null }>>({});
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [newDepartment, setNewDepartment] = useState({ code: "", name: "", label: "", responsible: "" });
  const [newRole, setNewRole] = useState({ code: "", name: "", label: "", rank: "4", capabilities: ["read", "create"] as Capability[] });

  const isAdmin = can(me, "administer");

  const load = useCallback(async () => {
    setError(null);
    try {
      const [r, d, u] = await Promise.all([getJson<Role[]>("/roles"), getJson<Department[]>("/departments"), getJson<UserRow[]>("/users")]);
      setRoles(r);
      setDepartments(d);
      setUsers(u);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "No se pudo conectar con la API.");
    }
  }, []);

  useEffect(() => {
    if (isAdmin) void Promise.resolve().then(load);
  }, [isAdmin, load]);

  async function send(path: string, method: string, body: unknown, done: string): Promise<boolean> {
    setError(null);
    setNotice(null);
    try {
      const response = await apiFetch(path, { method, headers: JSON_HEADERS, body: JSON.stringify(body) });
      if (!response.ok) {
        setError(await readApiError(response, "La API rechazó el cambio."));
        return false;
      }
      setNotice(done);
      await load();
      return true;
    } catch {
      setError("No se pudo conectar con el servidor. Inténtalo de nuevo.");
      return false;
    }
  }

  async function saveAssignment(user: UserRow) {
    const change = draft[user.id];
    if (!change) return;
    // Solo se envía lo que cambió: rol y departamento son ejes independientes.
    if (await send(`/users/${user.id}/assignment`, "PATCH", change, `Asignación de ${user.email} actualizada.`)) {
      setDraft((current) => Object.fromEntries(Object.entries(current).filter(([id]) => Number(id) !== user.id)));
    }
  }

  async function createDepartment(event: FormEvent) {
    event.preventDefault();
    if (await send("/departments", "POST", newDepartment, "Departamento creado.")) setNewDepartment({ code: "", name: "", label: "", responsible: "" });
  }

  async function createRole(event: FormEvent) {
    event.preventDefault();
    if (await send("/roles", "POST", { ...newRole, rank: Number(newRole.rank) }, "Rol creado.")) setNewRole({ ...newRole, code: "", name: "", label: "" });
  }

  if (loadingMe) return <p className="text-sm text-zinc-500">Comprobando permisos...</p>;
  if (!isAdmin) {
    return (
      <p role="alert" className="rounded-xl border border-red-200 bg-red-50 p-6 text-sm font-semibold text-red-800">
        403 · Esta vista es solo para el rol Admin. Tu rol actual es {me?.role_label ?? "desconocido"}.
      </p>
    );
  }

  const inputClass = "rounded-lg border border-zinc-300 px-3 py-2 text-sm";
  return (
    <div className="space-y-10">
      {error ? <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm font-semibold text-red-800">{error}</p> : null}
      {notice ? <p role="status" className="rounded-lg bg-emerald-50 p-3 text-sm font-semibold text-emerald-800">{notice}</p> : null}

      <section aria-labelledby="users-title">
        <h2 id="users-title" className="text-xl font-black text-zinc-900">Usuarios</h2>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[720px] text-left text-sm">
            <thead><tr className="border-b border-zinc-200 text-xs uppercase tracking-wide text-zinc-500"><th className="pb-2 pr-4">Correo</th><th className="pb-2 pr-4">Rol</th><th className="pb-2 pr-4">Departamento</th><th className="pb-2" /></tr></thead>
            <tbody>
              {users.map((user) => {
                const change = draft[user.id] ?? {};
                const roleValue = change.role_id ?? user.role_id;
                const departmentValue = "department_id" in change ? change.department_id : user.department_id;
                return (
                  <tr key={user.id} className="border-b border-zinc-100">
                    <td className="py-2 pr-4 font-semibold text-zinc-800">{user.email}</td>
                    <td className="py-2 pr-4">
                      <select aria-label={`Rol de ${user.email}`} value={roleValue} onChange={(event) => setDraft((c) => ({ ...c, [user.id]: { ...c[user.id], role_id: Number(event.target.value) } }))} className={inputClass}>
                        {roles.map((role) => <option key={role.id} value={role.id}>{role.label} (rango {role.rank})</option>)}
                      </select>
                    </td>
                    <td className="py-2 pr-4">
                      <select aria-label={`Departamento de ${user.email}`} value={departmentValue ?? ""} onChange={(event) => setDraft((c) => ({ ...c, [user.id]: { ...c[user.id], department_id: event.target.value === "" ? null : Number(event.target.value) } }))} className={inputClass}>
                        <option value="">Sin departamento</option>
                        {departments.map((department) => <option key={department.id} value={department.id}>{department.label}</option>)}
                      </select>
                    </td>
                    <td className="py-2"><button type="button" disabled={!draft[user.id]} onClick={() => void saveAssignment(user)} className="rounded-lg bg-zinc-900 px-3 py-1 text-xs font-bold text-white hover:bg-red-800 disabled:opacity-40">Guardar</button></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      <section aria-labelledby="roles-title">
        <h2 id="roles-title" className="text-xl font-black text-zinc-900">Roles (qué puede hacer)</h2>
        <ul className="mt-3 space-y-2 text-sm">
          {roles.map((role) => (
            <li key={role.id} className="rounded-lg border border-zinc-200 bg-white p-3">
              <span className="font-bold text-zinc-900">{role.label}</span> <span className="text-zinc-500">· {role.code} · rango {role.rank}</span>
              <p className="mt-1 text-zinc-600">{role.capabilities.join(", ")}</p>
            </li>
          ))}
        </ul>
        <form onSubmit={createRole} className="mt-4 grid gap-3 sm:grid-cols-4">
          <input required aria-label="Código del rol" placeholder="código" value={newRole.code} onChange={(e) => setNewRole({ ...newRole, code: e.target.value })} className={inputClass} />
          <input required aria-label="Nombre del rol" placeholder="nombre" value={newRole.name} onChange={(e) => setNewRole({ ...newRole, name: e.target.value, label: e.target.value })} className={inputClass} />
          <input required aria-label="Rango del rol" type="number" min="1" value={newRole.rank} onChange={(e) => setNewRole({ ...newRole, rank: e.target.value })} className={inputClass} />
          <button type="submit" className="rounded-lg bg-red-800 px-4 py-2 text-sm font-bold text-white hover:bg-red-900">Crear rol</button>
          <fieldset className="flex flex-wrap gap-3 text-xs text-zinc-700 sm:col-span-4">
            <legend className="sr-only">Capacidades</legend>
            {ALL_CAPABILITIES.map((capability) => (
              <label key={capability} className="flex items-center gap-1">
                <input type="checkbox" checked={newRole.capabilities.includes(capability)} onChange={(e) => setNewRole({ ...newRole, capabilities: e.target.checked ? [...newRole.capabilities, capability] : newRole.capabilities.filter((c) => c !== capability) })} />
                {capability}
              </label>
            ))}
          </fieldset>
        </form>
      </section>

      <section aria-labelledby="departments-title">
        <h2 id="departments-title" className="text-xl font-black text-zinc-900">Departamentos (qué datos le competen)</h2>
        <ul className="mt-3 grid gap-2 text-sm sm:grid-cols-2">
          {departments.map((department) => (
            <li key={department.id} className="rounded-lg border border-zinc-200 bg-white p-3">
              <span className="font-bold text-zinc-900">{department.label}</span> <span className="text-zinc-500">· {department.code}</span>
              {department.responsible ? <p className="text-zinc-600">Responsable: {department.responsible}</p> : null}
            </li>
          ))}
        </ul>
        <form onSubmit={createDepartment} className="mt-4 grid gap-3 sm:grid-cols-4">
          <input required aria-label="Código del departamento" placeholder="código" value={newDepartment.code} onChange={(e) => setNewDepartment({ ...newDepartment, code: e.target.value })} className={inputClass} />
          <input required aria-label="Nombre del departamento" placeholder="nombre" value={newDepartment.name} onChange={(e) => setNewDepartment({ ...newDepartment, name: e.target.value, label: e.target.value })} className={inputClass} />
          <input aria-label="Responsable" placeholder="responsable" value={newDepartment.responsible} onChange={(e) => setNewDepartment({ ...newDepartment, responsible: e.target.value })} className={inputClass} />
          <button type="submit" className="rounded-lg bg-red-800 px-4 py-2 text-sm font-bold text-white hover:bg-red-900">Crear departamento</button>
        </form>
      </section>
    </div>
  );
}
