import Link from "next/link";
import { AuthGuard } from "@/components/auth-guard";
import { IncidentListPanel } from "@/components/incident-list-panel";
import { IncidentSummaryPanel } from "@/components/incident-summary-panel";

export default function IncidentsPage() {
  return (
    <AuthGuard>
      <main>
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <p className="text-xs font-bold uppercase tracking-wide text-red-800">Gestor de incidencias</p>
            <h1 className="mt-1 text-2xl font-black text-zinc-900 sm:text-3xl">Panel de incidencias</h1>
          </div>
          <Link href="/incidents/new" className="rounded-lg bg-red-800 px-4 py-2 font-bold text-white hover:bg-red-900">
            Registrar incidencia
          </Link>
        </div>

        <section className="mt-8">
          <h2 className="text-lg font-black text-zinc-900">Resumen</h2>
          <div className="mt-4">
            <IncidentSummaryPanel />
          </div>
        </section>

        <section className="mt-10 border-t border-zinc-200 pt-8">
          <h2 className="text-lg font-black text-zinc-900">Incidencias registradas</h2>
          <div className="mt-4">
            <IncidentListPanel />
          </div>
        </section>
      </main>
    </AuthGuard>
  );
}
