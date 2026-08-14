import { BackofficeDashboard } from "@/components/backoffice-dashboard";

export default function BackofficePage() {
  return (
    <main>
      <h1 className="text-2xl font-black text-zinc-900 sm:text-3xl">Registros Brasa Points</h1>
      <p className="mt-2 max-w-2xl text-sm text-zinc-600">
        Vista interna para el equipo de Brasaland. Los datos, el filtrado, el
        orden, la búsqueda, la validación y las estadísticas reutilizan las
        funciones del módulo TypeScript del Hito 2 (<code>../../../src</code>),
        no se reimplementan aquí.
      </p>
      <div className="mt-8">
        <BackofficeDashboard />
      </div>
    </main>
  );
}
