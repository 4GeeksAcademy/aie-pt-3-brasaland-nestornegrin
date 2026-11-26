import type { Metadata } from "next";
import { ReservationForm } from "@/components/reservation-form";
import { PageHero } from "@/components/ui";
import { SITE } from "@/lib/site-data";

export const metadata: Metadata = {
  title: "Reservas",
  description: "Reserva tu mesa en cualquiera de los 14 restaurantes Brasaland en Colombia y Florida.",
  alternates: { canonical: "/reservas" },
};

export default async function ReservationsPage({
  searchParams,
}: {
  searchParams: Promise<{ local?: string | string[] }>;
}) {
  const { local } = await searchParams;
  const defaultLocal = Array.isArray(local) ? local[0] : local;

  return (
    <main>
      <PageHero
        eyebrow="Reservas"
        title="Tu mesa, lista y con brasa"
        intro="Cuéntanos cuándo y cuántos son. Te confirmamos por email o teléfono."
      />
      <section className="mx-auto grid max-w-6xl gap-10 px-5 py-14 sm:px-8 sm:py-20 lg:grid-cols-[1.6fr_1fr]">
        <ReservationForm defaultLocal={defaultLocal ?? ""} />
        <aside className="h-fit rounded-3xl bg-ink p-8 text-cream">
          <h2 className="font-display text-3xl font-bold uppercase">¿Prefieres llamar?</h2>
          <ul className="mt-5 space-y-3">
            <li>
              <a className="block text-lg font-semibold hover:text-amber" href={SITE.phones.colombia.href}>
                Colombia · {SITE.phones.colombia.display}
              </a>
            </li>
            <li>
              <a className="block text-lg font-semibold hover:text-amber" href={SITE.phones.florida.href}>
                Florida · {SITE.phones.florida.display}
              </a>
            </li>
          </ul>
          <p className="mt-6 text-sm leading-relaxed text-smoke">
            Horario: {SITE.hours.colombia} (Colombia) · {SITE.hours.florida} (Florida). Para grupos de más de 12
            personas o eventos, escríbenos a {SITE.email}.
          </p>
        </aside>
      </section>
    </main>
  );
}
