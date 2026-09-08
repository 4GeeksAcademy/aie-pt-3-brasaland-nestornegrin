import { Suspense } from "react";
import { AuthGuard } from "@/components/auth-guard";
import { InventoryInboundForm } from "@/components/inventory-inbound-form";

export default function InventoryInboundPage() {
  return (
    <AuthGuard>
      <main>
        <p className="text-xs font-bold uppercase tracking-wide text-red-800">Inventario</p>
        <h1 className="mt-1 text-2xl font-black text-zinc-900 sm:text-3xl">Registrar orden de entrada</h1>
        <div className="mt-8">
          <Suspense fallback={<p className="text-sm text-zinc-600">Cargando...</p>}>
            <InventoryInboundForm />
          </Suspense>
        </div>
      </main>
    </AuthGuard>
  );
}
