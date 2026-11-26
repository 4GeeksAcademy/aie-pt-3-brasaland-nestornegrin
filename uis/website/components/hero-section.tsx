import { PHOTOS } from "@/lib/site-data";
import { FoodImage } from "./food-image";
import { ButtonLink } from "./ui";

const STATS = [
  { value: "14", label: "restaurantes" },
  { value: "2", label: "países" },
  { value: "2008", label: "desde" },
];

export function HeroSection() {
  return (
    <section className="grain relative isolate flex min-h-[100svh] items-end overflow-hidden bg-ink text-cream">
      <div className="absolute inset-0 -z-10">
        <FoodImage src={PHOTOS.hero} alt="" priority sizes="100vw" className="opacity-60" />
        <div className="absolute inset-0 bg-gradient-to-t from-ink via-ink/60 to-ink/30" />
        <div className="absolute inset-0 bg-gradient-to-r from-ink/80 via-transparent to-transparent" />
      </div>

      <div className="mx-auto w-full max-w-6xl px-5 pb-16 pt-36 sm:px-8 sm:pb-24">
        <p className="animate-rise font-display text-sm uppercase tracking-[0.35em] text-amber">
          Colombia · Estados Unidos · Desde 2008
        </p>
        <h1 className="animate-rise mt-4 max-w-4xl font-display text-5xl font-bold uppercase leading-[0.98] [animation-delay:120ms] sm:text-7xl lg:text-8xl">
          El sabor de la <span className="text-ember">brasa</span>, en cada bocado
        </h1>
        <p className="animate-rise mt-6 max-w-xl text-lg leading-relaxed text-cream/85 [animation-delay:240ms] sm:text-xl">
          Desde 2008 sirviendo las mejores carnes a la brasa en Colombia y Estados Unidos. 14 ubicaciones, una misma
          pasión por la calidad y el sabor.
        </p>
        <div className="animate-rise mt-9 flex flex-col gap-3 [animation-delay:360ms] sm:flex-row">
          <ButtonLink href="/brasa-points" variant="primary">
            Únete a Brasa Points
          </ButtonLink>
          <ButtonLink href="/menu" variant="ghost">
            Ver la carta
          </ButtonLink>
          <ButtonLink href="/reservas" variant="ghost">
            Reservar mesa
          </ButtonLink>
        </div>

        <dl className="animate-rise mt-14 flex gap-10 border-t border-cream/15 pt-6 [animation-delay:480ms] sm:gap-16">
          {STATS.map((s) => (
            <div key={s.label}>
              <dt className="sr-only">{s.label}</dt>
              <dd>
                <span className="font-display text-4xl font-bold text-amber sm:text-5xl">{s.value}</span>
                <span className="ml-2 text-xs uppercase tracking-[0.25em] text-smoke">{s.label}</span>
              </dd>
            </div>
          ))}
        </dl>
      </div>
    </section>
  );
}
