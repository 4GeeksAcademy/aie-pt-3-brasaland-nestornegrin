import { apiFetch } from "@/lib/api-client";

/**
 * Cliente y utilidades del dashboard «Desempeño de Inventario por Restaurante».
 *
 * Consume `services/reporting/` (`GET /reporting/inventory-performance/kpis` y `/status`), que a su vez lee la tabla
 * de destino `reporting.restaurant_inventory_daily` del pipeline de `data/pipelines/`. Los nombres de los KPI (K1–K6)
 * son los de `data/pipelines/PIPELINE_DESIGN.md` §2.3. Este módulo no calcula KPIs nuevos: solo suma lo que ya viene
 * calculado y RECALCULA las tasas desde las sumas (nunca promedia porcentajes).
 */

export type Granularity = "day" | "week";
export type CaptureHealth = "ok" | "real_zero" | "suspected_capture_gap";

/** Una fila de `GET …/kpis` (un restaurante y un día local, o su agregado semanal). */
export type KpiItem = {
  report_date: string;
  restaurant: string;
  country: string;
  outbound_orders: number; // K1
  units_issued: number; // K2
  spoilage_units: number;
  spoilage_rate_pct: number | null; // K3
  stock_alerts_low: number; // K4
  stock_alerts_critical: number; // K4
  validation_failures: number;
  validation_rejection_rate_pct: number | null; // K5
  ingredients_at_risk_eod: number; // K6
  ingredients_critical_eod: number; // K6
  telemetry_coverage_pct: number | null;
  events_deduplicated: number;
  capture_health: CaptureHealth;
  revision: number;
};

export type KpisResponse = { items: KpiItem[]; generated_at: string };

/** Respuesta de `GET …/status`. */
export type PipelineStatus = {
  last_run: { status?: string; finished_at?: string | null } | null;
  last_success_at: string | null;
  watermark_lag: number;
  is_running: boolean;
  active_run_id: string | null;
  is_stale: boolean;
  capture_health: Record<string, number>;
};

export type KpiQuery = { days: number; granularity: Granularity; country: string | null };

const DAY_MS = 24 * 60 * 60 * 1000;
const BASE = "/reporting/inventory-performance";

function isoDate(date: Date): string {
  return date.toISOString().slice(0, 10);
}

/** Últimos `days` días hasta hoy (UTC), como pide el endpoint (`from`/`to` en YYYY-MM-DD). */
export function queryString({ days, granularity, country }: KpiQuery, today: Date = new Date()): string {
  const params = new URLSearchParams();
  params.set("from", isoDate(new Date(today.getTime() - (days - 1) * DAY_MS)));
  params.set("to", isoDate(today));
  params.set("granularity", granularity);
  if (country) params.set("country", country);
  return params.toString();
}

export function getInventoryKpis(query: KpiQuery): Promise<Response> {
  return apiFetch(`${BASE}/kpis?${queryString(query)}`);
}

export function getInventoryPipelineStatus(): Promise<Response> {
  return apiFetch(`${BASE}/status`);
}

// --------------------------------------------------------------------------- //
// Los seis KPI, con el nombre del diseño y una explicación para negocio
// --------------------------------------------------------------------------- //
export type KpiId = "K1" | "K2" | "K3" | "K4" | "K5" | "K6";

export type KpiDefinition = {
  id: KpiId;
  /** Nombre técnico del KPI en `PIPELINE_DESIGN.md` (columna de la tabla de destino). */
  name: string;
  /** Título para el lector de negocio. */
  title: string;
  /** La pregunta de negocio que responde. */
  question: string;
  /** Cómo se calcula, en una frase sin jerga. */
  how: string;
};

export const KPI_DEFINITIONS: KpiDefinition[] = [
  {
    id: "K1",
    name: "outbound_orders",
    title: "Órdenes de salida de insumos",
    question: "¿Cuántas veces sacó cada restaurante insumos del inventario?",
    how: "Número de órdenes de salida registradas en el período.",
  },
  {
    id: "K2",
    name: "units_issued",
    title: "Unidades de insumo entregadas",
    question: "¿Cuánto insumo salió del inventario en total?",
    how: "Suma de las cantidades de todas las órdenes de salida.",
  },
  {
    id: "K3",
    name: "spoilage_rate_pct",
    title: "Tasa de merma",
    question: "¿Qué parte de lo que sale del inventario se pierde como merma?",
    how: "Unidades registradas como merma ÷ unidades entregadas × 100.",
  },
  {
    id: "K4",
    name: "stock_alerts_low / stock_alerts_critical",
    title: "Alertas de stock bajo y crítico",
    question: "¿Qué restaurantes se están quedando sin insumos?",
    how: "Veces que un insumo cayó por debajo de 30 unidades (bajo) o de 10 (crítico).",
  },
  {
    id: "K5",
    name: "validation_rejection_rate_pct",
    title: "Tasa de rechazo en validaciones de inventario",
    question: "¿Con qué frecuencia el sistema rechaza una salida por no ser válida?",
    how: "Salidas rechazadas ÷ (salidas registradas + rechazadas) × 100.",
  },
  {
    id: "K6",
    name: "ingredients_at_risk_eod / ingredients_critical_eod",
    title: "Insumos en riesgo al cierre del día",
    question: "¿Con cuántos insumos en riesgo termina cada restaurante el último día del período?",
    how: "Insumos con stock de 30 unidades o menos al cierre (y cuántos de ellos de 10 o menos).",
  },
];

// --------------------------------------------------------------------------- //
// Agregación por restaurante (suma conteos, recalcula tasas)
// --------------------------------------------------------------------------- //
export type RestaurantSummary = {
  restaurant: string;
  country: string;
  outbound_orders: number;
  units_issued: number;
  spoilage_units: number;
  spoilage_rate_pct: number | null;
  stock_alerts_low: number;
  stock_alerts_critical: number;
  validation_failures: number;
  validation_rejection_rate_pct: number | null;
  ingredients_at_risk_eod: number;
  ingredients_critical_eod: number;
  capture_health: CaptureHealth;
};

const HEALTH_RANK: Record<CaptureHealth, number> = { ok: 0, real_zero: 1, suspected_capture_gap: 2 };

export function percent(numerator: number, denominator: number): number | null {
  if (!(denominator > 0)) return null; // 0 ÷ 0 no es «0 %»: es «sin datos»
  return Math.round((numerator / denominator) * 10000) / 100;
}

function round4(value: number): number {
  return Math.round(value * 10000) / 10000;
}

/** Una fila por restaurante: conteos sumados, tasas recalculadas, K6 del ÚLTIMO día del período y la peor salud de captura. */
export function summarizeByRestaurant(items: KpiItem[]): RestaurantSummary[] {
  const groups = new Map<string, KpiItem[]>();
  for (const item of items) groups.set(item.restaurant, [...(groups.get(item.restaurant) ?? []), item]);

  return [...groups.entries()]
    .map(([restaurant, rows]) => {
      const sum = (pick: (row: KpiItem) => number) => rows.reduce((total, row) => total + pick(row), 0);
      const last = [...rows].sort((a, b) => a.report_date.localeCompare(b.report_date)).at(-1) as KpiItem;
      const orders = sum((row) => row.outbound_orders);
      const units = round4(sum((row) => row.units_issued));
      const spoiled = round4(sum((row) => row.spoilage_units));
      const failures = sum((row) => row.validation_failures);
      const worst = rows.reduce<CaptureHealth>((acc, row) => (HEALTH_RANK[row.capture_health] > HEALTH_RANK[acc] ? row.capture_health : acc), "ok");
      return {
        restaurant,
        country: last.country,
        outbound_orders: orders,
        units_issued: units,
        spoilage_units: spoiled,
        spoilage_rate_pct: percent(spoiled, units),
        stock_alerts_low: sum((row) => row.stock_alerts_low),
        stock_alerts_critical: sum((row) => row.stock_alerts_critical),
        validation_failures: failures,
        validation_rejection_rate_pct: percent(failures, orders + failures),
        ingredients_at_risk_eod: last.ingredients_at_risk_eod,
        ingredients_critical_eod: last.ingredients_critical_eod,
        capture_health: worst,
      };
    })
    .sort((a, b) => a.restaurant.localeCompare(b.restaurant));
}

/** Totales de toda la cadena con la misma regla (sumar y recalcular). K6 suma el último día de cada restaurante. */
export function summarizeNetwork(summaries: RestaurantSummary[]): Omit<RestaurantSummary, "restaurant" | "country" | "capture_health"> {
  const sum = (pick: (row: RestaurantSummary) => number) => summaries.reduce((total, row) => total + pick(row), 0);
  const orders = sum((row) => row.outbound_orders);
  const units = round4(sum((row) => row.units_issued));
  const spoiled = round4(sum((row) => row.spoilage_units));
  const failures = sum((row) => row.validation_failures);
  return {
    outbound_orders: orders,
    units_issued: units,
    spoilage_units: spoiled,
    spoilage_rate_pct: percent(spoiled, units),
    stock_alerts_low: sum((row) => row.stock_alerts_low),
    stock_alerts_critical: sum((row) => row.stock_alerts_critical),
    validation_failures: failures,
    validation_rejection_rate_pct: percent(failures, orders + failures),
    ingredients_at_risk_eod: sum((row) => row.ingredients_at_risk_eod),
    ingredients_critical_eod: sum((row) => row.ingredients_critical_eod),
  };
}

// --------------------------------------------------------------------------- //
// Período cubierto, frescura y avisos de calidad de dato
// --------------------------------------------------------------------------- //
function addDays(date: string, days: number): string {
  return isoDate(new Date(new Date(`${date}T00:00:00Z`).getTime() + days * DAY_MS));
}

/** Período que cubren los datos mostrados. En la vista semanal, `report_date` es el lunes de cada semana. */
export function coveredPeriod(items: KpiItem[], granularity: Granularity): { from: string; to: string; label: string } | null {
  if (items.length === 0) return null;
  const dates = items.map((item) => item.report_date).sort();
  const from = dates[0];
  const to = granularity === "week" ? addDays(dates[dates.length - 1], 6) : dates[dates.length - 1];
  const unit = granularity === "week" ? "semanas completas (lunes a domingo)" : "días locales de cada restaurante";
  return { from, to, label: `Del ${from} al ${to} · ${unit}` };
}

export type Freshness = { tone: "ok" | "warning" | "unknown"; message: string };

/** Qué tan actualizados están los datos, en palabras de negocio (usa `is_stale`/`last_success_at` del endpoint de estado). */
export function dataFreshness(status: PipelineStatus | null): Freshness {
  if (!status) return { tone: "unknown", message: "No se pudo comprobar cuándo se actualizaron los datos por última vez." };
  if (!status.last_success_at) return { tone: "warning", message: "Todavía no se ha calculado ningún informe: los números pueden estar vacíos." };
  const updated = status.last_success_at.replace("T", " ").replace(/(\.\d+)?Z$/, " UTC");
  if (status.is_stale) return { tone: "warning", message: `Atención: los datos no se actualizan desde hace más de 26 horas (última actualización: ${updated}).` };
  return { tone: "ok", message: `Datos actualizados por última vez: ${updated}.` };
}

/** Restaurantes cuyo dato puede estar incompleto: hubo salidas reales que la telemetría no registró. */
export function captureGapRestaurants(summaries: RestaurantSummary[]): string[] {
  return summaries.filter((row) => row.capture_health === "suspected_capture_gap").map((row) => row.restaurant);
}

export function formatNumber(value: number): string {
  return new Intl.NumberFormat("es-CO", { maximumFractionDigits: 2 }).format(value);
}

export function formatPercent(value: number | null): string {
  return value === null ? "Sin datos" : `${new Intl.NumberFormat("es-CO", { maximumFractionDigits: 2 }).format(value)} %`;
}
