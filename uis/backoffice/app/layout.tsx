import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Backoffice | Brasaland",
  description:
    "Panel interno de Brasaland para revisar registros de Brasa Points: filtros, orden, búsqueda y estadísticas.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="es">
      <body className="min-h-screen bg-zinc-50 text-zinc-900 antialiased">
        <header className="border-b border-zinc-200 bg-white">
          <div className="mx-auto flex w-full max-w-6xl items-center justify-between px-4 py-4 sm:px-6 lg:px-8">
            <span className="text-xl font-black tracking-tight text-red-800">
              Brasaland <span className="font-medium text-zinc-500">· Backoffice</span>
            </span>
            <nav aria-label="Secciones" className="flex items-center gap-4 text-xs font-semibold uppercase tracking-wide text-zinc-500">
              <a href="#incidents" className="hover:text-red-800">Incidencias</a>
              <span>Panel interno — Brasa Points</span>
            </nav>
          </div>
        </header>
        <div className="mx-auto w-full max-w-6xl px-4 py-8 sm:px-6 lg:px-8">{children}</div>
      </body>
    </html>
  );
}
