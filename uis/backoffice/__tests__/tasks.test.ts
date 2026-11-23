import { waitForTask } from "../lib/tasks";

jest.mock("@/lib/api-client", () => ({
  apiFetch: jest.fn(),
  readApiError: jest.fn(async (_response: Response, fallback: string) => fallback),
}));

import { apiFetch } from "@/lib/api-client";

const mockedFetch = apiFetch as jest.Mock;

function taskResponse(status: string, result: unknown = null, ok = true): Response {
  return { ok, json: async () => ({ task_id: "t-1", status, result }) } as Response;
}

beforeEach(() => mockedFetch.mockReset());

describe("waitForTask", () => {
  test("camino feliz: consulta hasta que la tarea termina y devuelve el resultado", async () => {
    mockedFetch
      .mockResolvedValueOnce(taskResponse("pending"))
      .mockResolvedValueOnce(taskResponse("started"))
      .mockResolvedValueOnce(taskResponse("success", { total_processed: 3 }));
    const seen: string[] = [];

    const result = await waitForTask<{ total_processed: number }>("t-1", { intervalMs: 1, onStatus: (s) => seen.push(s) });

    expect(result).toEqual({ total_processed: 3 });
    expect(seen).toEqual(["pending", "started", "success"]);
    expect(mockedFetch).toHaveBeenCalledWith("/tasks/t-1");
  });

  test("modo de fallo: si la tarea falla, lanza el error que registró el worker", async () => {
    mockedFetch.mockResolvedValueOnce(taskResponse("failure", { error: "ValueError: cabecera inválida" }));
    await expect(waitForTask("t-1", { intervalMs: 1 })).rejects.toThrow("ValueError: cabecera inválida");
  });

  test("modo de fallo: si la API responde con error al consultar, lanza un mensaje legible", async () => {
    mockedFetch.mockResolvedValueOnce(taskResponse("pending", null, false));
    await expect(waitForTask("t-1", { intervalMs: 1 })).rejects.toThrow("No se pudo consultar el estado de la tarea");
  });

  test("caso límite: si la tarea no termina dentro del tiempo máximo, deja de esperar", async () => {
    mockedFetch.mockResolvedValue(taskResponse("started"));
    await expect(waitForTask("t-1", { intervalMs: 1, timeoutMs: 20 })).rejects.toThrow("tardando más de lo esperado");
  });

  test("caso límite: se puede cancelar la espera", async () => {
    mockedFetch.mockResolvedValue(taskResponse("started"));
    const controller = new AbortController();
    setTimeout(() => controller.abort(), 10);
    await expect(waitForTask("t-1", { intervalMs: 5, signal: controller.signal })).rejects.toThrow("cancelada");
  });
});
