"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import type { City, Country } from "../../../src/types/models";
import { cityOptionsByCountry, locationsByCountryAndCity } from "@/lib/locations-data";
import { SITE } from "@/lib/site-data";

const COUNTRIES = Object.keys(cityOptionsByCountry) as Country[];

/**
 * Directorio de los 14 restaurantes. Lee `lib/locations-data.ts` (fuente única
 * de verdad) y permite filtrar por país y ciudad.
 */
export function LocationsBrowser() {
  const [country, setCountry] = useState<Country | "todos">("todos");
  const [city, setCity] = useState<City | "todas">("todas");

  const cities = country === "todos" ? [] : cityOptionsByCountry[country];

  const rows = useMemo(() => {
    const out: { country: Country; city: City; name: string }[] = [];
    for (const c of COUNTRIES) {
      if (country !== "todos" && c !== country) continue;
      for (const ci of cityOptionsByCountry[c]) {
        if (city !== "todas" && ci !== city) continue;
        for (const name of locationsByCountryAndCity[c][ci] ?? []) out.push({ country: c, city: ci, name });
      }
    }
    return out;
  }, [country, city]);

  const chip = (active: boolean) =>
    `rounded-full border px-4 py-2 text-sm font-bold uppercase tracking-wider transition ${
      active ? "border-ember bg-ember text-white" : "border-ink/20 bg-white hover:border-ember"
    }`;

  return (
    <div>
      <div role="group" aria-label="Filtrar por país" className="flex flex-wrap gap-2">
        <button type="button" className={chip(country === "todos")} aria-pressed={country === "todos"} onClick={() => { setCountry("todos"); setCity("todas"); }}>
          Todos ({Object.values(locationsByCountryAndCity).reduce((n, byCity) => n + Object.values(byCity).flat().length, 0)})
        </button>
        {COUNTRIES.map((c) => (
          <button key={c} type="button" className={chip(country === c)} aria-pressed={country === c} onClick={() => { setCountry(c); setCity("todas"); }}>
            {c}
          </button>
        ))}
      </div>
      {cities.length > 0 ? (
        <div role="group" aria-label="Filtrar por ciudad" className="mt-3 flex flex-wrap gap-2">
          <button type="button" className={chip(city === "todas")} aria-pressed={city === "todas"} onClick={() => setCity("todas")}>
            Todas las ciudades
          </button>
          {cities.map((ci) => (
            <button key={ci} type="button" className={chip(city === ci)} aria-pressed={city === ci} onClick={() => setCity(ci)}>
              {ci}
            </button>
          ))}
        </div>
      ) : null}

      <p className="sr-only" role="status" aria-live="polite">
        {rows.length} restaurantes mostrados
      </p>

      <ul className="mt-10 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
        {rows.map((r) => {
          const co = r.country === "Colombia";
          const phone = co ? SITE.phones.colombia : SITE.phones.florida;
          return (
            <li key={r.name}>
              <article className="flex h-full flex-col rounded-3xl bg-white p-6 ring-1 ring-ink/5 transition hover:-translate-y-1 hover:shadow-xl">
                <p className="text-xs font-bold uppercase tracking-[0.25em] text-ember">
                  {r.city} · {co ? "Colombia" : "Florida"}
                </p>
                <h3 className="mt-2 font-display text-3xl font-bold uppercase leading-tight">{r.name}</h3>
                <p className="mt-3 text-sm text-ink/70">{co ? SITE.hours.colombia : SITE.hours.florida}</p>
                <div className="mt-6 flex flex-wrap gap-2 pt-1">
                  <a
                    href={phone.href}
                    className="rounded-full border border-ink/20 px-4 py-2 text-sm font-bold hover:bg-ink hover:text-cream"
                  >
                    Llamar
                  </a>
                  <a
                    href={`https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(`${r.name} ${r.city}`)}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="rounded-full border border-ink/20 px-4 py-2 text-sm font-bold hover:bg-ink hover:text-cream"
                  >
                    Cómo llegar
                  </a>
                  <Link
                    href={`/reservas?local=${encodeURIComponent(r.name)}`}
                    className="rounded-full bg-ember px-4 py-2 text-sm font-bold text-white hover:bg-ember-dark"
                  >
                    Reservar
                  </Link>
                </div>
              </article>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
