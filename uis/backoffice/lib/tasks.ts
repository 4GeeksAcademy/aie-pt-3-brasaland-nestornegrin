// Cliente de la cola de tareas asíncronas (DEV-55): las operaciones pesadas ya no responden con su resultado,
// responden 202 con un `task_id`; el resultado se consulta en GET /tasks/{task_id} hasta que termina.
import { apiFetch, readApiError } from "@/lib/api-client";

export type TaskStatus = "pending" | "started" | "success" | "failure";

type TaskResponse<T> = {
  task_id: string;
  status: TaskStatus;
  result: T | { error: string } | null;
};

type WaitOptions = {
  /** Se llama en cada consulta con el estado actual (para pintar «En cola…» / «Analizando…»). */
  onStatus?: (status: TaskStatus) => void;
  /** Cancela la espera (p. ej. al desmontar el componente). */
  signal?: AbortSignal;
  intervalMs?: number;
  timeoutMs?: number;
};

export const TASK_POLL_INTERVAL_MS = 1000;
// Una tarea con fallos tarda en rendirse: 3 reintentos con backoff exponencial. 2 minutos de margen.
export const TASK_TIMEOUT_MS = 120_000;

function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    const timer = setTimeout(resolve, ms);
    signal?.addEventListener("abort", () => { clearTimeout(timer); resolve(); }, { once: true });
  });
}

/**
 * Espera a que termine la tarea y devuelve su resultado. Lanza `Error` con el mensaje del worker si la tarea
 * falla (tras sus reintentos), o si la API no responde / se agota el tiempo de espera.
 */
export async function waitForTask<T>(taskId: string, options: WaitOptions = {}): Promise<T> {
  const { onStatus, signal, intervalMs = TASK_POLL_INTERVAL_MS, timeoutMs = TASK_TIMEOUT_MS } = options;
  const deadline = Date.now() + timeoutMs;
  while (!signal?.aborted) {
    const response = await apiFetch(`/tasks/${encodeURIComponent(taskId)}`);
    if (!response.ok) throw new Error(await readApiError(response, "No se pudo consultar el estado de la tarea"));
    const task = (await response.json()) as TaskResponse<T>;
    onStatus?.(task.status);
    if (task.status === "success") return task.result as T;
    if (task.status === "failure") {
      const detail = (task.result as { error?: string } | null)?.error;
      throw new Error(detail ?? "La tarea ha fallado");
    }
    if (Date.now() >= deadline) throw new Error("La tarea está tardando más de lo esperado. Inténtalo de nuevo en unos minutos.");
    await sleep(intervalMs, signal);
  }
  throw new Error("Consulta cancelada");
}
