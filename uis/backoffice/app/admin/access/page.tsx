import { AccessAdmin } from "@/components/access-admin";
import { AuthGuard } from "@/components/auth-guard";

export default function AccessAdminPage() {
  return (
    <AuthGuard>
      <main>
        <p className="text-xs font-bold uppercase tracking-wide text-red-800">Administración</p>
        <h1 className="mt-1 text-2xl font-black text-zinc-900 sm:text-3xl">Roles, departamentos y asignaciones</h1>
        <p className="mt-2 max-w-2xl text-sm text-zinc-600">
          El <strong>rol</strong> define qué puede hacer una persona; el <strong>departamento</strong> define qué datos le competen. Se asignan por separado.
        </p>
        <div className="mt-8"><AccessAdmin /></div>
      </main>
    </AuthGuard>
  );
}
