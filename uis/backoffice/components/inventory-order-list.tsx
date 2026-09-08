"use client";

import { useCallback, useEffect, useState } from "react";
import { type InventoryOrder, listOrders, readInventoryErrorDetails } from "@/lib/inventory";

const TYPE_STYLES: Record<InventoryOrder["type"], { badge: string; label: string }> = {
  inbound: { badge: "bg-emerald-100 text-emerald-800 border-emerald-200", label: "Entrada" },
  outbound: { badge: "bg-red-100 text-red-800 border-red-200", label: "Salida" },
};

export function InventoryOrderList() {
  const [orders, setOrders] = useState<InventoryOrder[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await listOrders();
      if (!response.ok) {
        const details = await readInventoryErrorDetails(response, "No se pudieron cargar las ordenes.");
        setError(details.message);
        return;
      }
      setOrders(await response.json());
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
    return <p className="rounded-lg border border-zinc-200 bg-white p-4 text-sm text-zinc-600">Cargando ordenes...</p>;
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

  if (!orders || orders.length === 0) {
    return <p className="rounded-lg border border-zinc-200 bg-white p-4 text-sm text-zinc-600">Todavia no se han registrado ordenes.</p>;
  }

  return (
    <div className="overflow-x-auto rounded-xl border border-zinc-200 bg-white">
      <table className="w-full text-left text-sm">
        <thead className="border-b border-zinc-200 bg-zinc-50 text-xs font-bold uppercase tracking-wide text-zinc-500">
          <tr>
            <th className="px-4 py-3">Tipo</th>
            <th className="px-4 py-3">Insumo</th>
            <th className="px-4 py-3">Cantidad</th>
            <th className="px-4 py-3">Fecha</th>
            <th className="px-4 py-3">Creada por (user_uuid)</th>
          </tr>
        </thead>
        <tbody>
          {orders.map((order) => {
            const style = TYPE_STYLES[order.type];
            return (
              <tr key={`${order.type}-${order.id}`} className="border-b border-zinc-100 last:border-0">
                <td className="px-4 py-3">
                  <span className={`inline-block rounded-full border px-2 py-1 text-xs font-bold ${style.badge}`}>
                    {style.label}
                  </span>
                </td>
                <td className="px-4 py-3 font-semibold text-zinc-900">{order.ingredient_name}</td>
                <td className="px-4 py-3 text-zinc-700">{order.quantity}</td>
                <td className="px-4 py-3 text-zinc-700">{new Date(order.created_at).toLocaleString("es-CO")}</td>
                <td className="px-4 py-3 text-zinc-700">{order.user_uuid}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
