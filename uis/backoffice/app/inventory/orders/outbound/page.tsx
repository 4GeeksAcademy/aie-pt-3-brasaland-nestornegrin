import { Suspense } from "react";
import { AuthGuard } from "@/components/auth-guard";
import { InventoryOutboundForm } from "@/components/inventory-outbound-form";

export default function InventoryOutboundPage() {
  return (
    <AuthGuard>
      <main>
        <p className="text-xs font-bold uppercase tracking-wide text-red-800">Inventario</p>
        <h1 className="mt-1 text-2xl font-black text-zinc-900 sm:text-3xl">Registrar orden de salida</h1>
        <div className="mt-8">
          <Suspense fallback={<p className="text-sm text-zinc-600">Cargando...</p>}>
            <InventoryOutboundForm />
          </Suspense>
        </div>
      </main>
    </AuthGuard>
  );
}
