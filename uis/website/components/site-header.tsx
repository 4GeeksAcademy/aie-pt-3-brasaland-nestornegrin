import Link from "next/link";

const navLinks = [
  { href: "#inicio", label: "Inicio" },
  { href: "#ubicaciones", label: "Ubicaciones" },
  { href: "#menu", label: "Menú" },
  { href: "#brasa-points", label: "Brasa Points" },
  { href: "#contacto", label: "Contacto" },
];

export function SiteHeader() {
  return (
    <header
      className="sticky top-0 z-50 border-b border-amber-200 bg-white/95 backdrop-blur"
      role="banner"
    >
      <div className="mx-auto flex w-full max-w-6xl items-center justify-between px-4 py-4 sm:px-6 lg:px-8">
        <Link
          href="#inicio"
          className="text-2xl font-black tracking-tight text-red-800"
          aria-label="Ir al inicio de Brasaland"
        >
          Brasaland
        </Link>
        <nav aria-label="Navegación principal">
          <ul className="hidden items-center gap-6 text-sm font-semibold md:flex">
            {navLinks.map((link) => (
              <li key={link.href}>
                <Link
                  href={link.href}
                  className="hover:text-red-700 focus:outline-none focus:ring-2 focus:ring-red-700"
                >
                  {link.label}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
        <Link
          href="/brasa-points"
          className="rounded-full bg-red-700 px-4 py-2 text-sm font-bold text-white transition hover:bg-red-800 focus:outline-none focus:ring-2 focus:ring-red-800"
          aria-label="Ir al formulario para unirte a Brasa Points"
        >
          Únete
        </Link>
      </div>
    </header>
  );
}
