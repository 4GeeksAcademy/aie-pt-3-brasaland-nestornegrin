"use client";

import { useState } from "react";

type Analysis = {
  total_processed: number;
  valid_records: number;
  invalid_records: number;
  by_category: Record<string, number>;
  by_status: Record<string, number>;
  average_closed_satisfaction: number | null;
  invalid_reasons: Record<string, number>;
};

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export function IncidentAnalysis() {
  const [file, setFile] = useState<File | null>(null);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function submitFile() {
    if (!file) {
      setError("Selecciona un fichero CSV antes de analizarlo.");
      return;
    }
    setLoading(true);
    setError(null);
    setAnalysis(null);
    const formData = new FormData();
    formData.append("file", file);
    try {
      const response = await fetch(`${API_URL}/api/incidents/analyze`, { method: "POST", body: formData });
      const payload = (await response.json()) as Analysis | { detail?: string };
      if (!response.ok) throw new Error("detail" in payload ? payload.detail : "No se pudo analizar el fichero");
      setAnalysis(payload as Analysis);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "No se pudo conectar con la API");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-6">
      <div className="rounded-xl border border-zinc-200 bg-white p-5 shadow-sm">
        <label htmlFor="incident-file" className="block text-sm font-bold text-zinc-800">
          Fichero CSV de incidencias
        </label>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <input
            id="incident-file"
            type="file"
            accept=".csv,text/csv"
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            className="block max-w-full text-sm text-zinc-600 file:mr-3 file:rounded-lg file:border-0 file:bg-red-800 file:px-4 file:py-2 file:font-semibold file:text-white hover:file:bg-red-900"
          />
          <button
            type="button"
            onClick={submitFile}
            disabled={loading}
            className="rounded-lg bg-zinc-900 px-4 py-2 text-sm font-bold text-white hover:bg-zinc-700 disabled:cursor-wait disabled:opacity-60"
          >
            {loading ? "Analizando..." : "Analizar CSV"}
          </button>
        </div>
        {file ? <p className="mt-2 text-xs text-zinc-500">Seleccionado: {file.name}</p> : null}
        {error ? <p role="alert" className="mt-3 text-sm font-semibold text-red-700">{error}</p> : null}
      </div>

      {analysis ? (
        <>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Stat label="Filas procesadas" value={analysis.total_processed} />
            <Stat label="Registros válidos" value={analysis.valid_records} />
            <Stat label="Registros inválidos" value={analysis.invalid_records} />
            <Stat label="Satisfacción cerrados" value={analysis.average_closed_satisfaction?.toFixed(2) ?? "N/D"} />
          </div>
          <div className="grid gap-4 md:grid-cols-3">
            <Breakdown title="Por categoría" values={analysis.by_category} />
            <Breakdown title="Por estado" values={analysis.by_status} />
            <Breakdown title="Motivos de invalidez" values={analysis.invalid_reasons} emptyLabel="Ninguno" />
          </div>
          <a
            href={`${API_URL}/api/incidents/results/export`}
            className="inline-flex rounded-lg border border-zinc-300 bg-white px-4 py-2 text-sm font-bold text-zinc-800 hover:border-red-800 hover:text-red-800"
          >
            Descargar resultados CSV
          </a>
        </>
      ) : null}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return <div className="rounded-xl border border-zinc-200 bg-white p-5 shadow-sm"><p className="text-2xl font-black text-red-800">{value}</p><p className="mt-1 text-xs font-semibold uppercase tracking-wide text-zinc-500">{label}</p></div>;
}

function Breakdown({ title, values, emptyLabel = "Sin datos" }: { title: string; values: Record<string, number>; emptyLabel?: string }) {
  const entries = Object.entries(values);
  return (
    <section className="rounded-xl border border-zinc-200 bg-white p-5 shadow-sm">
      <h3 className="text-sm font-bold uppercase tracking-wide text-zinc-500">{title}</h3>
      {entries.length ? <ul className="mt-3 space-y-2 text-sm">{entries.map(([key, value]) => <li key={key} className="flex justify-between gap-4"><span className="break-words text-zinc-700">{key}</span><strong>{value}</strong></li>)}</ul> : <p className="mt-3 text-sm text-zinc-500">{emptyLabel}</p>}
    </section>
  );
}