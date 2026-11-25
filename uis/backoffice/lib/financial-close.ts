import { apiFetch, readApiError } from "./api-client";

// Cierre financiero mensual. La API nunca devuelve salarios individuales ni datos bancarios (se redactan al ingerir).
export type ReportStatus = "pending_review" | "rejected" | "approved" | "distributed";
export interface ReportSummary { id: number; period: string; version: number; status: ReportStatus; content_hash: string; created_at: string; decided_at: string | null; distributed_at: string | null }
export interface Review { id: number; staff_id: string; decision: "approve" | "reject"; comment: string; ts: string }
export interface Report extends ReportSummary { markdown: string; reviews: Review[]; content: { summary: string[]; fx: string; missing: { kind: string; text: string }[]; deviations: { country_name: string; label: string; pct: string }[] } }
export interface FigureRecord { entry_id: string | null; file: string; row: number; date: string | null; amount: string | null; description: string | null; metric: string | null }
export interface Figure { id: string; label: string; value: string | null; unit: string; formula: string; status: string; sources: { file: string; row: number; entry_id: string | null }[]; records: FigureRecord[] }
export interface AuditEvent { id: number; ts: string; actor_type: string; actor_id: string; action: string; subject: string; detail: Record<string, unknown> }

async function json<T>(response: Response, fallback: string): Promise<T> {
  if (!response.ok) throw new Error(await readApiError(response, fallback));
  return (await response.json()) as T;
}
const post = (path: string, body?: unknown) =>
  apiFetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) });

export const STATUS_LABELS: Record<ReportStatus, string> = {
  pending_review: "Pendiente de revisión (Felipe Guerrero)", rejected: "Rechazado (hay una versión nueva)", approved: "Aprobado", distributed: "Aprobado y distribuido",
};
export const ACTOR_LABELS: Record<string, string> = { automated_process: "Proceso automatizado (agente)", user: "Persona" };

/** Solo un informe pendiente se puede revisar; la API lo hace cumplir (y solo el revisor designado). */
export function canReview(report: { status: ReportStatus }): boolean { return report.status === "pending_review"; }
/** Un rechazo exige comentarios: sin ellos no hay forma de que la nueva versión los tenga en cuenta. */
export function rejectionError(comment: string): string { return comment.trim() ? "" : "Para rechazar, escribe qué hay que corregir."; }
/** Una cifra con `partial` o `missing` se muestra como tal, nunca como un número limpio. */
export function figureWarning(status: string): string { return status === "partial" ? "Cifra parcial: faltan datos" : status === "missing" ? "Sin datos" : ""; }
/** Origen legible de una cifra: el entry_id si lo hay, o archivo:fila. */
export function sourceLabel(s: { file: string; row: number; entry_id: string | null }): string { return s.entry_id ?? `${s.file}:${s.row}`; }
/** Los informes se listan del periodo más reciente al más antiguo y, dentro del periodo, la versión más nueva primero. */
export function sortReports<T extends Pick<ReportSummary, "period" | "version">>(rows: T[]): T[] {
  return [...rows].sort((a, b) => (a.period === b.period ? b.version - a.version : a.period < b.period ? 1 : -1));
}

export const financialCloseApi = {
  reports: async () => json<ReportSummary[]>(await apiFetch("/financial-close/reports"), "No se pudieron cargar los informes."),
  report: async (id: number) => json<Report>(await apiFetch(`/financial-close/reports/${id}`), "No se pudo cargar el informe."),
  figure: async (id: number, figureId: string) => json<Figure>(await apiFetch(`/financial-close/reports/${id}/figures/${encodeURIComponent(figureId)}`), "No se pudo cargar el origen de la cifra."),
  review: async (id: number, decision: "approve" | "reject", comment?: string) => json<Report>(await post(`/financial-close/reports/${id}/review`, { decision, comment }), "No se pudo registrar la decisión."),
  demo: async () => json<Report>(await post("/financial-close/demo"), "No se pudo generar el cierre de ejemplo."),
  events: async () => json<AuditEvent[]>(await apiFetch("/financial-close/audit/events"), "No se pudo cargar el registro."),
};
