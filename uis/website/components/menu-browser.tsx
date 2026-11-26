"use client";

import { useMemo, useState } from "react";
import { DISHES, MENU_CATEGORIES, formatPrice, type MenuCategoryId } from "@/lib/site-data";
import { FoodImage } from "./food-image";

type Market = "CO" | "US";
const DIET_FILTERS = ["vegetariano", "sin gluten", "picante", "recomendado"] as const;

/** Carta interactiva: categorías, país/moneda y filtros alimentarios. */
export function MenuBrowser() {
  const [category, setCategory] = useState<MenuCategoryId | "todo">("todo");
  const [market, setMarket] = useState<Market>("CO");
  const [tag, setTag] = useState<(typeof DIET_FILTERS)[number] | null>(null);

  const visible = useMemo(
    () =>
      DISHES.filter((d) => (category === "todo" || d.category === category) && (!tag || d.tags?.includes(tag))),
    [category, tag],
  );

  const chip = (active: boolean) =>
    `rounded-full border px-4 py-2 text-sm font-bold uppercase tracking-wider transition ${
      active ? "border-ember bg-ember text-white" : "border-ink/20 bg-white text-ink hover:border-ember"
    }`;

  return (
    <div>
      <div className="sticky top-[4.5rem] z-30 -mx-5 border-b border-ink/10 bg-cream/95 px-5 py-4 backdrop-blur sm:-mx-8 sm:px-8">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div role="group" aria-label="Categorías de la carta" className="flex gap-2 overflow-x-auto pb-1">
            <button type="button" className={chip(category === "todo")} aria-pressed={category === "todo"} onClick={() => setCategory("todo")}>
              Todo
            </button>
            {MENU_CATEGORIES.map((c) => (
              <button
                key={c.id}
                type="button"
                className={`${chip(category === c.id)} whitespace-nowrap`}
                aria-pressed={category === c.id}
                onClick={() => setCategory(c.id)}
              >
                {c.label}
              </button>
            ))}
          </div>
          <div role="group" aria-label="País y moneda" className="flex shrink-0 rounded-full bg-ink p-1">
            {(
              [
                ["CO", "Colombia · COP"],
                ["US", "Florida · USD"],
              ] as const
            ).map(([m, label]) => (
              <button
                key={m}
                type="button"
                aria-pressed={market === m}
                onClick={() => setMarket(m)}
                className={`rounded-full px-4 py-2 text-xs font-bold uppercase tracking-wider transition ${
                  market === m ? "bg-amber text-ink" : "text-cream/80 hover:text-white"
                }`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
        <div role="group" aria-label="Filtros alimentarios" className="mt-3 flex flex-wrap items-center gap-2">
          <span className="text-xs font-bold uppercase tracking-widest text-ink/50">Filtrar:</span>
          {DIET_FILTERS.map((f) => (
            <button
              key={f}
              type="button"
              aria-pressed={tag === f}
              onClick={() => setTag(tag === f ? null : f)}
              className={`rounded-full border px-3 py-1 text-xs font-semibold capitalize transition ${
                tag === f ? "border-ink bg-ink text-cream" : "border-ink/20 text-ink/70 hover:border-ink"
              }`}
            >
              {f}
            </button>
          ))}
        </div>
      </div>

      <p className="sr-only" role="status" aria-live="polite">
        {visible.length} platos mostrados
      </p>

      {visible.length === 0 ? (
        <p className="py-20 text-center text-lg text-ink/60">No hay platos con ese filtro. Prueba con otro.</p>
      ) : (
        <ul className="mt-10 grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {visible.map((d) => (
            <li key={d.id}>
              <article className="flex h-full flex-col overflow-hidden rounded-3xl bg-white ring-1 ring-ink/5 transition hover:shadow-xl">
                {d.image ? (
                  <div className="relative aspect-[16/10] overflow-hidden bg-ink">
                    <FoodImage src={d.image} alt={d.name} />
                  </div>
                ) : null}
                {d.tags?.includes("recomendado") ? (
                  <span className="mx-6 mt-6 w-fit rounded-full bg-amber px-3 py-1 text-xs font-bold uppercase tracking-wider text-ink">
                    Recomendado
                  </span>
                ) : null}
                <div className="flex flex-1 flex-col p-6">
                  <div className="flex items-start justify-between gap-4">
                    <h3 className="font-display text-2xl font-bold uppercase leading-tight">{d.name}</h3>
                    <p className="shrink-0 font-display text-xl font-semibold text-ember">{formatPrice(d, market)}</p>
                  </div>
                  <p className="mt-2 flex-1 text-sm leading-relaxed text-ink/70">{d.description}</p>
                  {d.tags?.filter((t) => t !== "recomendado").length ? (
                    <ul className="mt-4 flex flex-wrap gap-2">
                      {d.tags
                        .filter((t) => t !== "recomendado")
                        .map((t) => (
                          <li key={t} className="rounded-full bg-sand px-3 py-1 text-xs font-semibold capitalize text-ink/70">
                            {t}
                          </li>
                        ))}
                    </ul>
                  ) : null}
                </div>
              </article>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

