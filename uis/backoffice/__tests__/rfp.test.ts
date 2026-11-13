import { canRetryClosing, canStartApproval, decideApproval, generateResponse, generationAction, isLive, MAX_PDF_BYTES, progressLabel, reprocessTicket, startApproval, statusLabel, uploadRfp, validatePdf } from "../lib/rfp";

const pdf = (name: string, size = 10) => new File([new Uint8Array(size)], name, { type: "application/pdf" });

describe("validatePdf", () => {
  test("acepta un PDF y rechaza vacío, grande o de otro tipo", () => {
    expect(validatePdf(pdf("rfp.pdf"))).toBeNull();
    expect(validatePdf(null)).toMatch(/Selecciona/);
    expect(validatePdf(pdf("rfp.txt"))).toMatch(/PDF/);
    expect(validatePdf(new File([], "rfp.pdf"))).toMatch(/vacío/);
    expect(validatePdf({ name: "a.pdf", size: MAX_PDF_BYTES + 1 } as File)).toMatch(/10 MB/);
  });
});

describe("estado del ticket", () => {
  test("solo hace polling mientras el pipeline corre", () => {
    expect(isLive({ status: "analizando", processing: "running" })).toBe(true);
    expect(isLive({ status: "analizando", processing: "failed" })).toBe(false);
    expect(isLive({ status: "analizando", processing: "stalled" })).toBe(false);
    expect(isLive({ status: "descartado", processing: "idle" })).toBe(false);
  });
  test("etiquetas claras para cada caso", () => {
    expect(statusLabel({ status: "analisis_completo", processing: "idle" })).toBe("Análisis completo");
    expect(statusLabel({ status: "descartado", processing: "idle" })).toBe("Descartado");
    expect(statusLabel({ status: "analizando", processing: "failed" })).toMatch(/Falló/);
    expect(statusLabel({ status: "analizando", processing: "stalled" })).toMatch(/Detenido/);
  });
});

describe("llamadas a la API", () => {
  beforeEach(() => window.localStorage.clear());
  test("uploadRfp envía multipart sin Content-Type manual y devuelve el ticket", async () => {
    const fetchMock = jest.fn(async () => ({ ok: true, status: 202, json: async () => ({ ticket_id: 7, status: "analizando" }) }));
    global.fetch = fetchMock as unknown as typeof fetch;
    await expect(uploadRfp(pdf("rfp.pdf"))).resolves.toEqual({ ticket_id: 7, status: "analizando" });
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toMatch(/\/rfp\/tickets$/);
    expect(init.body).toBeInstanceOf(FormData);
    expect(new Headers(init.headers).has("Content-Type")).toBe(false);
  });
  test("propaga el mensaje de error del backend", async () => {
    global.fetch = jest.fn(async () => ({ ok: false, status: 415, json: async () => ({ detail: "El archivo no es un PDF válido." }) })) as unknown as typeof fetch;
    await expect(uploadRfp(pdf("x.pdf"))).rejects.toThrow("El archivo no es un PDF válido.");
  });
  test("reprocessTicket usa ?force=true solo cuando se pide", async () => {
    const fetchMock = jest.fn(async () => ({ ok: true, status: 202, json: async () => ({}) }));
    global.fetch = fetchMock as unknown as typeof fetch;
    await reprocessTicket(3); await reprocessTicket(3, true);
    expect((fetchMock.mock.calls[0] as unknown as [string])[0]).toMatch(/\/rfp\/tickets\/3\/reprocess$/);
    expect((fetchMock.mock.calls[1] as unknown as [string])[0]).toMatch(/reprocess\?force=true$/);
  });
});

describe("Parte 2 — generación de respuestas", () => {
  test("hace polling también mientras se generan y evalúan los borradores", () => {
    expect(isLive({ status: "generando_borrador", processing: "running" })).toBe(true);
    expect(isLive({ status: "en_evaluación", processing: "running" })).toBe(true);
    expect(isLive({ status: "en_evaluación", processing: "idle" })).toBe(false);
    expect(isLive({ status: "needs_human_review", processing: "idle" })).toBe(false);
  });
  test("etiquetas de los estados de la Parte 2", () => {
    expect(statusLabel({ status: "generando_borrador", processing: "running" })).toMatch(/Generando/);
    expect(statusLabel({ status: "en_evaluación", processing: "running" })).toMatch(/Evaluando/);
    expect(statusLabel({ status: "en_evaluación", processing: "idle" })).toBe("Respuesta evaluada");
    expect(statusLabel({ status: "needs_human_review", processing: "idle" })).toMatch(/revisión humana/);
    expect(statusLabel({ status: "generando_borrador", processing: "failed" })).toMatch(/Falló/);
  });
  test("avance y acción disponible", () => {
    expect(progressLabel({ total: 4, passed: 3, needs_review: 1, working: 0, errors: 0 })).toBe("3/4 aprobadas · 1 por revisar");
    expect(progressLabel(null)).toBeNull();
    expect(generationAction({ status: "analisis_completo", processing: "idle" })).toEqual({ label: "Generar respuesta", regenerate: false });
    expect(generationAction({ status: "en_evaluación", processing: "stalled" })?.regenerate).toBe(false);
    expect(generationAction({ status: "needs_human_review", processing: "idle" })?.regenerate).toBe(true);
    expect(generationAction({ status: "generando_borrador", processing: "running" })).toBeNull();
    expect(generationAction({ status: "descartado", processing: "idle" })).toBeNull();
  });
  test("generateResponse usa ?regenerate=true solo cuando se pide", async () => {
    const fetchMock = jest.fn(async () => ({ ok: true, status: 202, json: async () => ({}) }));
    global.fetch = fetchMock as unknown as typeof fetch;
    await generateResponse(5); await generateResponse(5, true);
    expect((fetchMock.mock.calls[0] as unknown as [string])[0]).toMatch(/\/rfp\/tickets\/5\/generate$/);
    expect((fetchMock.mock.calls[1] as unknown as [string])[0]).toMatch(/generate\?regenerate=true$/);
  });
});

describe("Parte 3 — aprobación humana", () => {
  test("polling mientras una decisión se procesa, no mientras se espera al humano", () => {
    expect(isLive({ status: "esperando_aprobación", processing: "running" })).toBe(true);
    expect(isLive({ status: "esperando_aprobación", processing: "idle" })).toBe(false);
    expect(isLive({ status: "terminado", processing: "idle" })).toBe(false);
  });
  test("etiquetas y avance de la Parte 3", () => {
    expect(statusLabel({ status: "esperando_aprobación", processing: "idle" })).toBe("Esperando aprobación");
    expect(statusLabel({ status: "esperando_aprobación", processing: "running" })).toMatch(/Procesando/);
    expect(statusLabel({ status: "esperando_aprobación", processing: "failed" })).toMatch(/cierre/);
    expect(statusLabel({ status: "terminado", processing: "idle" })).toBe("Terminado");
    expect(progressLabel({ total: 4, passed: 4, needs_review: 0, working: 0, errors: 0, approved: 2, awaiting: 2 }, "esperando_aprobación")).toBe("2/4 secciones aprobadas");
  });
  test("qué botones corresponden a cada estado", () => {
    expect(canStartApproval({ status: "en_evaluación", processing: "idle" })).toBe(true);
    expect(canStartApproval({ status: "needs_human_review", processing: "idle" })).toBe(true);
    expect(canStartApproval({ status: "esperando_aprobación", processing: "idle" })).toBe(false);
    expect(canRetryClosing({ status: "esperando_aprobación", processing: "failed" })).toBe(true);
    expect(canRetryClosing({ status: "terminado", processing: "idle" })).toBe(false);
    expect(generationAction({ status: "esperando_aprobación", processing: "idle" })).toBeNull();  // la Parte 2 queda cerrada
  });
  test("decideApproval reanuda la rama del departamento con JSON y propaga el error de validación", async () => {
    const fetchMock = jest.fn(async () => ({ ok: true, status: 202, json: async () => ({}) }));
    global.fetch = fetchMock as unknown as typeof fetch;
    await decideApproval(4, "operaciones", { action: "request_changes", approver: "Felipe Guerrero", comment: "Ajusta el plazo de montaje." });
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toMatch(/\/rfp\/tickets\/4\/approvals\/operaciones$/);
    expect(JSON.parse(init.body as string)).toMatchObject({ action: "request_changes", approver: "Felipe Guerrero" });
    global.fetch = jest.fn(async () => ({ ok: false, status: 422, json: async () => ({ detail: "Solo Felipe Guerrero puede decidir." }) })) as unknown as typeof fetch;
    await expect(decideApproval(4, "operaciones", { action: "approve", approver: "x" })).rejects.toThrow("Solo Felipe Guerrero");
  });
  test("startApproval llama al endpoint de apertura", async () => {
    const fetchMock = jest.fn(async () => ({ ok: true, status: 202, json: async () => ({}) }));
    global.fetch = fetchMock as unknown as typeof fetch;
    await startApproval(9);
    expect((fetchMock.mock.calls[0] as unknown as [string])[0]).toMatch(/\/rfp\/tickets\/9\/approval\/start$/);
  });
});
