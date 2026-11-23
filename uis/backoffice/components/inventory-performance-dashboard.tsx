"use client";

import { useCallback, useEffect, useState } from "react";
import { readApiError } from "@/lib/api-client";
import {
  getInventoryKpis,
  getInventoryPipelineStatus,
  type Granularity,
  type KpiItem,
  type KpisResponse,
  type PipelineStatus,
} from "@/lib/inventory-performance";
import { InventoryPerformanceReport } from "@/components/inventory-performance-report";

const PERIODS = [
  { label: "Últimos 7 días", days: 7 },
  { label: "Últimos 14 días", days: 14 },
  { label: "Últimos 30 días", days: 30 },
];
const VIEWS: Array<{ label: string; value: Granularity }> = [
  { label: "Por día", value: "day" },
  { label: "Por semana", value: "week" },
];
const COUNTRIES: Array<{ label: string; value: string | null }> = [
  { label: "Colombia y Estados Unidos", value: null },
  { label: "Colombia", value: "Colombia" },
  { label: "Estados Unidos", value: "Estados Unidos" },
];

function Choice<T>({ label, options, value, onChange }: { label: string; options: Array<{ label: string; value: T }>; value: T; onChange: (value: T) => void }) {
  return (
    <div role="group" aria-label={label} className="flex flex-wrap items-center gap-2">
      {options.map((option) => (
        <button
          key={option.label}
          type="button"
          onClick={() => onChange(option.value)}
          aria-pressed={option.value === value}
          className={`rounded-lg border px-3 py-2 text-xs font-bold ${
            option.value === value ? "border-red-800 bg-red-800 text-white" : "border-zinc-300 bg-white text-zinc-700 hover:border-red-800"
          }`}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

/** Contenedor: pide los KPIs y el estado de actualización al backend y se los pasa a la vista. */
export function InventoryPerformanceDashboard() {
  const [days, setDays] = useState(14); // mismo período por defecto que el endpoint
  const [granularity, setGranularity] = useState<Granularity>("day");
  const [country, setCountry] = useState<string | null>(null);
  const [items, setItems] = useState<KpiItem[] | null>(null);
  const [status, setStatus] = useState<PipelineStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    await Promise.resolve();
    setLoading(true);
    setError(null);
    try {
      const [kpis, state] = await Promise.all([getInventoryKpis({ days, granularity, country }), getInventoryPipelineStatus()]);
      if (!kpis.ok) {
        setError(await readApiError(kpis, "No se pudo cargar el informe de inventario."));
        return;
      }
      setItems(((await kpis.json()) as KpisResponse).items);
      setStatus(state.ok ? ((await state.json()) as PipelineStatus) : null); // sin estado igual se muestran los KPIs
    } catch {
      setError("No se pudo conectar con el servidor.");
    } finally {
      setLoading(false);
    }
  }, [days, granularity, country]);

  useEffect(() => {
    void Promise.resolve().then(() => load());
  }, [load]);

  return (
    <div className="space-y-6">
      <div className="space-y-3">
        <Choice label="Período" options={PERIODS.map((p) => ({ label: p.label, value: p.days }))} value={days} onChange={setDays} />
        <Choice label="Vista" options={VIEWS} value={granularity} onChange={setGranularity} />
        <Choice label="País" options={COUNTRIES} value={country} onChange={setCountry} />
      </div>

      {loading && !items && <p className="rounded-lg border border-zinc-200 bg-white p-4 text-sm text-zinc-600">Cargando informe...</p>}

      {error && (
        <div role="alert" className="rounded-xl border border-red-200 bg-red-50 p-6 text-sm text-red-800">
          <p className="font-semibold">{error}</p>
          <button type="button" onClick={() => void load()} className="mt-3 font-bold underline">Reintentar</button>
        </div>
      )}

      {items && <InventoryPerformanceReport items={items} granularity={granularity} status={status} />}
    </div>
  );
}
