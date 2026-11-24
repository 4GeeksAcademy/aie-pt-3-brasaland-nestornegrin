import { AuditViewer } from "@/components/audit-viewer";
import { AuthGuard } from "@/components/auth-guard";

export default function AuditLogPage() {
  return (
    <AuthGuard>
      <main>
        <p className="text-xs font-bold uppercase tracking-wide text-red-800">Administración</p>
        <h1 className="mt-1 text-2xl font-black text-zinc-900 sm:text-3xl">Registro de auditoría</h1>
        <p className="mt-2 max-w-2xl text-sm text-zinc-600">
          Quién hizo qué, sobre qué recurso, cuándo y desde dónde. El registro es de <strong>solo lectura</strong>: ninguna entrada se puede modificar ni borrar.
        </p>
        <div className="mt-8"><AuditViewer /></div>
      </main>
    </AuthGuard>
  );
}
