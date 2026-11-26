import { SITE } from "@/lib/site-data";
import { Reveal } from "./reveal";
import { ButtonLink, SectionHeading } from "./ui";

const REGIONS = [
  {
    flag: "CO",
    name: "Colombia",
    summary: "10 restaurantes en Medellín, Bogotá y Cali",
    hours: `Horario: ${SITE.hours.colombia}`,
    cities: ["Medellín", "Bogotá", "Cali"],
  },
  {
    flag: "US",
    name: "Estados Unidos (Florida)",
    summary: "4 restaurantes en Miami y Orlando",
    hours: `Horario: ${SITE.hours.florida}`,
    cities: ["Miami", "Orlando"],
  },
];

export function LocationsSection() {
  return (
    <section id="ubicaciones" className="bg-sand py-20 sm:py-28" aria-labelledby="ubicaciones-title">
      <div className="mx-auto max-w-6xl px-5 sm:px-8">
        <SectionHeading
          id="ubicaciones-title"
          eyebrow="Dos países, una misma brasa"
          title="Nuestras ubicaciones"
        />
        <div className="mt-12 grid gap-6 md:grid-cols-2">
          {REGIONS.map((r, i) => (
            <Reveal key={r.name} delay={i * 140}>
              <article className="h-full rounded-3xl bg-ink p-8 text-cream">
                <span className="inline-flex h-10 min-w-10 items-center justify-center rounded-full bg-ember px-3 font-display text-sm font-bold tracking-widest">
                  {r.flag}
                </span>
                <h3 className="mt-5 font-display text-4xl font-bold uppercase">{r.name}</h3>
                <p className="mt-3 text-lg text-cream/80">{r.summary}</p>
                <p className="mt-2 font-semibold text-amber">{r.hours}</p>
                <ul className="mt-6 flex flex-wrap gap-2">
                  {r.cities.map((c) => (
                    <li key={c} className="rounded-full border border-cream/20 px-4 py-1.5 text-sm">
                      {c}
                    </li>
                  ))}
                </ul>
              </article>
            </Reveal>
          ))}
        </div>
        <div className="mt-10">
          <ButtonLink href="/ubicaciones" variant="dark">
            Ver los 14 restaurantes
          </ButtonLink>
        </div>
      </div>
    </section>
  );
}
