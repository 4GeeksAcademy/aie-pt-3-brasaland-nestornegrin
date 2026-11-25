import { ACTOR_LABELS, STATUS_LABELS, canReview, figureWarning, rejectionError, sortReports, sourceLabel } from "../lib/financial-close";

describe("helpers del cierre financiero", () => {
  test("solo un informe pendiente se puede revisar", () => {
    expect(canReview({ status: "pending_review" })).toBe(true);
    for (const status of ["rejected", "approved", "distributed"] as const) expect(canReview({ status })).toBe(false);
  });
  test("un rechazo exige comentarios", () => {
    expect(rejectionError("   ")).toMatch(/rechazar/);
    expect(rejectionError("Detalla Marketing de Florida")).toBe("");
  });
  test("una cifra parcial o sin datos se avisa, una completa no", () => {
    expect(figureWarning("partial")).toMatch(/parcial/);
    expect(figureWarning("missing")).toMatch(/Sin datos/);
    expect(figureWarning("ok")).toBe("");
  });
  test("el origen se muestra con el entry_id o, si no hay, con archivo y fila", () => {
    expect(sourceLabel({ file: "ledger.csv", row: 3, entry_id: "L-FL-2026-10-0001" })).toBe("L-FL-2026-10-0001");
    expect(sourceLabel({ file: "budget.csv", row: 4, entry_id: null })).toBe("budget.csv:4");
  });
  test("los informes se ordenan por periodo reciente y versión nueva primero", () => {
    const rows = [{ period: "2026-09", version: 1 }, { period: "2026-10", version: 1 }, { period: "2026-10", version: 2 }];
    expect(sortReports(rows).map((r) => `${r.period}v${r.version}`)).toEqual(["2026-10v2", "2026-10v1", "2026-09v1"]);
  });
  test("las etiquetas cubren todos los estados y distinguen proceso automatizado de persona", () => {
    expect(Object.keys(STATUS_LABELS).sort()).toEqual(["approved", "distributed", "pending_review", "rejected"]);
    expect(ACTOR_LABELS.automated_process).toMatch(/automatizado/);
  });
});
