import type { Metadata } from "next";
import { FoodImage } from "@/components/food-image";
import { Reveal } from "@/components/reveal";
import { ButtonLink, PageHero, SectionHeading } from "@/components/ui";
import { PHOTOS } from "@/lib/site-data";

export const metadata: Metadata = {
  title: "Nuestra historia",
  description:
    "Brasaland nació en Medellín en 2008 como un sueño familiar. Hoy son 14 restaurantes en Colombia y Florida con la misma receta: producto fresco, técnica tradicional y pasión.",
  alternates: { canonical: "/nuestra-historia" },
};

const NUMBERS = [
  { v: "2008", l: "Año de fundación en Medellín" },
  { v: "14", l: "Restaurantes propios" },
  { v: "2", l: "Países: Colombia y Estados Unidos" },
  { v: "115", l: "Personas en cocina, sala y equipo" },
];

const VALUES = [
  { t: "Calidad consistente", d: "Mismas recetas y estándares en todos los locales, con ingredientes frescos seleccionados cada día." },
  { t: "Experiencia cálida", d: "Servicio amable y atento, y un ambiente familiar en cada visita." },
  { t: "Rapidez", d: "Tu comida lista en minutos, sin sacrificar sabor ni calidad." },
];

export default function HistoryPage() {
  return (
    <main>
      <PageHero
        eyebrow="Medellín, 2008"
        title="Un sueño familiar, hecho brasa"
        intro="Compartir el auténtico sabor de la carne a la brasa con calidad constante y servicio cálido."
      />

      <section className="mx-auto grid max-w-6xl items-center gap-12 px-5 py-16 sm:px-8 sm:py-24 lg:grid-cols-2">
        <Reveal>
          <SectionHeading eyebrow="Cómo empezó" title="De un local a 14 restaurantes" />
          <div className="mt-6 space-y-4 text-lg leading-relaxed text-ink/80">
            <p>
              Fundada en Medellín en 2008, Brasaland comenzó como un sueño familiar: compartir el auténtico sabor de la
              carne a la brasa con calidad constante y servicio cálido.
            </p>
            <p>
              Hoy somos 14 restaurantes en dos países, pero mantenemos la misma receta de éxito: productos frescos,
              técnicas tradicionales, y pasión por cada plato que servimos.
            </p>
          </div>
        </Reveal>
        <Reveal delay={150}>
          <div className="relative aspect-[4/3] overflow-hidden rounded-[2rem] shadow-xl">
            <FoodImage src={PHOTOS.dining} alt="Comedor de un restaurante Brasaland" sizes="(min-width: 1024px) 45vw, 100vw" />
          </div>
        </Reveal>
      </section>

      <section className="bg-ink py-16 text-cream sm:py-20" aria-label="Brasaland en cifras">
        <dl className="mx-auto grid max-w-6xl gap-8 px-5 sm:grid-cols-2 sm:px-8 lg:grid-cols-4">
          {NUMBERS.map((n) => (
            <div key={n.l} className="border-l-2 border-ember pl-5">
              <dt className="sr-only">{n.l}</dt>
              <dd>
                <span className="block font-display text-6xl font-bold text-amber">{n.v}</span>
                <span className="mt-1 block text-sm uppercase tracking-widest text-smoke">{n.l}</span>
              </dd>
            </div>
          ))}
        </dl>
      </section>

      <section className="mx-auto max-w-6xl px-5 py-16 sm:px-8 sm:py-24" aria-labelledby="valores-title">
        <SectionHeading id="valores-title" eyebrow="Lo que nos guía" title="Tres pilares" />
        <ul className="mt-10 grid gap-6 md:grid-cols-3">
          {VALUES.map((v, i) => (
            <li key={v.t}>
              <Reveal delay={i * 120} className="h-full">
                <article className="h-full rounded-3xl bg-white p-8 ring-1 ring-ink/5">
                  <h3 className="font-display text-3xl font-bold uppercase text-ember">{v.t}</h3>
                  <p className="mt-3 leading-relaxed text-ink/75">{v.d}</p>
                </article>
              </Reveal>
            </li>
          ))}
        </ul>
        <div className="mt-12 flex flex-wrap gap-3">
          <ButtonLink href="/menu">Ver la carta</ButtonLink>
          <ButtonLink href="/ubicaciones" variant="dark">Encuentra tu restaurante</ButtonLink>
        </div>
      </section>
    </main>
  );
}
