import { PHOTOS } from "@/lib/site-data";
import { FoodImage } from "./food-image";
import { Reveal } from "./reveal";
import { ButtonLink, SectionHeading } from "./ui";

export function OurStorySection() {
  return (
    <section className="grain relative overflow-hidden bg-ink py-20 text-cream sm:py-28" aria-labelledby="historia-title">
      <div className="relative mx-auto grid max-w-6xl items-center gap-12 px-5 sm:px-8 lg:grid-cols-2">
        <Reveal>
          <SectionHeading
            id="historia-title"
            eyebrow="Medellín, 2008"
            title="Nuestra historia"
            tone="light"
          />
          <p className="mt-6 text-lg leading-relaxed text-cream/80">
            Fundada en Medellín en 2008, Brasaland comenzó como un sueño familiar: compartir el auténtico sabor de la
            carne a la brasa con calidad constante y servicio cálido. Hoy somos 14 restaurantes en dos países, pero
            mantenemos la misma receta de éxito: productos frescos, técnicas tradicionales, y pasión por cada plato que
            servimos.
          </p>
          <ButtonLink href="/nuestra-historia" variant="ghost" className="mt-8">
            Conoce más
          </ButtonLink>
        </Reveal>
        <Reveal delay={150}>
          <figure className="relative">
            <div className="relative aspect-[4/5] overflow-hidden rounded-[2rem] ring-1 ring-cream/10">
              <FoodImage
                src={PHOTOS.grill}
                alt="Carnes cocinándose sobre la parrilla de carbón en un restaurante Brasaland"
                sizes="(min-width: 1024px) 40vw, 100vw"
              />
            </div>
            <figcaption className="absolute -bottom-5 left-5 rounded-2xl bg-amber px-6 py-4 text-ink shadow-xl">
              <span className="block font-display text-4xl font-bold leading-none">115</span>
              <span className="text-xs font-bold uppercase tracking-widest">personas en cocina, sala y equipo</span>
            </figcaption>
          </figure>
        </Reveal>
      </div>
    </section>
  );
}
