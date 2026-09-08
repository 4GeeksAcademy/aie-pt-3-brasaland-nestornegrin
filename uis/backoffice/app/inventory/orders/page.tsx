import { AuthGuard } from "@/components/auth-guard";
import { InventoryOrderList } from "@/components/inventory-order-list";

export default function InventoryOrdersPage() {
  return (
    <AuthGuard>
      <main>
        <p className="text-xs font-bold uppercase tracking-wide text-red-800">Inventario</p>
        <h1 className="mt-1 text-2xl font-black text-zinc-900 sm:text-3xl">Historial de ordenes</h1>
        <div className="mt-8">
          <InventoryOrderList />
        </div>
      </main>
    </AuthGuard>
  );
}
