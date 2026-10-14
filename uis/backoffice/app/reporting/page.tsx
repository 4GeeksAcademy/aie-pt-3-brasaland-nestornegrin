import { AuthGuard } from "@/components/auth-guard";
import { InventoryPerformanceDashboard } from "@/components/inventory-performance-dashboard";

export default function InventoryPerformancePage() {
  return (
    <AuthGuard>
      <main>
        <p className="text-xs font-bold uppercase tracking-wide text-red-800">Operaciones y dirección</p>
        <h1 className="mt-1 text-2xl font-black text-zinc-900 sm:text-3xl">Desempeño de inventario por restaurante</h1>
        <p className="mt-2 max-w-2xl text-sm text-zinc-600">
          Cómo se mueve el inventario en cada uno de los 14 restaurantes de Brasaland: cuánto sale, cuánto se pierde como merma, dónde se
          está acabando el stock y con qué frecuencia el sistema rechaza una salida. Se actualiza cada día a las 10:00 UTC.
        </p>
        <div className="mt-8">
          <InventoryPerformanceDashboard />
        </div>
      </main>
    </AuthGuard>
  );
}
