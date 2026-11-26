import type { Metadata } from "next";
import { MenuBrowser } from "@/components/menu-browser";
import { ButtonLink, PageHero } from "@/components/ui";

export const metadata: Metadata = {
  title: "Menú",
  description:
    "Carta de Brasaland: carnes y aves a la brasa, platos para compartir, acompañantes, bebidas y postres. Precios en COP y USD.",
  alternates: { canonical: "/menu" },
};

export default function MenuPage() {
  return (
    <main>
      <PageHero
        eyebrow="La carta"
        title={
          <>
            Todo pasa por la <span className="text-ember">brasa</span>
          </>
        }
        intro="Carbón, fuego vivo y producto fresco. Elige tu país para ver los precios en pesos colombianos o en dólares."
      />
      <section className="mx-auto max-w-6xl px-5 pb-24 sm:px-8" aria-label="Carta de platos">
        <MenuBrowser />
        <p className="mt-10 text-sm text-ink/55">
          Precios con impuestos incluidos y sujetos a cambios. Informa a tu mesero de cualquier alergia o restricción
          alimentaria.
        </p>
        <div className="mt-10 flex flex-col items-start gap-4 rounded-3xl bg-ink p-8 text-cream sm:flex-row sm:items-center sm:justify-between">
          <p className="font-display text-3xl font-bold uppercase">¿Te antojaste? Reserva tu mesa.</p>
          <ButtonLink href="/reservas" variant="primary">
            Reservar mesa
          </ButtonLink>
        </div>
      </section>
    </main>
  );
}
