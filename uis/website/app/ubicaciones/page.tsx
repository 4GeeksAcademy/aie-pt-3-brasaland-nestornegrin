import type { Metadata } from "next";
import { LocationsBrowser } from "@/components/locations-browser";
import { PageHero } from "@/components/ui";

export const metadata: Metadata = {
  title: "Ubicaciones",
  description:
    "Los 14 restaurantes Brasaland: 10 en Colombia (Medellín, Bogotá y Cali) y 4 en Florida (Miami y Orlando). Horarios, teléfonos y cómo llegar.",
  alternates: { canonical: "/ubicaciones" },
};

export default function LocationsPage() {
  return (
    <main>
      <PageHero
        eyebrow="Encuéntranos"
        title="14 restaurantes, dos países"
        intro="10 restaurantes en Medellín, Bogotá y Cali, y 4 en Miami y Orlando. Elige el más cercano."
      />
      <section className="mx-auto max-w-6xl px-5 py-14 sm:px-8 sm:py-20" aria-label="Directorio de restaurantes">
        <LocationsBrowser />
      </section>
    </main>
  );
}
