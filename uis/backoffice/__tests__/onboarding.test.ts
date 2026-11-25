import { canSubmit, onboardingApi, rowLabel, stageTone } from "../lib/onboarding";

describe("helpers del onboarding", () => {
  test("tono de cada etapa", () => {
    expect(stageTone({ status: "completed", overdue: false })).toBe("done");
    expect(stageTone({ status: "active", overdue: true })).toBe("late");
    expect(stageTone({ status: "active", overdue: false })).toBe("active");
    expect(stageTone({ status: "pending", overdue: false })).toBe("todo");
  });
  test("etiqueta de la fila: bloqueada, retrasada, en curso, completada", () => {
    expect(rowLabel({ status: "active", blocked: true, overdue: true })).toMatch(/Bloqueada/);
    expect(rowLabel({ status: "active", blocked: false, overdue: true })).toBe("Retrasada");
    expect(rowLabel({ status: "active", blocked: false, overdue: false })).toBe("En curso");
    expect(rowLabel({ status: "completed", blocked: false, overdue: false })).toBe("Completado");
  });
  test("la comprobación solo se envía con todas las preguntas respondidas", () => {
    const qs = [{ id: "a", question: "?", options: [] }, { id: "b", question: "?", options: [] }];
    expect(canSubmit(qs, { a: 0 })).toBe(false);
    expect(canSubmit(qs, { a: 0, b: 3 })).toBe(true);
    expect(canSubmit([], {})).toBe(false);
  });
});

describe("llamadas a la API", () => {
  beforeEach(() => window.localStorage.clear());
  test("decide envía JSON a /decision y propaga el error del servidor", async () => {
    const fetchMock = jest.fn(async () => ({ ok: false, status: 403, json: async () => ({ detail: "Solo puede decidir esta etapa: Responsable directo." }), text: async () => "" }));
    global.fetch = fetchMock as unknown as typeof fetch;
    await expect(onboardingApi.decide("ob-1", { decision: "approve" })).rejects.toThrow(/Responsable directo/);
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toMatch(/\/onboarding\/ob-1\/decision$/);
    expect(JSON.parse(init.body as string)).toEqual({ decision: "approve" });
  });
  test("ask devuelve la respuesta con fuentes", async () => {
    global.fetch = jest.fn(async () => ({ ok: true, status: 200, json: async () => ({ answered: false, answer: "x", sources: [], derived_to: "Personas (Ashley Turner)" }) })) as unknown as typeof fetch;
    await expect(onboardingApi.ask("ob-1", "¿vacaciones?")).resolves.toMatchObject({ answered: false, derived_to: "Personas (Ashley Turner)" });
  });
});
