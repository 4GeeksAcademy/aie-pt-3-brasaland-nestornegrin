import { AuthGuard } from "@/components/auth-guard";
import { TelemetryReportView } from "@/components/telemetry-report-view";

export default function TelemetryReportPage() {
  return (
    <AuthGuard>
      <main>
        <p className="text-xs font-bold uppercase tracking-wide text-red-800">Ingeniería</p>
        <h1 className="mt-1 text-2xl font-black text-zinc-900 sm:text-3xl">Reporte técnico de telemetría</h1>
        <p className="mt-2 max-w-2xl text-sm text-zinc-600">
          Salud operacional del sistema (volumen, errores, latencia y autenticación). Vista técnica para ingeniería: no incluye métricas de negocio.
        </p>
        <div className="mt-8">
          <TelemetryReportView />
        </div>
      </main>
    </AuthGuard>
  );
}
