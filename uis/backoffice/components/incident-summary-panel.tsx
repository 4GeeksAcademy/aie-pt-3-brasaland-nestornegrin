"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch, readApiError } from "@/lib/api-client";
import { ORIGIN_LABELS, STATUS_LABELS, type IncidentSummaryData } from "@/lib/incidents";

export function IncidentSummaryPanel() {
  const [summary, setSummary] = useState<IncidentSummaryData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await apiFetch("/api/incidents/summary");
      if (!response.ok) {
        setError(await readApiError(response, "No se pudo cargar el resumen."));
        return;
      }
      setSummary(await response.json());
    } catch {
      setError("No se pudo conectar con el servidor.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void Promise.resolve().then(load);
  }, [load]);

  if (loading) return <p className="text-sm text-zinc-600">Cargando resumen...</p>;
  if (error) {
    return (
      <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">
        <p className="font-semibold">{error}</p>
        <button type="button" onClick={() => void load()} className="mt-2 font-bold underline">
          Reintentar
        </button>
      </div>
    );
  }
  if (!summary) return null;

  const branchesWithData = Object.entries(summary.by_branch).filter(([, count]) => count > 0);

  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      <StatCard title="Total de incidencias" value={summary.total} />
      <BreakdownCard title="Por estado" data={summary.by_status} labels={STATUS_LABELS} />
      <BreakdownCard title="Por categoría" data={summary.by_category} />
      <BreakdownCard title="Por origen" data={summary.by_origin} labels={ORIGIN_LABELS} />
      <BreakdownCard
        title="Por sede"
        data={Object.fromEntries(branchesWithData)}
        emptyMessage="Todavía no hay incidencias asociadas a una sede."
      />
    </div>
  );
}

function StatCard({ title, value }: { title: string; value: number }) {
  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-4">
      <p className="text-xs font-bold uppercase tracking-wide text-zinc-500">{title}</p>
      <p className="mt-1 text-3xl font-black text-red-800">{value}</p>
    </div>
  );
}

function BreakdownCard({
  title,
  data,
  labels,
  emptyMessage,
}: {
  title: string;
  data: Record<string, number>;
  labels?: Record<string, string>;
  emptyMessage?: string;
}) {
  const entries = Object.entries(data);
  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-4">
      <p className="text-xs font-bold uppercase tracking-wide text-zinc-500">{title}</p>
      {entries.length === 0 ? (
        <p className="mt-2 text-sm text-zinc-500">{emptyMessage ?? "Sin datos."}</p>
      ) : (
        <ul className="mt-2 space-y-1 text-sm">
          {entries.map(([key, count]) => (
            <li key={key} className="flex justify-between gap-4">
              <span className="text-zinc-700">{labels?.[key] ?? key}</span>
              <span className="font-bold text-zinc-900">{count}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
