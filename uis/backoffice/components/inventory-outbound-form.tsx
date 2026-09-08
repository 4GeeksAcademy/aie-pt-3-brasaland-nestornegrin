"use client";

import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  type Ingredient,
  createOutboundOrder,
  getProduct,
  listProducts,
  readInventoryErrorDetails,
} from "@/lib/inventory";

const EMPTY = { ingredient_id: "", quantity: "", reason: "" };

export function InventoryOutboundForm() {
  const searchParams = useSearchParams();
  const [products, setProducts] = useState<Ingredient[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [form, setForm] = useState(EMPTY);
  const [currentStock, setCurrentStock] = useState<number | null>(null);
  const [stockError, setStockError] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [success, setSuccess] = useState(false);
  const [loading, setLoading] = useState(false);

  const loadProducts = useCallback(async () => {
    try {
      const response = await listProducts();
      if (!response.ok) {
        const details = await readInventoryErrorDetails(response, "No se pudieron cargar los insumos.");
        setLoadError(details.message);
        return;
      }
      setProducts(await response.json());
      const preselected = searchParams.get("ingredient_id");
      if (preselected) setForm((current) => ({ ...current, ingredient_id: preselected }));
    } catch {
      setLoadError("No se pudo conectar con el servidor.");
    }
  }, [searchParams]);

  useEffect(() => {
    void Promise.resolve().then(() => loadProducts());
  }, [loadProducts]);

  // Cuando cambia el insumo seleccionado, se obtiene su stock actual desde
  // la API (no el valor ya cargado en la lista) para reflejar el dato mas
  // reciente antes de que el usuario decida cuanto sacar.
  useEffect(() => {
    if (!form.ingredient_id) {
      setCurrentStock(null);
      return;
    }
    let active = true;
    setStockError(null);
    void getProduct(Number(form.ingredient_id))
      .then(async (response) => {
        if (!active) return;
        if (!response.ok) {
          const details = await readInventoryErrorDetails(response, "No se pudo consultar el stock de este insumo.");
          setStockError(details.message);
          setCurrentStock(null);
          return;
        }
        const product: Ingredient = await response.json();
        setCurrentStock(product.current_stock);
      })
      .catch(() => {
        if (active) setStockError("No se pudo consultar el stock de este insumo.");
      });
    return () => {
      active = false;
    };
  }, [form.ingredient_id]);

  function update(field: keyof typeof form, value: string) {
    setForm((current) => ({ ...current, [field]: value }));
    // Limpia un error de un envio anterior en cuanto el usuario vuelve a
    // tocar ese campo, para no mostrar un mensaje ya obsoleto.
    setErrors((current) => {
      if (!(field in current)) return current;
      const next = { ...current };
      delete next[field];
      return next;
    });
  }

  const quantityExceedsStock =
    currentStock !== null && form.quantity !== "" && Number(form.quantity) > currentStock;

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setErrors({});
    setSuccess(false);
    if (quantityExceedsStock) {
      setErrors({ quantity: `Solo hay ${currentStock} disponible. Reduce la cantidad antes de enviar.` });
      return;
    }
    setLoading(true);
    try {
      const response = await createOutboundOrder({
        ingredient_id: Number(form.ingredient_id),
        quantity: Number(form.quantity),
        reason: form.reason || undefined,
      });
      if (!response.ok) {
        const details = await readInventoryErrorDetails(response, "No se pudo registrar la salida. Intentalo de nuevo.");
        // El 400 de stock insuficiente se muestra junto al campo de cantidad.
        if (response.status === 400) {
          setErrors({ quantity: details.message });
        } else {
          setErrors(Object.keys(details.fields).length ? details.fields : { form: details.message });
        }
        return;
      }
      setForm(EMPTY);
      setCurrentStock(null);
      setSuccess(true);
    } catch {
      setErrors({ form: "No se pudo conectar con el servidor. Intentalo de nuevo en unos minutos." });
    } finally {
      setLoading(false);
    }
  }

  if (loadError) {
    return <p role="alert" className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800">{loadError}</p>;
  }

  return (
    <form onSubmit={submit} noValidate className="max-w-xl space-y-5 rounded-xl border border-zinc-200 bg-white p-6 shadow-sm">
      <div>
        <label htmlFor="ingredient_id" className="block text-sm font-bold">Insumo</label>
        <select
          id="ingredient_id"
          required
          value={form.ingredient_id}
          onChange={(event) => update("ingredient_id", event.target.value)}
          className="mt-2 w-full rounded-lg border border-zinc-300 px-3 py-2"
        >
          <option value="" disabled>Selecciona un insumo</option>
          {(products ?? []).map((product) => (
            <option key={product.id} value={product.id}>
              {product.name} - {product.restaurant}
            </option>
          ))}
        </select>

        {stockError ? <p className="mt-1 text-sm text-red-700">{stockError}</p> : null}
        {currentStock !== null ? (
          <p className="mt-2 rounded-lg bg-zinc-50 p-2 text-sm font-semibold text-zinc-700">
            Stock disponible: {currentStock}
          </p>
        ) : null}
      </div>

      <div>
        <label htmlFor="quantity" className="block text-sm font-bold">Cantidad</label>
        <input
          id="quantity"
          type="number"
          min="0.01"
          step="0.01"
          required
          value={form.quantity}
          onChange={(event) => update("quantity", event.target.value)}
          className="mt-2 w-full rounded-lg border border-zinc-300 px-3 py-2"
        />
        {quantityExceedsStock ? (
          <p className="mt-1 text-sm font-semibold text-amber-700">
            Advertencia: la cantidad supera el stock disponible ({currentStock}).
          </p>
        ) : null}
        {errors.quantity ? <p className="mt-1 text-sm text-red-700">{errors.quantity}</p> : null}
      </div>

      <div>
        <label htmlFor="reason" className="block text-sm font-bold">Motivo (opcional)</label>
        <input
          id="reason"
          type="text"
          placeholder="Uso en cocina, merma..."
          value={form.reason}
          onChange={(event) => update("reason", event.target.value)}
          className="mt-2 w-full rounded-lg border border-zinc-300 px-3 py-2"
        />
      </div>

      {errors.form ? <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm font-semibold text-red-800">{errors.form}</p> : null}
      {success ? <p role="status" className="rounded-lg bg-emerald-50 p-3 text-sm font-semibold text-emerald-800">Salida registrada correctamente.</p> : null}

      <button
        type="submit"
        disabled={loading}
        className="w-full rounded-lg bg-red-800 px-4 py-2 font-bold text-white hover:bg-red-900 disabled:opacity-60"
      >
        {loading ? "Registrando..." : "Registrar salida"}
      </button>
    </form>
  );
}
