export function SiteFooter() {
  return (
    <footer className="border-t border-zinc-200 bg-white" role="contentinfo">
      <div className="mx-auto flex max-w-6xl flex-col gap-3 px-4 py-6 text-sm text-zinc-600 sm:flex-row sm:items-center sm:justify-between sm:px-6 lg:px-8">
        <p>© 2025 Brasaland. Todos los derechos reservados.</p>
        <nav aria-label="Redes sociales" className="flex gap-4 font-semibold">
          <a
            href="https://instagram.com/brasaland"
            className="hover:text-red-700 focus:outline-none focus:ring-2 focus:ring-red-700"
          >
            Instagram
          </a>
          <a
            href="https://facebook.com/brasaland"
            className="hover:text-red-700 focus:outline-none focus:ring-2 focus:ring-red-700"
          >
            Facebook
          </a>
        </nav>
      </div>
    </footer>
  );
}
