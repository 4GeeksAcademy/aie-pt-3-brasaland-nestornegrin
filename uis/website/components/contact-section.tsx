import { SITE } from "@/lib/site-data";
import { Reveal } from "./reveal";
import { ButtonLink, SectionHeading } from "./ui";

export function ContactSection() {
  return (
    <section id="contacto" className="bg-cream py-20 sm:py-28" aria-labelledby="contacto-title">
      <div className="mx-auto grid max-w-6xl items-center gap-10 px-5 sm:px-8 lg:grid-cols-2">
        <SectionHeading
          id="contacto-title"
          eyebrow="Escríbenos o llámanos"
          title="Contacto"
          intro="Reservas, eventos, comentarios o alianzas: te respondemos en español e inglés."
        />
        <Reveal>
          <ul className="space-y-4">
            <li className="rounded-2xl bg-white p-5 ring-1 ring-ink/5">
              <p className="text-xs font-bold uppercase tracking-widest text-ember">Email</p>
              <a href={`mailto:${SITE.email}`} className="mt-1 block font-display text-2xl font-semibold hover:text-ember">
                {SITE.email}
              </a>
            </li>
            <li className="rounded-2xl bg-white p-5 ring-1 ring-ink/5">
              <p className="text-xs font-bold uppercase tracking-widest text-ember">Colombia</p>
              <a href={SITE.phones.colombia.href} className="mt-1 block font-display text-2xl font-semibold hover:text-ember">
                {SITE.phones.colombia.display}
              </a>
            </li>
            <li className="rounded-2xl bg-white p-5 ring-1 ring-ink/5">
              <p className="text-xs font-bold uppercase tracking-widest text-ember">Florida</p>
              <a href={SITE.phones.florida.href} className="mt-1 block font-display text-2xl font-semibold hover:text-ember">
                {SITE.phones.florida.display}
              </a>
            </li>
          </ul>
          <ButtonLink href="/contacto" variant="primary" className="mt-6">
            Enviar un mensaje
          </ButtonLink>
        </Reveal>
      </div>
    </section>
  );
}
