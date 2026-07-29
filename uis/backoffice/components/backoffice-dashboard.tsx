"use client";

import { useMemo, useState } from "react";
import type { Country } from "../../../src/types/models";
import {
  aggregateNumbers,
  binarySearch,
  countRegistrationsByCountry,
  countRegistrationsBySource,
  filterRegistrationsByCriteria,
  linearSearch,
  sortBy,
  validateRegistration,
} from "../../../src/index";
import { sampleRegistrations } from "../data/sample-registrations";

type SortField = "fullName" | "country" | "city" | "birthDate";

function ageFromBirthDate(birthDate: string): number {
  const parsed = new Date(birthDate);
  const today = new Date();
  let age = today.getFullYear() - parsed.getFullYear();
  const monthDiff = today.getMonth() - parsed.getMonth();
  if (monthDiff < 0 || (monthDiff === 0 && today.getDate() < parsed.getDate())) {
    age -= 1;
  }
  return age;
}

export function BackofficeDashboard() {
  const [countryFilter, setCountryFilter] = useState<Country | "all">("all");
  const [sortField, setSortField] = useState<SortField>("fullName");
  const [searchEmail, setSearchEmail] = useState("");

  const filtered = useMemo(() => {
    if (countryFilter === "all") return sampleRegistrations;
    // Reutiliza filterRegistrationsByCriteria de src/utils/collections.ts (Hito 2)
    return filterRegistrationsByCriteria(sampleRegistrations, { country: countryFilter });
  }, [countryFilter]);

  const sorted = useMemo(() => sortBy(filtered, sortField, "asc"), [filtered, sortField]);

  const ages = useMemo(() => sampleRegistrations.map((r) => ageFromBirthDate(r.birthDate)), []);
  const ageStats = useMemo(() => aggregateNumbers(ages), [ages]);

  const countryCounts = useMemo(() => countRegistrationsByCountry(sampleRegistrations), []);
  const sourceCounts = useMemo(() => countRegistrationsBySource(sampleRegistrations), []);

  const emails = useMemo(() => sampleRegistrations.map((r) => r.email), []);
  const linearIndex = searchEmail ? linearSearch(emails, searchEmail.trim()) : null;

  const sortedAges = useMemo(() => [...ages].sort((a, b) => a - b), [ages]);
  const [ageToFind, setAgeToFind] = useState(sortedAges[0] ?? 0);
  const binaryIndex = binarySearch(sortedAges, ageToFind);

  const invalidSample = { ...sampleRegistrations[2] };
  const validation = validateRegistration(invalidSample);

  return (
    <div className="space-y-8">
      <section aria-labelledby="stats-title" className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <h2 id="stats-title" className="sr-only">
          Estadísticas de registros
        </h2>
        <StatCard label="Total registros" value={sampleRegistrations.length} />
        <StatCard label="Edad promedio" value={ageStats.average.toFixed(1)} />
        <StatCard label="Edad mínima" value={ageStats.min} />
        <StatCard label="Edad máxima" value={ageStats.max} />
      </section>

      <section aria-labelledby="counts-title" className="grid gap-4 sm:grid-cols-2">
        <div className="rounded-xl border border-zinc-200 bg-white p-5 shadow-sm">
          <h2 id="counts-title" className="text-sm font-bold uppercase tracking-wide text-zinc-500">
            Registros por país
          </h2>
          <ul className="mt-3 space-y-1 text-zinc-800">
            {Object.entries(countryCounts).map(([country, count]) => (
              <li key={country} className="flex justify-between text-sm">
                <span>{country}</span>
                <span className="font-semibold">{count}</span>
              </li>
            ))}
          </ul>
        </div>
        <div className="rounded-xl border border-zinc-200 bg-white p-5 shadow-sm">
          <h2 className="text-sm font-bold uppercase tracking-wide text-zinc-500">Registros por origen</h2>
          <ul className="mt-3 space-y-1 text-zinc-800">
            {Object.entries(sourceCounts).map(([source, count]) => (
              <li key={source} className="flex justify-between text-sm">
                <span>{source}</span>
                <span className="font-semibold">{count}</span>
              </li>
            ))}
          </ul>
        </div>
      </section>

      <section aria-labelledby="table-title" className="rounded-xl border border-zinc-200 bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 id="table-title" className="text-sm font-bold uppercase tracking-wide text-zinc-500">
            Registros Brasa Points
          </h2>
          <div className="flex flex-wrap gap-3">
            <label className="flex items-center gap-2 text-sm text-zinc-700">
              País:
              <select
                value={countryFilter}
                onChange={(e) => setCountryFilter(e.target.value as Country | "all")}
                className="rounded-lg border border-zinc-300 px-2 py-1 text-sm"
              >
                <option value="all">Todos</option>
                <option value="Colombia">Colombia</option>
                <option value="Estados Unidos">Estados Unidos</option>
              </select>
            </label>
            <label className="flex items-center gap-2 text-sm text-zinc-700">
              Ordenar por:
              <select
                value={sortField}
                onChange={(e) => setSortField(e.target.value as SortField)}
                className="rounded-lg border border-zinc-300 px-2 py-1 text-sm"
              >
                <option value="fullName">Nombre</option>
                <option value="country">País</option>
                <option value="city">Ciudad</option>
                <option value="birthDate">Fecha de nacimiento</option>
              </select>
            </label>
          </div>
        </div>

        <div className="mt-4 overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-zinc-200 text-zinc-500">
                <th className="py-2 pr-4">Nombre</th>
                <th className="py-2 pr-4">País</th>
                <th className="py-2 pr-4">Ciudad</th>
                <th className="py-2 pr-4">Origen</th>
                <th className="py-2 pr-4">Términos</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((registration) => (
                <tr key={registration.id} className="border-b border-zinc-100 text-zinc-800">
                  <td className="py-2 pr-4 font-medium">{registration.fullName}</td>
                  <td className="py-2 pr-4">{registration.country}</td>
                  <td className="py-2 pr-4">{registration.city}</td>
                  <td className="py-2 pr-4">{registration.source}</td>
                  <td className="py-2 pr-4">{registration.acceptedTerms ? "Sí" : "No"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {sorted.length === 0 ? (
            <p className="py-4 text-sm text-zinc-500">No hay registros para este filtro.</p>
          ) : null}
        </div>
      </section>

      <section aria-labelledby="search-title" className="rounded-xl border border-zinc-200 bg-white p-5 shadow-sm">
        <h2 id="search-title" className="text-sm font-bold uppercase tracking-wide text-zinc-500">
          Buscar registro por email
        </h2>
        <input
          type="email"
          value={searchEmail}
          onChange={(e) => setSearchEmail(e.target.value)}
          placeholder="ana@brasaland.com"
          className="mt-3 w-full max-w-sm rounded-lg border border-zinc-300 px-3 py-2 text-sm"
          aria-describedby="search-result"
        />
        <p id="search-result" className="mt-2 text-sm text-zinc-700">
          {searchEmail
            ? linearIndex !== null && linearIndex >= 0
              ? `Encontrado en la posición ${linearIndex} (búsqueda lineal).`
              : "No se encontró ningún registro con ese email."
            : "Escribe un email para buscarlo con linearSearch."}
        </p>

        <div className="mt-5 border-t border-zinc-100 pt-4">
          <label htmlFor="age-search" className="block text-sm font-semibold text-zinc-700">
            Buscar edad exacta entre los registros (búsqueda binaria, edades ordenadas: {sortedAges.join(", ")})
          </label>
          <input
            id="age-search"
            type="number"
            value={ageToFind}
            onChange={(e) => setAgeToFind(Number(e.target.value))}
            className="mt-2 w-32 rounded-lg border border-zinc-300 px-3 py-2 text-sm"
          />
          <p className="mt-2 text-sm text-zinc-700">
            {binaryIndex >= 0
              ? `Encontrada en la posición ${binaryIndex} del arreglo ordenado (búsqueda binaria).`
              : "Ninguna persona registrada tiene exactamente esa edad."}
          </p>
        </div>
      </section>

      <section aria-labelledby="validation-title" className="rounded-xl border border-zinc-200 bg-white p-5 shadow-sm">
        <h2 id="validation-title" className="text-sm font-bold uppercase tracking-wide text-zinc-500">
          Validación de ejemplo (validateRegistration)
        </h2>
        <p className="mt-2 text-sm text-zinc-600">
          Registro de ejemplo: <strong>{invalidSample.fullName}</strong> — resultado:{" "}
          <strong>{validation.isValid ? "válido" : "inválido"}</strong>
        </p>
        {!validation.isValid ? (
          <ul className="mt-2 list-inside list-disc text-sm text-red-700">
            {validation.errors.map((error) => (
              <li key={error}>{error}</li>
            ))}
          </ul>
        ) : null}
      </section>
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-5 text-center shadow-sm">
      <p className="text-3xl font-black text-red-800">{value}</p>
      <p className="mt-1 text-xs font-semibold uppercase tracking-wide text-zinc-500">{label}</p>
    </div>
  );
}
