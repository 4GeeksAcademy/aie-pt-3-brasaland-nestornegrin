import { Reveal } from "./reveal";
import { ButtonLink } from "./ui";

const PERKS = [
  { big: "1 punto", text: "Acumula 1 punto por cada $10.000 COP o $5 USD" },
  { big: "Canjea", text: "Canjea tus puntos por descuentos y platos gratis" },
  { big: "Exclusivo", text: "Ofertas exclusivas para miembros" },
  { big: "100% digital", text: "Registro 100% digital - ¡ya no más tarjetas de papel!" },
];

export function BrasaPointsTeaser() {
  return (
    <section
      id="brasa-points"
      className="grain relative isolate overflow-hidden bg-gradient-to-br from-ember-dark via-ember to-amber py-20 text-ink sm:py-28"
      aria-labelledby="brasa-points-title"
    >
      <div className="relative mx-auto max-w-6xl px-5 sm:px-8">
        <div className="flex flex-col justify-between gap-6 sm:flex-row sm:items-end">
          <div className="max-w-2xl">
            <p className="font-display text-sm font-medium uppercase tracking-[0.3em] text-ink/70">Brasa Points</p>
            <h2
              id="brasa-points-title"
              className="mt-3 font-display text-4xl font-bold uppercase leading-[1.05] text-white sm:text-6xl"
            >
              Gana puntos con cada visita
            </h2>
          </div>
          <ButtonLink href="/brasa-points" variant="solid" className="self-start sm:self-auto">
            Registrarme ahora
          </ButtonLink>
        </div>
        <ul className="mt-12 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {PERKS.map((p, i) => (
            <li key={p.big}>
              <Reveal delay={i * 100} className="h-full">
                <article className="h-full rounded-3xl bg-ink p-6 text-cream">
                  <p className="font-display text-3xl font-bold uppercase text-amber">{p.big}</p>
                  <p className="mt-3 leading-relaxed text-cream/80">{p.text}</p>
                </article>
              </Reveal>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
