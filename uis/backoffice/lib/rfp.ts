import { apiFetch, readApiError } from "./api-client";

// Hito 9 · Parte 1 — recepción de RFPs. Estados del ticket en esta parte.
export type TicketStatus = "analizando" | "descartado" | "analisis_completo";
// «processing» lo deriva el backend del latido del pipeline: running | failed | stalled | idle.
export type Processing = "running" | "failed" | "stalled" | "idle";

export interface KeyAspect { aspect: string; detail: string; source_excerpt?: string; unverified_numbers?: string[] }
export interface RfpSection {
  department_id: string; department: string; owner: string; reason: string | null;
  key_aspects: KeyAspect[]; asks: string[]; figures: Record<string, string>; open_questions: string[]; excerpts: string[];
}
export interface TicketSummary {
  ticket_id: number; rfp_id: string | null; status: TicketStatus; processing: Processing; original_filename: string;
  client_name: string | null; current_node: string | null; created_at: string; updated_at: string;
}
export interface TicketDetail extends TicketSummary {
  discard_reason: string | null; processing_error: string | null; attempts: number;
  classification: { document_type?: string; confidence?: number; reasons?: string[]; forced_by_user?: boolean } | null;
  metadata: Record<string, unknown> | null; readability: Record<string, unknown> | null;
  sections: RfpSection[]; summary: { headline?: string; by_department?: Record<string, string> } | null;
  handoff: { open_questions?: string[]; conflicts?: unknown[]; approvals?: { ceo?: { required: boolean | null; threshold_usd: number; approver: string } } } | null;
}

export const MAX_PDF_BYTES = 10 * 1024 * 1024;

/** Un ticket sigue «en vivo» mientras el pipeline corre: solo entonces tiene sentido hacer polling. */
export function isLive(ticket: Pick<TicketSummary, "status" | "processing">): boolean {
  return ticket.status === "analizando" && ticket.processing === "running";
}

export function statusLabel(ticket: Pick<TicketSummary, "status" | "processing">): string {
  if (ticket.status === "analisis_completo") return "Análisis completo";
  if (ticket.status === "descartado") return "Descartado";
  if (ticket.processing === "failed") return "Falló — reprocesar";
  if (ticket.processing === "stalled") return "Detenido — reprocesar";
  return "Analizando…";
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
