import type { Metadata } from "next";
import { ContactForm } from "@/components/contact-form";
import { PageHero } from "@/components/ui";
import { SITE } from "@/lib/site-data";

export const metadata: Metadata = {
  title: "Contacto",
  description: "Escríbenos o llámanos: hola@brasaland.com · Colombia +57 4 123 4567 · Florida +1 305 123 4567.",
  alternates: { canonical: "/contacto" },
};

export default function ContactPage() {
  return (
    <main>
      <PageHero eyebrow="Contacto" title="Hablemos" intro="Reservas, eventos, comentarios o alianzas: te respondemos en español e inglés." />
      <section className="mx-auto grid max-w-6xl gap-10 px-5 py-14 sm:px-8 sm:py-20 lg:grid-cols-[1.5fr_1fr]">
        <ContactForm />
        <ul className="space-y-4">
          {[
            { k: "Email", v: SITE.email, h: `mailto:${SITE.email}` },
            { k: "Colombia", v: SITE.phones.colombia.display, h: SITE.phones.colombia.href },
            { k: "Florida", v: SITE.phones.florida.display, h: SITE.phones.florida.href },
          ].map((c) => (
            <li key={c.k} className="rounded-3xl bg-ink p-6 text-cream">
              <p className="text-xs font-bold uppercase tracking-[0.25em] text-amber">{c.k}</p>
              <a href={c.h} className="mt-1 block font-display text-2xl font-semibold hover:text-amber">{c.v}</a>
            </li>
          ))}
          <li className="rounded-3xl bg-sand p-6 text-sm leading-relaxed text-ink/80">
            <p className="font-bold uppercase tracking-widest text-ember">Horarios</p>
            <p className="mt-2">Colombia: {SITE.hours.colombia}</p>
            <p>Florida: {SITE.hours.florida}</p>
          </li>
        </ul>
      </section>
    </main>
  );
}
