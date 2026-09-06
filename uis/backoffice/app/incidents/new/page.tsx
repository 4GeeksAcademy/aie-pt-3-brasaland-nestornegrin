import { AuthGuard } from "@/components/auth-guard";
import { IncidentForm } from "@/components/incident-form";

export default function NewIncidentPage() {
  return (
    <AuthGuard>
      <main className="mx-auto max-w-xl">
        <p className="text-xs font-bold uppercase tracking-wide text-red-800">Gestor de incidencias</p>
        <h1 className="mt-1 text-2xl font-black text-zinc-900 sm:text-3xl">Registrar incidencia</h1>
        <p className="mt-2 text-sm text-zinc-600">
          Cualquier persona del equipo puede registrar una incidencia desde aquí, esté en una sede, en central, o
          gestionando el reporte de un cliente.
        </p>
        <div className="mt-6">
          <IncidentForm />
        </div>
      </main>
    </AuthGuard>
  );
}
