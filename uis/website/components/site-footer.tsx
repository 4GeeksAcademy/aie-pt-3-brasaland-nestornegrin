import Link from "next/link";
import { NAV_LINKS, SITE } from "@/lib/site-data";
import { Logo } from "./logo";

export function SiteFooter() {
  return (
    <footer className="grain relative overflow-hidden bg-ink text-cream" role="contentinfo">
      <div className="relative mx-auto grid max-w-6xl gap-12 px-5 py-16 sm:px-8 md:grid-cols-[1.3fr_1fr_1fr]">
        <div>
          <Logo />
          <p className="mt-5 max-w-sm leading-relaxed text-smoke">
            Comida a la brasa con calidad constante, servicio cálido y rapidez. 14 restaurantes en Colombia y Florida,
            desde 2008.
          </p>
          <div className="mt-6 flex gap-3">
            <a
              href={SITE.social.instagram}
              target="_blank"
              rel="noopener noreferrer"
              className="rounded-full border border-cream/25 px-4 py-2 text-sm font-semibold hover:bg-cream hover:text-ink"
            >
              Instagram
            </a>
            <a
              href={SITE.social.facebook}
              target="_blank"
              rel="noopener noreferrer"
              className="rounded-full border border-cream/25 px-4 py-2 text-sm font-semibold hover:bg-cream hover:text-ink"
            >
              Facebook
            </a>
          </div>
        </div>

        <nav aria-label="Mapa del sitio">
          <h2 className="font-display text-sm uppercase tracking-[0.25em] text-amber">Explora</h2>
          <ul className="mt-4 space-y-2.5">
            {NAV_LINKS.map((l) => (
              <li key={l.href}>
                <Link href={l.href} className="text-cream/80 hover:text-white">
                  {l.label}
                </Link>
              </li>
            ))}
            <li>
              <Link href="/reservas" className="text-cream/80 hover:text-white">
                Reservas
              </Link>
            </li>
          </ul>
        </nav>

        <div>
          <h2 className="font-display text-sm uppercase tracking-[0.25em] text-amber">Hablemos</h2>
          <ul className="mt-4 space-y-2.5 text-cream/80">
            <li>
              <a href={`mailto:${SITE.email}`} className="hover:text-white">
                {SITE.email}
              </a>
            </li>
            <li>
              <a href={SITE.phones.colombia.href} className="hover:text-white">
                Colombia · {SITE.phones.colombia.display}
              </a>
            </li>
            <li>
              <a href={SITE.phones.florida.href} className="hover:text-white">
                Florida · {SITE.phones.florida.display}
              </a>
            </li>
            <li className="pt-2 text-sm text-smoke">
              {SITE.hours.colombia}
              <br />
              {SITE.hours.florida}
            </li>
          </ul>
        </div>
      </div>
      <div className="relative border-t border-cream/10">
        <p className="mx-auto max-w-6xl px-5 py-5 text-sm text-smoke sm:px-8">
          © 2025 Brasaland. Todos los derechos reservados.
        </p>
      </div>
    </footer>
  );
}
