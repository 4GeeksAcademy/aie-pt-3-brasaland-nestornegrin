import { DISHES, FEATURED_DISH_IDS, PHOTOS, formatPrice } from "@/lib/site-data";
import { FoodImage } from "./food-image";
import { Reveal } from "./reveal";
import { ButtonLink, SectionHeading } from "./ui";

export function FeaturedDishes() {
  const dishes = FEATURED_DISH_IDS.map((id) => DISHES.find((d) => d.id === id)).filter(
    (d): d is NonNullable<typeof d> => Boolean(d),
  );

  return (
    <section className="bg-cream py-20 sm:py-28" aria-labelledby="destacados-title">
      <div className="mx-auto max-w-6xl px-5 sm:px-8">
        <div className="flex flex-col justify-between gap-6 sm:flex-row sm:items-end">
          <SectionHeading
            id="destacados-title"
            eyebrow="De la parrilla a tu mesa"
            title="Los favoritos de la casa"
            intro="Las mismas recetas y los mismos estándares en cada local: lo que pruebas en Medellín sabe igual en Miami."
          />
          <ButtonLink href="/menu" variant="dark" className="self-start sm:self-auto">
            Ver toda la carta
          </ButtonLink>
        </div>

        <ul className="mt-12 grid gap-6 md:grid-cols-3">
          {dishes.map((dish, i) => (
            <li key={dish.id}>
              <Reveal delay={i * 120}>
                <article className="group overflow-hidden rounded-3xl bg-white shadow-sm ring-1 ring-ink/5 transition hover:-translate-y-1 hover:shadow-xl">
                  <div className="relative aspect-[4/3] overflow-hidden">
                    <FoodImage
                      src={dish.image ?? PHOTOS.plate}
                      alt={`${dish.name}, plato de Brasaland`}
                      className="transition duration-700 group-hover:scale-105"
                    />
                  </div>
                  <div className="p-6">
                    <h3 className="font-display text-2xl font-bold uppercase">{dish.name}</h3>
                    <p className="mt-2 text-sm leading-relaxed text-ink/70">{dish.description}</p>
                    <p className="mt-4 font-display text-xl font-semibold text-ember">
                      {formatPrice(dish, "CO")}
                      <span className="ml-2 text-sm font-medium text-ink/50">· {formatPrice(dish, "US")} en Florida</span>
                    </p>
                  </div>
                </article>
              </Reveal>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
