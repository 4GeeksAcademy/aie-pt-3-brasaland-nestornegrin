"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import {
  type Ingredient,
  listProducts,
  readInventoryErrorDetails,
  stockLevel,
} from "@/lib/inventory";

const LEVEL_STYLES: Record<string, { badge: string; label: string; row: string }> = {
  critical: { badge: "bg-red-100 text-red-800 border-red-200", label: "Stock critico", row: "" },
  low: { badge: "bg-amber-100 text-amber-800 border-amber-200", label: "Stock bajo", row: "" },
  healthy: { badge: "bg-emerald-100 text-emerald-800 border-emerald-200", label: "Saludable", row: "" },
};

export function InventoryProductList() {
  const [products, setProducts] = useState<Ingredient[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    await Promise.resolve();
    setLoading(true);
    setError(null);
    try {
      const response = await listProducts();
      if (!response.ok) {
        const details = await readInventoryErrorDetails(response, "No se pudieron cargar los insumos.");
        setError(details.message);
        return;
      }
      setProducts(await response.json());
    } catch {
      setError("No se pudo conectar con el servidor.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void Promise.resolve().then(() => load());
  }, [load]);

  if (loading) {
    return <p className="rounded-lg border border-zinc-200 bg-white p-4 text-sm text-zinc-600">Cargando insumos...</p>;
  }

  if (error) {
    return (
      <div role="alert" className="rounded-xl border border-red-200 bg-red-50 p-6 text-sm text-red-800">
        <p className="font-semibold">{error}</p>
        <button type="button" onClick={() => void load()} className="mt-3 font-bold underline">
          Reintentar
        </button>
      </div>
    );
  }

  if (!products || products.length === 0) {
    return <p className="rounded-lg border border-zinc-200 bg-white p-4 text-sm text-zinc-600">No hay insumos registrados todavia.</p>;
  }

  return (
    <div className="overflow-x-auto rounded-xl border border-zinc-200 bg-white">
      <table className="w-full text-left text-sm">
        <thead className="border-b border-zinc-200 bg-zinc-50 text-xs font-bold uppercase tracking-wide text-zinc-500">
          <tr>
            <th className="px-4 py-3">Insumo</th>
            <th className="px-4 py-3">SKU</th>
            <th className="px-4 py-3">Restaurante</th>
            <th className="px-4 py-3">Stock actual</th>
            <th className="px-4 py-3">Nivel</th>
            <th className="px-4 py-3">Acciones</th>
          </tr>
        </thead>
        <tbody>
          {products.map((product) => {
            const level = stockLevel(product.current_stock);
            const style = LEVEL_STYLES[level];
            return (
              <tr key={product.id} className="border-b border-zinc-100 align-top last:border-0">
                <td className="px-4 py-3 font-semibold text-zinc-900">{product.name}</td>
                <td className="px-4 py-3 text-zinc-700">{product.sku}</td>
                <td className="px-4 py-3 text-zinc-700">{product.restaurant}</td>
                <td className="px-4 py-3 font-bold text-zinc-900">{product.current_stock}</td>
                <td className="px-4 py-3">
                  <span className={`inline-block rounded-full border px-2 py-1 text-xs font-bold ${style.badge}`}>
                    {style.label}
                  </span>
                </td>
                <td className="px-4 py-3">
                  <div className="flex flex-wrap gap-3 text-xs font-bold uppercase tracking-wide">
                    <Link href={`/inventory/orders/inbound?ingredient_id=${product.id}`} className="text-red-800 hover:text-red-900">
                      Registrar entrada
                    </Link>
                    <Link href={`/inventory/orders/outbound?ingredient_id=${product.id}`} className="text-red-800 hover:text-red-900">
                      Registrar salida
                    </Link>
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
