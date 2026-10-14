/** @jest-environment node */
import { renderToStaticMarkup } from "react-dom/server";
import { InventoryPerformanceReport } from "@/components/inventory-performance-report";
import {
  KPI_DEFINITIONS,
  captureGapRestaurants,
  coveredPeriod,
  dataFreshness,
  percent,
  queryString,
  summarizeByRestaurant,
  summarizeNetwork,
  type KpiItem,
  type PipelineStatus,
} from "@/lib/inventory-performance";

const POBLADO = "Brasaland El Poblado";
const BRICKELL = "Brasaland Brickell";

function item(overrides: Partial<KpiItem>): KpiItem {
  return {
    report_date: "2026-10-05", restaurant: POBLADO, country: "Colombia", outbound_orders: 0, units_issued: 0, spoilage_units: 0,
    spoilage_rate_pct: null, stock_alerts_low: 0, stock_alerts_critical: 0, validation_failures: 0, validation_rejection_rate_pct: null,
    ingredients_at_risk_eod: 0, ingredients_critical_eod: 0, telemetry_coverage_pct: null, events_deduplicated: 0, capture_health: "ok", revision: 1,
    ...overrides,
  };
}

const FRESH: PipelineStatus = {
  last_run: { status: "completed" }, last_success_at: "2026-10-14T10:00:05Z", watermark_lag: 0, is_running: false, active_run_id: null, is_stale: false, capture_health: {},
};

describe("agregación por restaurante", () => {
  it("suma los conteos y RECALCULA las tasas desde las sumas (no promedia porcentajes)", () => {
    const rows = [
      item({ report_date: "2026-10-05", outbound_orders: 1, units_issued: 10, spoilage_units: 3, spoilage_rate_pct: 30, validation_failures: 1, validation_rejection_rate_pct: 50 }),
      item({ report_date: "2026-10-06", outbound_orders: 9, units_issued: 90, spoilage_units: 0, spoilage_rate_pct: 0, validation_failures: 0, validation_rejection_rate_pct: 0 }),
    ];
    const [summary] = summarizeByRestaurant(rows);
    expect(summary.outbound_orders).toBe(10);
    expect(summary.units_issued).toBe(100);
    expect(summary.spoilage_rate_pct).toBe(3); // 3 ÷ 100, no (30 + 0) ÷ 2 = 15
    expect(summary.validation_rejection_rate_pct).toBe(9.09); // 1 ÷ (10 + 1)
  });

  it("K6 toma el cierre del ÚLTIMO día del período, no la suma de todos los días", () => {
    const rows = [
      item({ report_date: "2026-10-06", ingredients_at_risk_eod: 2, ingredients_critical_eod: 1 }),
      item({ report_date: "2026-10-05", ingredients_at_risk_eod: 7, ingredients_critical_eod: 4 }),
    ];
    const [summary] = summarizeByRestaurant(rows);
    expect([summary.ingredients_at_risk_eod, summary.ingredients_critical_eod]).toEqual([2, 1]);
  });

  it("una tasa sin denominador es «sin datos» (null), no un 0 %", () => {
    expect(percent(0, 0)).toBeNull();
    expect(percent(3, 10)).toBe(30);
    expect(summarizeByRestaurant([item({})])[0].spoilage_rate_pct).toBeNull();
  });

  it("totaliza la cadena con la misma regla y detecta los restaurantes con hueco de captura", () => {
    const summaries = summarizeByRestaurant([
      item({ outbound_orders: 3, units_issued: 10, spoilage_units: 3, stock_alerts_low: 1, stock_alerts_critical: 2 }),
      item({ restaurant: BRICKELL, country: "Estados Unidos", outbound_orders: 1, units_issued: 10, capture_health: "suspected_capture_gap" }),
    ]);
    const network = summarizeNetwork(summaries);
    expect(network.outbound_orders).toBe(4);
    expect(network.spoilage_rate_pct).toBe(15); // 3 ÷ 20
    expect([network.stock_alerts_low, network.stock_alerts_critical]).toEqual([1, 2]);
    expect(captureGapRestaurants(summaries)).toEqual([BRICKELL]);
  });
});

describe("consulta y período", () => {
  it("pide al endpoint los últimos N días con vista y país", () => {
    const query = new URLSearchParams(queryString({ days: 7, granularity: "week", country: "Colombia" }, new Date("2026-10-14T12:00:00Z")));
    expect(query.get("from")).toBe("2026-10-08");
    expect(query.get("to")).toBe("2026-10-14");
    expect(query.get("granularity")).toBe("week");
    expect(query.get("country")).toBe("Colombia");
    expect(new URLSearchParams(queryString({ days: 7, granularity: "day", country: null })).has("country")).toBe(false);
  });

  it("el período semanal termina el domingo de la última semana", () => {
    expect(coveredPeriod([item({ report_date: "2026-10-05" })], "week")?.to).toBe("2026-10-11");
    expect(coveredPeriod([item({ report_date: "2026-10-05" })], "day")?.to).toBe("2026-10-05");
    expect(coveredPeriod([], "day")).toBeNull();
  });

  it("avisa en lenguaje de negocio cuando los datos no se actualizan", () => {
    expect(dataFreshness(FRESH).tone).toBe("ok");
    expect(dataFreshness({ ...FRESH, is_stale: true })).toMatchObject({ tone: "warning", message: expect.stringContaining("26 horas") });
    expect(dataFreshness({ ...FRESH, last_success_at: null }).tone).toBe("warning");
    expect(dataFreshness(null).tone).toBe("unknown");
  });
});

describe("dashboard de negocio", () => {
  const rows = [
    item({ outbound_orders: 3, units_issued: 10, spoilage_units: 3, spoilage_rate_pct: 30, stock_alerts_low: 1, stock_alerts_critical: 2, validation_failures: 1, validation_rejection_rate_pct: 25, ingredients_at_risk_eod: 2, ingredients_critical_eod: 1 }),
  ];

  it("muestra un bloque por cada KPI del diseño, con su nombre y la pregunta de negocio", () => {
    const html = renderToStaticMarkup(<InventoryPerformanceReport items={rows} granularity="day" status={FRESH} />);
    for (const kpi of KPI_DEFINITIONS) {
      expect(html).toContain(`data-testid="kpi-${kpi.id}"`);
      expect(html).toContain(`${kpi.id} · ${kpi.title}`);
      expect(html).toContain(kpi.question);
      expect(html).toContain(kpi.name);
    }
    expect(KPI_DEFINITIONS.map((kpi) => kpi.id)).toEqual(["K1", "K2", "K3", "K4", "K5", "K6"]);
  });

  it("muestra el período que cubren los datos, los valores por restaurante y la frescura", () => {
    const html = renderToStaticMarkup(<InventoryPerformanceReport items={rows} granularity="day" status={FRESH} />);
    expect(html).toContain("Período que cubren los datos:");
    expect(html).toContain("Del 2026-10-05 al 2026-10-05");
    expect(html).toContain(POBLADO);
    expect(html).toContain("30 %"); // K3
    expect(html).toContain("25 %"); // K5
    expect(html).toContain("Datos actualizados por última vez");
  });

  it("sin datos, lo dice con claridad en lugar de mostrar gráficos vacíos", () => {
    const html = renderToStaticMarkup(<InventoryPerformanceReport items={[]} granularity="day" status={FRESH} />);
    expect(html).toContain("No hay datos para este período");
    expect(html).not.toContain('data-testid="kpi-K1"');
  });

  it("advierte cuando un restaurante puede tener cifras incompletas", () => {
    const html = renderToStaticMarkup(
      <InventoryPerformanceReport items={[item({ outbound_orders: 1, capture_health: "suspected_capture_gap" })]} granularity="day" status={{ ...FRESH, is_stale: true }} />,
    );
    expect(html).toContain("Posible dato incompleto");
    expect(html).toContain("no se actualizan desde hace más de 26 horas");
  });
});
