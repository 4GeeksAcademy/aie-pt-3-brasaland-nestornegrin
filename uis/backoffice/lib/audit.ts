/** Audit log: tipos de la API (`/audit-log`) y utilidades del visor. El alcance (qué ve cada persona) lo decide SIEMPRE el servidor. */

export type ActorType = "user" | "agent" | "system" | "anonymous";
export type Outcome = "success" | "failure" | "denied";

export type AuditEntry = {
  seq: number;
  id: string;
  timestamp: string;
  actor_type: ActorType;
  actor_id: string;
  actor_label: string | null;
  actor_role: string | null;
  actor_department: string | null;
  action: string;
  category: string;
  resource_type: string;
  resource_id: string | null;
  department: string | null;
  outcome: Outcome;
  origin: string;
  channel: "http" | "process";
  details: Record<string, unknown>;
  hash: string;
};

export type AuditPage = { items: AuditEntry[]; total: number; limit: number; next_before_seq: number | null };
export type AuditFacets = { actions: string[]; resource_types: string[]; categories: string[]; can_view_security: boolean };
export type VerifyResult = { valid: boolean; entries: number; head_seq: number; head_hash: string; broken_at_seq: number | null; reason: string | null };

export type AuditFilters = {
  actor: string;
  actor_type: string;
  action: string;
  category: string;
  resource_type: string;
  outcome: string;
  date_from: string; // valor de <input type="datetime-local">
  date_to: string;
};

export const EMPTY_FILTERS: AuditFilters = { actor: "", actor_type: "", action: "", category: "", resource_type: "", outcome: "", date_from: "", date_to: "" };

export const ACTOR_LABELS: Record<ActorType, string> = { user: "Persona", agent: "Agente de IA", system: "Proceso del sistema", anonymous: "Sin identificar" };
export const OUTCOME_LABELS: Record<Outcome, string> = { success: "Correcta", failure: "Fallida", denied: "Denegada" };
export const CATEGORY_LABELS: Record<string, string> = {
  auth: "Sesiones", access: "Roles y permisos", federated: "Cuentas externas", audit: "Auditoría", process: "Procesos", data: "Datos de negocio",
};

/** Query string con solo los filtros rellenos. Las fechas locales del navegador se envían como instantes UTC. */
export function buildAuditQuery(filters: AuditFilters, limit: number, beforeSeq?: number | null): string {
  const params = new URLSearchParams();
  (Object.keys(filters) as (keyof AuditFilters)[]).forEach((key) => {
    const value = filters[key].trim();
    if (!value) return;
    if (key === "date_from" || key === "date_to") {
      const moment = new Date(value);
      if (!Number.isNaN(moment.getTime())) params.set(key, moment.toISOString());
    } else {
      params.set(key, value);
    }
  });
  params.set("limit", String(limit));
  if (beforeSeq) params.set("before_seq", String(beforeSeq));
  return params.toString();
}

export function formatActor(entry: AuditEntry): string {
  if (entry.actor_type === "system") return entry.actor_id;
  return entry.actor_label ?? entry.actor_id;
}
