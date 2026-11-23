import { apiFetch, readApiError } from "./api-client";

// Hito 9 · Partes 1 y 2 — recepción de RFPs y generación de respuestas. Los estados de la Parte 3 no existen aquí.
export type TicketStatus = "analizando" | "descartado" | "analisis_completo" | "generando_borrador" | "en_evaluación" | "needs_human_review";
export type SectionStatus = "pendiente" | "generando" | "en_evaluacion" | "paso" | "needs_human_review" | "error";
// «processing» lo deriva el backend del latido del pipeline: running | failed | stalled | idle.
export type Processing = "running" | "failed" | "stalled" | "idle";

export interface KeyAspect { aspect: string; detail: string; source_excerpt?: string; unverified_numbers?: string[]; inferred?: boolean }
export interface Violation { rule_id: string; message: string; excerpt?: string; briefing_ref?: string }
export interface EvaluationResult {
  section_id?: string; department_id?: string; overall_pass: boolean; feedback_for_generator: string;
  readability: { pass: boolean; score: number | null; details: Record<string, unknown> };
  relevance: { pass: boolean; missing_aspects: string[] };
  compliance: { pass: boolean; rule_ids: string[]; violations: Violation[] };
  iteration?: number;
}
export interface RfpSection {
  department_id: string; department: string; owner: string; reason: string | null;
  key_aspects: KeyAspect[]; asks: string[]; figures: Record<string, string>; open_questions: string[]; excerpts: string[];
  // Parte 2
  generation_status?: SectionStatus | null; iterations?: number | null; needs_human_review?: boolean | null;
  draft_content?: string | null; pending_items?: string[] | null; evaluation_results?: EvaluationResult | null;
  evaluation_history?: EvaluationResult[] | null; generation_error?: string | null;
}
export interface Progress { total: number; passed: number; needs_review: number; working: number; errors: number }
export interface TicketSummary {
  ticket_id: number; rfp_id: string | null; status: TicketStatus; processing: Processing; original_filename: string;
  client_name: string | null; current_node: string | null; progress?: Progress | null; created_at: string; updated_at: string;
}
export interface TicketDetail extends TicketSummary {
  discard_reason: string | null; processing_error: string | null; attempts: number;
  classification: { document_type?: string; confidence?: number; reasons?: string[]; forced_by_user?: boolean } | null;
  metadata: Record<string, unknown> | null; readability: Record<string, unknown> | null;
  sections: RfpSection[]; summary: { headline?: string; by_department?: Record<string, string> } | null;
  response_completed_at?: string | null;
  part3_handoff?: { all_sections_passed?: boolean; needs_human_review?: string[] } | null;
  handoff: { open_questions?: string[]; conflicts?: unknown[]; approvals?: { ceo?: { required: boolean | null; threshold_usd: number; approver: string } } } | null;
}

export const MAX_PDF_BYTES = 10 * 1024 * 1024;

const WORKING = ["analizando", "generando_borrador", "en_evaluación"];

/** Un ticket sigue «en vivo» mientras algún pipeline corre: solo entonces tiene sentido hacer polling. */
export function isLive(ticket: Pick<TicketSummary, "status" | "processing">): boolean {
  return WORKING.includes(ticket.status) && ticket.processing === "running";
}

export function statusLabel(ticket: Pick<TicketSummary, "status" | "processing" | "progress">): string {
  if (ticket.status === "descartado") return "Descartado";
  if (ticket.status === "analisis_completo") return "Análisis completo";
  if (ticket.status === "needs_human_review") return "Requiere revisión humana";
  if (ticket.processing === "failed") return "Falló — reintentar";
  if (ticket.processing === "stalled") return "Detenido — reintentar";
  if (ticket.status === "generando_borrador") return "Generando borradores…";
  if (ticket.status === "en_evaluación") return ticket.processing === "running" ? "Evaluando borradores…" : "Respuesta evaluada";
  return "Analizando…";
}

/** «3/4 aprobadas» para el avance de la Parte 2 (o null si aún no aplica). */
export function progressLabel(progress: Progress | null | undefined): string | null {
  if (!progress || progress.total === 0) return null;
  const extra = progress.needs_review ? ` · ${progress.needs_review} por revisar` : "";
  return `${progress.passed}/${progress.total} aprobadas${extra}`;
}

/** Acción de la Parte 2 disponible según el estado. */
export function generationAction(t: Pick<TicketSummary, "status" | "processing">): { label: string; regenerate: boolean } | null {
  if (t.status === "analisis_completo") return { label: "Generar respuesta", regenerate: false };
  if (["generando_borrador", "en_evaluación"].includes(t.status) && (t.processing === "failed" || t.processing === "stalled")) return { label: "Reintentar generación", regenerate: false };
  if (t.status === "needs_human_review" || (t.status === "en_evaluación" && t.processing === "idle")) return { label: "Regenerar borradores", regenerate: true };
  return null;
}

export function validatePdf(file: File | null | undefined): string | null {
  if (!file) return "Selecciona un archivo PDF.";
  if (!file.name.toLowerCase().endsWith(".pdf")) return "El archivo debe ser un PDF.";
  if (file.size === 0) return "El archivo está vacío.";
  if (file.size > MAX_PDF_BYTES) return "El PDF supera el máximo de 10 MB.";
  return null;
}

async function json<T>(response: Response, fallback: string): Promise<T> {
  if (!response.ok) throw new Error(await readApiError(response, fallback));
  return (await response.json()) as T;
}

export async function uploadRfp(file: File): Promise<{ ticket_id: number; status: TicketStatus }> {
  const form = new FormData();
  form.append("file", file); // sin Content-Type manual: el navegador añade el boundary
  return json(await apiFetch("/rfp/tickets", { method: "POST", body: form }), "No se pudo subir el PDF.");
}
export async function listTickets(): Promise<TicketSummary[]> {
  return json(await apiFetch("/rfp/tickets"), "No se pudieron cargar los tickets.");
}
export async function getTicket(id: number): Promise<TicketDetail> {
  return json(await apiFetch(`/rfp/tickets/${id}`), "No se pudo cargar el ticket.");
}
export async function reprocessTicket(id: number, force = false): Promise<void> {
  await json(await apiFetch(`/rfp/tickets/${id}/reprocess${force ? "?force=true" : ""}`, { method: "POST" }), "No se pudo reprocesar el ticket.");
}
export async function generateResponse(id: number, regenerate = false): Promise<void> {
  await json(await apiFetch(`/rfp/tickets/${id}/generate${regenerate ? "?regenerate=true" : ""}`, { method: "POST" }), "No se pudo iniciar la generación.");
}
