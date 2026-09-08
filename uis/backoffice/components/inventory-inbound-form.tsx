"use client";

import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  type Ingredient,
  createInboundOrder,
  listProducts,
  readInventoryErrorDetails,
} from "@/lib/inventory";

const EMPTY = { ingredient_id: "", quantity: "", supplier: "" };

export function InventoryInboundForm() {
  const searchParams = useSearchParams();
  const [products, setProducts] = useState<Ingredient[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [form, setForm] = useState(EMPTY);
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
      const data: Ingredient[] = await response.json();
      setProducts(data);
      const preselected = searchParams.get("ingredient_id");
      if (preselected) setForm((current) => ({ ...current, ingredient_id: preselected }));
    } catch {
      setLoadError("No se pudo conectar con el servidor.");
    }
  }, [searchParams]);

  useEffect(() => {
    void Promise.resolve().then(() => loadProducts());
  }, [loadProducts]);

  function update(field: keyof typeof form, value: string) {
    setForm((current) => ({ ...current, [field]: value }));
    setErrors((current) => {
      if (!(field in current)) return current;
      const next = { ...current };
      delete next[field];
      return next;
    });
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setErrors({});
    setSuccess(false);
    setLoading(true);
    try {
      const response = await createInboundOrder({
        ingredient_id: Number(form.ingredient_id),
        quantity: Number(form.quantity),
        supplier: form.supplier || undefined,
      });
      if (!response.ok) {
        const details = await readInventoryErrorDetails(response, "No se pudo registrar la entrada. Intentalo de nuevo.");
        setErrors(Object.keys(details.fields).length ? details.fields : { form: details.message });
        return;
      }
      setForm(EMPTY);
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
        {errors.ingredient_id ? <p className="mt-1 text-sm text-red-700">{errors.ingredient_id}</p> : null}
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
        {errors.quantity ? <p className="mt-1 text-sm text-red-700">{errors.quantity}</p> : null}
      </div>

      <div>
        <label htmlFor="supplier" className="block text-sm font-bold">Proveedor (opcional)</label>
        <input
          id="supplier"
          type="text"
          value={form.supplier}
          onChange={(event) => update("supplier", event.target.value)}
          className="mt-2 w-full rounded-lg border border-zinc-300 px-3 py-2"
        />
      </div>

      {errors.form ? <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm font-semibold text-red-800">{errors.form}</p> : null}
      {success ? <p role="status" className="rounded-lg bg-emerald-50 p-3 text-sm font-semibold text-emerald-800">Entrada registrada correctamente.</p> : null}

      <button
        type="submit"
        disabled={loading}
        className="w-full rounded-lg bg-red-800 px-4 py-2 font-bold text-white hover:bg-red-900 disabled:opacity-60"
      >
        {loading ? "Registrando..." : "Registrar entrada"}
      </button>
    </form>
  );
}
