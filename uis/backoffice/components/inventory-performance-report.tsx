import {
  KPI_DEFINITIONS,
  captureGapRestaurants,
  coveredPeriod,
  dataFreshness,
  formatNumber,
  formatPercent,
  summarizeByRestaurant,
  summarizeNetwork,
  type Granularity,
  type KpiDefinition,
  type KpiItem,
  type PipelineStatus,
  type RestaurantSummary,
} from "@/lib/inventory-performance";

/**
 * Vista (sin estado ni red) del dashboard «Desempeño de Inventario por Restaurante».
 * Recibe las filas que devuelve `GET /reporting/inventory-performance/kpis` y las presenta, un bloque por KPI,
 * para Operaciones y la dirección (CEO / CTO). Está separada del contenedor para poder probarla sin navegador.
 */

function Bar({ value, max, tone = "bg-red-800" }: { value: number; max: number; tone?: string }) {
  const width = max > 0 && value > 0 ? Math.max(2, Math.round((value / max) * 100)) : 0;
  return (
    <div className="h-3 w-full rounded bg-zinc-100" aria-hidden="true">
      <div className={`h-3 rounded ${tone}`} style={{ width: `${width}%` }} />
    </div>
  );
}

function KpiSection({ definition, summary, children }: { definition: KpiDefinition; summary: string; children: React.ReactNode }) {
  return (
    <section className="rounded-xl border border-zinc-200 bg-white p-4 sm:p-6" aria-labelledby={`kpi-${definition.id}`} data-testid={`kpi-${definition.id}`}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id={`kpi-${definition.id}`} className="text-base font-black text-zinc-900">
          {definition.id} · {definition.title}
        </h2>
        <p className="text-sm font-bold text-red-800" data-testid={`kpi-${definition.id}-network`}>Toda la cadena: {summary}</p>
      </div>
      <p className="mt-1 text-sm text-zinc-700">{definition.question}</p>
      <p className="mt-1 text-xs text-zinc-500">
        {definition.how} <span className="font-mono">({definition.name})</span>
      </p>
      <ul className="mt-4 space-y-2">{children}</ul>
    </section>
  );
}

function Row({ name, bar, value }: { name: string; bar: React.ReactNode; value: string }) {
  return (
    <li className="grid grid-cols-[10rem_1fr_9rem] items-center gap-3 text-sm sm:grid-cols-[14rem_1fr_11rem]">
      <span className="truncate text-zinc-700" title={name}>{name}</span>
      {bar}
      <span className="text-right font-bold text-zinc-900">{value}</span>
    </li>
  );
}

function ranked(summaries: RestaurantSummary[], pick: (row: RestaurantSummary) => number | null): RestaurantSummary[] {
  return [...summaries].sort((a, b) => (pick(b) ?? -1) - (pick(a) ?? -1) || a.restaurant.localeCompare(b.restaurant));
}

export function InventoryPerformanceReport({
  items,
  granularity,
  status,
}: {
  items: KpiItem[];
  granularity: Granularity;
  status: PipelineStatus | null;
}) {
  const summaries = summarizeByRestaurant(items);
  const network = summarizeNetwork(summaries);
  const period = coveredPeriod(items, granularity);
  const freshness = dataFreshness(status);
  const gaps = captureGapRestaurants(summaries);
  const max = (pick: (row: RestaurantSummary) => number | null) => Math.max(0, ...summaries.map((row) => pick(row) ?? 0));
  const [k1, k2, k3, k4, k5, k6] = KPI_DEFINITIONS;

  const freshnessTone =
    freshness.tone === "ok" ? "border-emerald-200 bg-emerald-50 text-emerald-900" : "border-amber-300 bg-amber-50 text-amber-900";

  return (
    <div className="space-y-6">
      <p className={`rounded-lg border px-4 py-3 text-sm ${freshnessTone}`} role="status" data-testid="data-freshness">
        {freshness.message}
      </p>

      {period ? (
        <p className="rounded-lg border border-zinc-200 bg-white px-4 py-3 text-sm text-zinc-700" data-testid="report-period">
          <span className="font-bold">Período que cubren los datos:</span> {period.label}
        </p>
      ) : (
        <p className="rounded-lg border border-zinc-200 bg-white p-4 text-sm text-zinc-600" data-testid="report-empty">
          No hay datos para este período y filtros. Si es la primera vez, el informe se calcula cada día a las 10:00 UTC.
        </p>
      )}

      {gaps.length > 0 && (
        <p role="alert" className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900" data-testid="capture-gap-warning">
          <span className="font-bold">Posible dato incompleto:</span> hubo salidas reales de insumos que el sistema no registró en {gaps.join(", ")}. Sus cifras
          pueden estar por debajo de la realidad.
        </p>
      )}

      {period && (
        <>
          <KpiSection definition={k1} summary={formatNumber(network.outbound_orders)}>
            {ranked(summaries, (r) => r.outbound_orders).map((row) => (
              <Row key={row.restaurant} name={row.restaurant} bar={<Bar value={row.outbound_orders} max={max((r) => r.outbound_orders)} />} value={formatNumber(row.outbound_orders)} />
            ))}
          </KpiSection>

          <KpiSection definition={k2} summary={`${formatNumber(network.units_issued)} unidades`}>
            {ranked(summaries, (r) => r.units_issued).map((row) => (
              <Row key={row.restaurant} name={row.restaurant} bar={<Bar value={row.units_issued} max={max((r) => r.units_issued)} tone="bg-zinc-700" />} value={`${formatNumber(row.units_issued)} uds.`} />
            ))}
          </KpiSection>

          <KpiSection definition={k3} summary={formatPercent(network.spoilage_rate_pct)}>
            {ranked(summaries, (r) => r.spoilage_rate_pct).map((row) => (
              <Row key={row.restaurant} name={row.restaurant} bar={<Bar value={row.spoilage_rate_pct ?? 0} max={100} />} value={formatPercent(row.spoilage_rate_pct)} />
            ))}
          </KpiSection>

          <KpiSection definition={k4} summary={`${formatNumber(network.stock_alerts_low)} bajas · ${formatNumber(network.stock_alerts_critical)} críticas`}>
            {ranked(summaries, (r) => r.stock_alerts_low + r.stock_alerts_critical).map((row) => (
              <Row
                key={row.restaurant}
                name={row.restaurant}
                bar={
                  <div className="space-y-1">
                    <Bar value={row.stock_alerts_low} max={max((r) => r.stock_alerts_low + r.stock_alerts_critical)} tone="bg-amber-500" />
                    <Bar value={row.stock_alerts_critical} max={max((r) => r.stock_alerts_low + r.stock_alerts_critical)} />
                  </div>
                }
                value={`${formatNumber(row.stock_alerts_low)} bajas · ${formatNumber(row.stock_alerts_critical)} críticas`}
              />
            ))}
          </KpiSection>

          <KpiSection definition={k5} summary={formatPercent(network.validation_rejection_rate_pct)}>
            {ranked(summaries, (r) => r.validation_rejection_rate_pct).map((row) => (
              <Row key={row.restaurant} name={row.restaurant} bar={<Bar value={row.validation_rejection_rate_pct ?? 0} max={100} tone="bg-zinc-700" />} value={formatPercent(row.validation_rejection_rate_pct)} />
            ))}
          </KpiSection>

          <KpiSection definition={k6} summary={`${formatNumber(network.ingredients_at_risk_eod)} en riesgo · ${formatNumber(network.ingredients_critical_eod)} críticos`}>
            {ranked(summaries, (r) => r.ingredients_at_risk_eod).map((row) => (
              <Row
                key={row.restaurant}
                name={row.restaurant}
                bar={<Bar value={row.ingredients_at_risk_eod} max={max((r) => r.ingredients_at_risk_eod)} />}
                value={`${formatNumber(row.ingredients_at_risk_eod)} en riesgo · ${formatNumber(row.ingredients_critical_eod)} críticos`}
              />
            ))}
          </KpiSection>
        </>
      )}
    </div>
  );
}
