import { AuthGuard } from "@/components/auth-guard";
import { InventoryProductList } from "@/components/inventory-product-list";

export default function InventoryProductsPage() {
  return (
    <AuthGuard>
      <main>
        <p className="text-xs font-bold uppercase tracking-wide text-red-800">Inventario</p>
        <h1 className="mt-1 text-2xl font-black text-zinc-900 sm:text-3xl">Insumos y stock actual</h1>
        <div className="mt-8">
          <InventoryProductList />
        </div>
      </main>
    </AuthGuard>
  );
}
