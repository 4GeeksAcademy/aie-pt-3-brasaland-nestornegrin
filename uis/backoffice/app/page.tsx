import { BackofficeDashboard } from "@/components/backoffice-dashboard";
import { IncidentAnalysis } from "@/components/incident-analysis";
import { SupplierDirectory } from "@/components/supplier-directory";

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
      <div className="mt-12 border-t border-zinc-200 pt-10">
        <SupplierDirectory />
      </div>
      <section id="incidents" className="mt-12 border-t border-zinc-200 pt-10">
        <h2 className="text-2xl font-black text-zinc-900">Análisis de incidencias postventa</h2>
        <p className="mt-2 max-w-2xl text-sm text-zinc-600">
          Carga un CSV para validar sus registros y obtener el resumen operativo sin exponer datos de clientes.
        </p>
        <div className="mt-6">
          <IncidentAnalysis />
        </div>
      </section>
    </main>
  );
}
