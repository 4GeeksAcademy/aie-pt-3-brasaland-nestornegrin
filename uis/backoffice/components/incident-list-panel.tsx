"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch, readApiError } from "@/lib/api-client";
import { ALLOWED_TRANSITIONS, BRANCHES, ORIGINS, ORIGIN_LABELS, STATUS_LABELS, type Incident } from "@/lib/incidents";

type Filters = { status: string; origin: string; branch: string };

const STATUS_OPTIONS = Object.keys(STATUS_LABELS);

export function IncidentListPanel() {
  const [incidents, setIncidents] = useState<Incident[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [filters, setFilters] = useState<Filters>({ status: "", origin: "", branch: "" });
  const [rowErrors, setRowErrors] = useState<Record<number, string>>({});

  const load = useCallback(async (activeFilters: Filters) => {
    await Promise.resolve(); // diferir a un microtask: react-hooks/set-state-in-effect
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (activeFilters.status) params.set("status", activeFilters.status);
      if (activeFilters.origin) params.set("origin", activeFilters.origin);
      if (activeFilters.branch) params.set("branch", activeFilters.branch);
      const query = params.toString();
      const response = await apiFetch(`/api/incidents${query ? `?${query}` : ""}`);
      if (!response.ok) {
        setError(await readApiError(response, "No se pudieron cargar las incidencias."));
        return;
      }
      setIncidents(await response.json());
    } catch {
      setError("No se pudo conectar con el servidor.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // Se difiere la invocación a un microtask (en vez de llamar a load()
    // directamente) porque react-hooks/set-state-in-effect rastrea el
    // setState síncrono incluso a través de una función referenciada
    // (useCallback) invocada de forma directa desde el cuerpo del efecto.
    void Promise.resolve().then(() => load(filters));
  }, [filters, load]);

  async function changeStatus(incident: Incident, newStatus: string) {
    const previousStatus = incident.status;
    setIncidents((current) => current?.map((item) => (item.id === incident.id ? { ...item, status: newStatus } : item)) ?? current);
    setRowErrors((current) => ({ ...current, [incident.id]: "" }));

    try {
      const response = await apiFetch(`/api/incidents/${incident.id}/status`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: newStatus }),
      });
      if (!response.ok) {
        const message = await readApiError(response, "No se pudo actualizar el estado.");
        setIncidents((current) => current?.map((item) => (item.id === incident.id ? { ...item, status: previousStatus } : item)) ?? current);
        setRowErrors((current) => ({ ...current, [incident.id]: message }));
      }
    } catch {
      setIncidents((current) => current?.map((item) => (item.id === incident.id ? { ...item, status: previousStatus } : item)) ?? current);
      setRowErrors((current) => ({ ...current, [incident.id]: "No se pudo conectar con el servidor." }));
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-4">
        <FilterSelect
          label="Estado"
          value={filters.status}
          onChange={(value) => setFilters((current) => ({ ...current, status: value }))}
          options={[{ value: "", label: "Todos" }, ...STATUS_OPTIONS.map((status) => ({ value: status, label: STATUS_LABELS[status] }))]}
        />
        <FilterSelect
          label="Origen"
          value={filters.origin}
          onChange={(value) => setFilters((current) => ({ ...current, origin: value }))}
          options={[{ value: "", label: "Todos" }, ...ORIGINS]}
        />
        <FilterSelect
          label="Sede"
          value={filters.branch}
          onChange={(value) => setFilters((current) => ({ ...current, branch: value }))}
          options={[{ value: "", label: "Todas" }, ...BRANCHES]}
        />
      </div>

      {loading ? <p className="text-sm text-zinc-600">Cargando incidencias...</p> : null}

      {!loading && error ? (
        <div className="rounded-lg border border-red-200 bg-red-50 p-4">
          <p className="text-sm font-semibold text-red-800">{error}</p>
          <button type="button" onClick={() => void load(filters)} className="mt-2 text-sm font-bold text-red-800 underline">
            Reintentar
          </button>
        </div>
      ) : null}

      {!loading && !error && incidents && incidents.length === 0 ? (
        <p className="rounded-lg border border-zinc-200 bg-white p-4 text-sm text-zinc-600">
          No hay incidencias que coincidan con los filtros seleccionados.
        </p>
      ) : null}

      {!loading && !error && incidents && incidents.length > 0 ? (
        <div className="overflow-x-auto rounded-xl border border-zinc-200 bg-white">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-zinc-200 bg-zinc-50 text-xs font-bold uppercase tracking-wide text-zinc-500">
              <tr>
                <th className="px-4 py-3">Título</th>
                <th className="px-4 py-3">Categoría</th>
                <th className="px-4 py-3">Origen</th>
                <th className="px-4 py-3">Sede</th>
                <th className="px-4 py-3">Estado</th>
              </tr>
            </thead>
            <tbody>
              {incidents.map((incident) => (
                <tr key={incident.id} className="border-b border-zinc-100 align-top last:border-0">
                  <td className="px-4 py-3 font-semibold text-zinc-900">{incident.title}</td>
                  <td className="px-4 py-3 text-zinc-700">{incident.category}</td>
                  <td className="px-4 py-3 text-zinc-700">{ORIGIN_LABELS[incident.origin] ?? incident.origin}</td>
                  <td className="px-4 py-3 text-zinc-700">{incident.branch}</td>
                  <td className="px-4 py-3">
                    <select
                      value={incident.status}
                      onChange={(event) => void changeStatus(incident, event.target.value)}
                      className="rounded-lg border border-zinc-300 px-2 py-1 text-sm"
                    >
                      <option value={incident.status}>{STATUS_LABELS[incident.status]}</option>
                      {(ALLOWED_TRANSITIONS[incident.status] ?? []).map((next) => (
                        <option key={next} value={next}>{STATUS_LABELS[next]}</option>
                      ))}
                    </select>
                    {rowErrors[incident.id] ? <p className="mt-1 text-xs text-red-700">{rowErrors[incident.id]}</p> : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}

function FilterSelect({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: readonly { value: string; label: string }[];
}) {
  return (
    <div>
      <label className="block text-xs font-bold uppercase tracking-wide text-zinc-500">{label}</label>
      <select value={value} onChange={(event) => onChange(event.target.value)} className="mt-1 rounded-lg border border-zinc-300 px-2 py-1 text-sm">
        {options.map((option) => (
          <option key={option.value} value={option.value}>{option.label}</option>
        ))}
      </select>
    </div>
  );
}
