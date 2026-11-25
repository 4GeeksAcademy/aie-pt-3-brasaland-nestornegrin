import { apiFetch, readApiError } from "./api-client";

// Proveedores y contratos. La API nunca devuelve datos bancarios ni contactos personales de los contratos (se redactan al ingerir).
export interface Supplier { id: string; name: string; country: string; category: string; currency: string; contract_id: string | null; has_contract: boolean }
export interface Alert { id: number; key: string; kind: "price_increase" | "contract_expiry" | "notice_deadline"; supplier_id: string; contract_id: string | null;
  stage: number | null; as_of: string; message: string; detail: Record<string, unknown>; recipients: string[]; created_at: string }
export interface Citation { contract_id: string; clause: string; page: number; quote: string; language: "es" | "en"; confidence: number; doubtful: boolean }
export interface Reply { intent: string; supplier_id: string | null; answer: string; consulted: string[]; consults_used: number; consults_limit: number;
  citations: Citation[]; missing: string[]; truncated: boolean; brief: { communication_id?: number; required_approvers: string[] } | null }
export interface Approval { role: string; staff_id: string; decision: string; ts: string }
export interface Communication { id: number; supplier_id: string; subject: string; body: string; status: "pending_approval" | "approved" | "rejected" | "sent";
  required_roles: string[]; missing_roles: string[]; approvals: Approval[]; created_by: string; created_at: string }

async function json<T>(response: Response, fallback: string): Promise<T> {
  if (!response.ok) throw new Error(await readApiError(response, fallback));
  return (await response.json()) as T;
}
const post = (path: string, body?: unknown) =>
  apiFetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) });

export const ROLE_NAMES: Record<string, string> = { ops_director: "Felipe Guerrero (Operaciones)", ceo: "Mariana Restrepo (CEO)", procurement_lead: "Lucía Fernández (Compras)" };
export const KIND_LABELS: Record<Alert["kind"], string> = { price_increase: "Subida de precio", contract_expiry: "Vencimiento de contrato", notice_deadline: "Fecha límite de preaviso" };
export const STATUS_LABELS: Record<Communication["status"], string> = { pending_approval: "Pendiente de aprobación", approved: "Aprobada (lista para enviar)", rejected: "Rechazada", sent: "Enviada" };

/** Quién falta por aprobar, en lenguaje de la empresa. */
export function waitingOn(comm: Pick<Communication, "status" | "missing_roles">): string {
  if (comm.status !== "pending_approval") return "";
  return comm.missing_roles.map((r) => ROLE_NAMES[r] ?? r).join(" y ");
}
/** Una comunicación solo se puede enviar con TODAS las aprobaciones exigidas. */
export function canSend(comm: Pick<Communication, "status">): boolean { return comm.status === "approved"; }
/** Etiqueta de una cita: contrato, cláusula y página (la fuente de toda afirmación contractual). */
export function citationLabel(c: Pick<Citation, "contract_id" | "clause" | "page" | "doubtful">): string {
  return `${c.contract_id}, cláusula ${c.clause}, p. ${c.page}${c.doubtful ? " (extracción dudosa)" : ""}`;
}

export const supplierContractsApi = {
  suppliers: async () => json<Supplier[]>(await apiFetch("/supplier-contracts/suppliers"), "No se pudieron cargar los proveedores."),
  seed: async () => json<{ load_date: string; price_rows: number; alerts: number }>(await post("/supplier-contracts/seed"), "No se pudieron cargar los datos."),
  alerts: async () => json<Alert[]>(await apiFetch("/supplier-contracts/alerts"), "No se pudieron cargar las alertas."),
  ask: async (question: string) => json<Reply>(await post("/supplier-contracts/ask", { question }), "No se pudo responder."),
  brief: async (supplier_id: string, draft_message: boolean) => json<Reply>(await post("/supplier-contracts/brief", { supplier_id, draft_message }), "No se pudo preparar el brief."),
  communications: async () => json<Communication[]>(await apiFetch("/supplier-contracts/communications"), "No se pudieron cargar las comunicaciones."),
  decide: async (id: number, decision: "approve" | "reject", comment?: string) =>
    json<Communication>(await post(`/supplier-contracts/communications/${id}/decision`, { decision, comment }), "No se pudo registrar la decisión."),
  send: async (id: number) => json<Communication>(await post(`/supplier-contracts/communications/${id}/send`), "No se pudo enviar."),
};
