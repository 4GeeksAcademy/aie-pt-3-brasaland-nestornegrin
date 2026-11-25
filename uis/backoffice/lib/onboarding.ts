import { apiFetch, readApiError } from "./api-client";

// Orquestador de onboarding corporativo. La API nunca devuelve datos sensibles (documento, banco, salario): solo estados.
export type StageStatus = "pending" | "active" | "completed";
export interface StageView {
  number: number; key: string; title: string; status: StageStatus; exit_condition: string; approver: string;
  requires_human_approval: boolean; has_comprehension_check: boolean; deadline_at: string; completed_at: string | null;
  attempts: number; rejections: number; last_comment: string | null; overdue: boolean;
}
export interface BoardRow {
  id: string; name: string; position: string; department: string; site: string; manager_id: string; status: string;
  current_stage: number; current_stage_title: string; waiting_on: string | null; overdue: boolean; blocked: boolean; deadline_at: string;
  progress: { completed: number; total: number }; start_date: string; processing_error: string | null; stages: StageView[];
}
export interface QuizQuestion { id: string; question: string; options: string[] }
export interface PersonView extends BoardRow {
  manager: { id: string; name: string } | null; paperwork: Record<string, boolean>; remaining: string[];
  awaiting: { kind: "quiz" | "approval"; stage: number } | null; last_rejection_comment: string | null;
  presentation: { stage: number; title: string; sections: { id: string; title: string; body: string; source: string; ref: string }[] } | null;
  quiz: { attempt: number; passing_score: number; last_score: number | null; questions: QuizQuestion[];
          reinforce: { title: string; body: string; source: string }[] } | null;
}
export interface PendingApproval { id: string; name: string; position: string; department: string; site: string; overdue: boolean; deadline_at: string;
  stage: number; stage_title: string; exit_condition: string }
export interface Notice { id: number; kind: string; message: string; stage: number | null; created_at: string }
export interface Reply { answered: boolean; answer: string; sources: { ref: string; label: string }[]; derived_to: string | null }

async function json<T>(response: Response, fallback: string): Promise<T> {
  if (!response.ok) throw new Error(await readApiError(response, fallback));
  return (await response.json()) as T;
}
const post = (path: string, body?: unknown) =>
  apiFetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) });

/** Una etapa vencida es la que sigue activa y pasó su plazo: lo que el tablero marca en rojo. */
export function stageTone(stage: Pick<StageView, "status" | "overdue">): "done" | "late" | "active" | "todo" {
  if (stage.status === "completed") return "done";
  if (stage.overdue) return "late";
  return stage.status === "active" ? "active" : "todo";
}
export function rowLabel(row: Pick<BoardRow, "status" | "blocked" | "overdue">): string {
  if (row.status === "completed") return "Completado";
  if (row.blocked) return "Bloqueada (plazo vencido)";
  return row.overdue ? "Retrasada" : "En curso";
}
/** ¿Todas las preguntas tienen respuesta? Solo entonces se habilita el envío de la comprobación. */
export function canSubmit(questions: QuizQuestion[], answers: Record<string, number>): boolean {
  return questions.length > 0 && questions.every((q) => Number.isInteger(answers[q.id]));
}
export const onboardingApi = {
  board: async () => json<BoardRow[]>(await apiFetch("/onboarding"), "No se pudo cargar el tablero."),
  mine: async () => json<PersonView>(await apiFetch("/onboarding/me"), "No tienes un onboarding asignado."),
  approvals: async () => json<PendingApproval[]>(await apiFetch("/onboarding/approvals"), "No se pudieron cargar las aprobaciones."),
  notifications: async () => json<Notice[]>(await apiFetch("/onboarding/notifications"), "No se pudieron cargar los avisos."),
  sweep: async () => json<{ sent: unknown[] }>(await post("/onboarding/sweep"), "No se pudo ejecutar el seguimiento."),
  answers: async (id: string, answers: Record<string, number>) => json<{ accepted: boolean }>(await post(`/onboarding/${id}/answers`, { answers }), "No se pudo enviar la comprobación."),
  decide: async (id: string, body: { decision: "approve" | "reject"; comment?: string; contract_received?: boolean; payroll_docs_received?: boolean; accesses_confirmed?: boolean }) =>
    json<{ accepted: boolean }>(await post(`/onboarding/${id}/decision`, body), "No se pudo registrar la decisión."),
  ask: async (id: string, question: string) => json<Reply>(await post(`/onboarding/${id}/questions`, { question }), "No se pudo enviar la duda."),
};
