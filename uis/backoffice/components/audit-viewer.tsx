"use client";

import { Fragment, useCallback, useEffect, useState, type FormEvent } from "react";
import { apiFetch, readApiError } from "@/lib/api-client";
import { useMe } from "@/lib/access";
import {
  ACTOR_LABELS, CATEGORY_LABELS, EMPTY_FILTERS, OUTCOME_LABELS, buildAuditQuery, formatActor,
  type AuditEntry, type AuditFacets, type AuditFilters, type AuditPage, type VerifyResult,
} from "@/lib/audit";

const PAGE_SIZE = 50;
const BADGE: Record<string, string> = {
  user: "bg-zinc-100 text-zinc-800", agent: "bg-violet-100 text-violet-900", system: "bg-sky-100 text-sky-900", anonymous: "bg-amber-100 text-amber-900",
  success: "bg-emerald-100 text-emerald-900", failure: "bg-orange-100 text-orange-900", denied: "bg-red-100 text-red-900",
};

async function getJson<T>(path: string): Promise<T> {
  const response = await apiFetch(path);
  if (!response.ok) throw new Error(await readApiError(response, "No se pudo cargar el registro de auditoría."));
  return (await response.json()) as T;
}

function Badge({ kind, children }: { kind: string; children: React.ReactNode }) {
  return <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-bold ${BADGE[kind] ?? "bg-zinc-100 text-zinc-800"}`}>{children}</span>;
}

export function AuditViewer() {
  const { me, loading: loadingMe } = useMe();
  const [filters, setFilters] = useState<AuditFilters>(EMPTY_FILTERS);
  const [applied, setApplied] = useState<AuditFilters>(EMPTY_FILTERS);
  const [facets, setFacets] = useState<AuditFacets | null>(null);
  const [items, setItems] = useState<AuditEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [cursor, setCursor] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [openId, setOpenId] = useState<string | null>(null);
  const [verify, setVerify] = useState<VerifyResult | null>(null);

  const isViewer = Boolean(me && me.rank >= 2);

  const load = useCallback(async (query: AuditFilters, before: number | null, append: boolean) => {
    setLoading(true);
    setError(null);
    try {
      const page = await getJson<AuditPage>(`/audit-log?${buildAuditQuery(query, PAGE_SIZE, before)}`);
      setItems((current) => (append ? [...current, ...page.items] : page.items));
      setTotal(page.total);
      setCursor(page.next_before_seq);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "No se pudo conectar con la API.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!isViewer) return;
    void Promise.resolve().then(async () => {
      try { setFacets(await getJson<AuditFacets>("/audit-log/facets")); } catch { setFacets(null); }
      await load(EMPTY_FILTERS, null, false);
    });
  }, [isViewer, load]);

  function apply(event: FormEvent) {
    event.preventDefault();
    setApplied(filters);
    setOpenId(null);
    void load(filters, null, false);
  }

  function clear() {
    setFilters(EMPTY_FILTERS);
    setApplied(EMPTY_FILTERS);
    void load(EMPTY_FILTERS, null, false);
  }

  async function runVerify() {
    setVerify(null);
    try { setVerify(await getJson<VerifyResult>("/audit-log/verify")); } catch (requestError) { setError(requestError instanceof Error ? requestError.message : "No se pudo verificar."); }
  }

  if (loadingMe) return <p className="text-sm text-zinc-500">Comprobando permisos...</p>;
  if (!isViewer) {
    return (
      <p role="alert" className="rounded-xl border border-red-200 bg-red-50 p-6 text-sm font-semibold text-red-800">
        403 · El registro de auditoría está disponible para Supervisores y Admins. Tu rol no tiene acceso.
      </p>
    );
  }

  const set = (key: keyof AuditFilters) => (event: { target: { value: string } }) => setFilters((current) => ({ ...current, [key]: event.target.value }));
  const field = "mt-1 w-full rounded-lg border border-zinc-300 bg-white px-2 py-1.5 text-sm text-zinc-900";
  const label = "block text-xs font-bold uppercase tracking-wide text-zinc-600";

  return (
    <div className="space-y-6">
      <p className="rounded-lg bg-zinc-50 p-3 text-sm text-zinc-700" data-testid="audit-scope">
        {facets?.can_view_security
          ? "Ves TODO el registro: datos de negocio y eventos de seguridad (inicios de sesión, permisos, cuentas externas, procesos)."
          : `Ves solo las acciones sobre datos de negocio de tu departamento${me?.department_label ? ` (${me.department_label})` : ""}. Los eventos de seguridad son de Tecnología.`}
      </p>

      <form onSubmit={apply} className="grid gap-3 rounded-xl border border-zinc-200 bg-white p-4 sm:grid-cols-2 lg:grid-cols-4" aria-label="Filtros del registro">
        <label className={label}>Actor<input className={field} value={filters.actor} onChange={set("actor")} placeholder="correo o id" /></label>
        <label className={label}>Tipo de actor
          <select className={field} value={filters.actor_type} onChange={set("actor_type")}>
            <option value="">Todos</option>
            {Object.entries(ACTOR_LABELS).map(([value, text]) => <option key={value} value={value}>{text}</option>)}
          </select>
        </label>
        <label className={label}>Acción
          <select className={field} value={filters.action} onChange={set("action")}>
            <option value="">Todas</option>
            {(facets?.actions ?? []).map((value) => <option key={value} value={value}>{value}</option>)}
          </select>
        </label>
        <label className={label}>Recurso
          <select className={field} value={filters.resource_type} onChange={set("resource_type")}>
            <option value="">Todos</option>
            {(facets?.resource_types ?? []).map((value) => <option key={value} value={value}>{value}</option>)}
          </select>
        </label>
        <label className={label}>Categoría
          <select className={field} value={filters.category} onChange={set("category")}>
            <option value="">Todas</option>
            {(facets?.categories ?? []).map((value) => <option key={value} value={value}>{CATEGORY_LABELS[value] ?? value}</option>)}
          </select>
        </label>
        <label className={label}>Resultado
          <select className={field} value={filters.outcome} onChange={set("outcome")}>
            <option value="">Todos</option>
            {Object.entries(OUTCOME_LABELS).map(([value, text]) => <option key={value} value={value}>{text}</option>)}
          </select>
        </label>
        <label className={label}>Desde<input type="datetime-local" className={field} value={filters.date_from} onChange={set("date_from")} /></label>
        <label className={label}>Hasta<input type="datetime-local" className={field} value={filters.date_to} onChange={set("date_to")} /></label>
        <div className="flex items-end gap-2 sm:col-span-2 lg:col-span-4">
          <button type="submit" className="rounded-lg bg-red-800 px-4 py-2 text-sm font-bold text-white hover:bg-red-900">Filtrar</button>
          <button type="button" onClick={clear} className="rounded-lg border border-zinc-300 px-4 py-2 text-sm font-bold text-zinc-700 hover:bg-zinc-50">Limpiar</button>
          {facets?.can_view_security ? (
            <button type="button" onClick={() => void runVerify()} className="ml-auto rounded-lg border border-zinc-300 px-4 py-2 text-sm font-bold text-zinc-700 hover:bg-zinc-50">Verificar integridad</button>
          ) : null}
        </div>
      </form>

      {verify ? (
        <p role="status" className={`rounded-lg p-3 text-sm font-semibold ${verify.valid ? "bg-emerald-50 text-emerald-900" : "bg-red-50 text-red-900"}`}>
          {verify.valid
            ? `Cadena íntegra: ${verify.entries} entradas verificadas. Hash de cabeza: ${verify.head_hash.slice(0, 16)}…`
            : `CADENA ROTA en la entrada #${verify.broken_at_seq}: ${verify.reason}`}
        </p>
      ) : null}
      {error ? <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm font-semibold text-red-800">{error}</p> : null}

      <div>
        <p className="text-sm text-zinc-600" aria-live="polite">{loading && items.length === 0 ? "Cargando..." : `${total} entradas${Object.values(applied).some(Boolean) ? " con estos filtros" : ""}`}</p>
        <div className="mt-2 overflow-x-auto">
          <table className="w-full min-w-[880px] text-left text-sm">
            <thead>
              <tr className="border-b border-zinc-200 text-xs uppercase tracking-wide text-zinc-500">
                <th className="pb-2 pr-3">Fecha</th><th className="pb-2 pr-3">Actor</th><th className="pb-2 pr-3">Acción</th><th className="pb-2 pr-3">Recurso</th><th className="pb-2 pr-3">Resultado</th><th className="pb-2 pr-3">Origen</th><th className="pb-2"><span className="sr-only">Detalle</span></th>
              </tr>
            </thead>
            <tbody>
              {items.map((entry) => (
                <Fragment key={entry.id}>
                  <tr className="border-b border-zinc-100 align-top">
                    <td className="py-2 pr-3 whitespace-nowrap text-zinc-700">{new Date(entry.timestamp).toLocaleString()}</td>
                    <td className="py-2 pr-3"><Badge kind={entry.actor_type}>{ACTOR_LABELS[entry.actor_type]}</Badge><div className="mt-0.5 font-semibold text-zinc-800">{formatActor(entry)}</div></td>
                    <td className="py-2 pr-3 font-mono text-xs text-zinc-800">{entry.action}</td>
                    <td className="py-2 pr-3 text-zinc-700">{entry.resource_type}{entry.resource_id ? ` · ${entry.resource_id}` : ""}</td>
                    <td className="py-2 pr-3"><Badge kind={entry.outcome}>{OUTCOME_LABELS[entry.outcome]}</Badge></td>
                    <td className="py-2 pr-3 text-zinc-600">{entry.origin}</td>
                    <td className="py-2"><button type="button" onClick={() => setOpenId(openId === entry.id ? null : entry.id)} aria-expanded={openId === entry.id} className="text-xs font-bold text-red-800 hover:text-red-950">{openId === entry.id ? "Ocultar" : "Detalle"}</button></td>
                  </tr>
                  {openId === entry.id ? (
                    <tr className="border-b border-zinc-100 bg-zinc-50">
                      <td colSpan={7} className="p-3">
                        <pre className="overflow-x-auto whitespace-pre-wrap text-xs text-zinc-800">{JSON.stringify({ seq: entry.seq, rol: entry.actor_role, departamento_actor: entry.actor_department, departamento_recurso: entry.department, canal: entry.channel, detalle: entry.details, hash: entry.hash }, null, 2)}</pre>
                      </td>
                    </tr>
                  ) : null}
                </Fragment>
              ))}
            </tbody>
          </table>
          {!loading && items.length === 0 && !error ? <p className="py-6 text-sm text-zinc-500">No hay entradas con estos filtros.</p> : null}
        </div>
        {cursor ? (
          <button type="button" disabled={loading} onClick={() => void load(applied, cursor, true)} className="mt-3 rounded-lg border border-zinc-300 px-4 py-2 text-sm font-bold text-zinc-700 hover:bg-zinc-50 disabled:opacity-50">
            {loading ? "Cargando..." : "Cargar más"}
          </button>
        ) : null}
      </div>
    </div>
  );
}
