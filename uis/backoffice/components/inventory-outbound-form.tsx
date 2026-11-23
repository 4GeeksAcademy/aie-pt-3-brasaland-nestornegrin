"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  type Ingredient,
  createOutboundOrder,
  getProduct,
  HEALTHY_STOCK_THRESHOLD,
  LOW_STOCK_THRESHOLD,
  listProducts,
  readInventoryErrorDetails,
  stockLevel,
} from "@/lib/inventory";
import { useFlowTracking } from "@/lib/use-flow-tracking";
import { track } from "@/services/telemetry";

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
  // Telemetría: flujo "outbound_order" y aviso de sobregiro (una vez por transición).
  const flow = useFlowTracking("outbound_order", "inventory_outbound");
  const overdrawWarned = useRef(false);

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
    flow.touch(field);
    setForm((current) => ({ ...current, [field]: value }));
    if (field === "quantity") {
      const exceeds = currentStock !== null && value !== "" && Number(value) > currentStock;
      if (exceeds && !overdrawWarned.current && form.ingredient_id) {
        track("outbound_overdraw_warning_shown", {
          ingredientId: Number(form.ingredient_id),
          requestedQuantity: Number(value),
          availableStock: currentStock,
          trigger: "typing",
        });
      }
      overdrawWarned.current = exceeds;
    }
    // Limpia un error de un envio anterior en cuanto el usuario vuelve a
    // tocar ese campo, para no mostrar un mensaje ya obsoleto.
    setErrors((current) => {
      if (!(field in current)) return current;
      const next = { ...current };
      delete next[field];
      return next;
    });
  }

  const selectedProduct = (products ?? []).find((product) => String(product.id) === form.ingredient_id);

  const quantityExceedsStock =
    currentStock !== null && form.quantity !== "" && Number(form.quantity) > currentStock;

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setErrors({});
    setSuccess(false);
    if (quantityExceedsStock) {
      track("outbound_overdraw_warning_shown", {
        ingredientId: Number(form.ingredient_id),
        requestedQuantity: Number(form.quantity),
        availableStock: currentStock,
        trigger: "submit_blocked",
      });
      flow.submitAttempt(false);
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
        flow.submitAttempt(false);
        // Telemetría (`inventory_validation_failed`): lo rechazó el servidor.
        if (response.status === 400 || response.status === 404) {
          track("inventory_validation_failed", {
            operation: "outbound_order",
            errorCode:
              response.status === 404 ? "ingredient_not_found" : Object.keys(details.fields).length ? "invalid_payload" : "insufficient_stock",
            httpStatus: response.status,
            ingredientId: Number(form.ingredient_id),
            restaurant: selectedProduct?.restaurant,
            requestedQuantity: Number(form.quantity),
            ...(currentStock !== null ? { availableStock: currentStock } : {}),
          });
        }
        // El 400 de stock insuficiente se muestra junto al campo de cantidad.
        if (response.status === 400) {
          setErrors({ quantity: details.message });
        } else {
          setErrors(Object.keys(details.fields).length ? details.fields : { form: details.message });
        }
        return;
      }
      // Telemetría: orden creada (+ umbral de stock cruzado, si lo hubo).
      const created = (await response.json()) as { id: number };
      const quantity = Number(form.quantity);
      const stockBefore = currentStock ?? 0;
      const stockAfter = Math.round((stockBefore - quantity) * 100) / 100;
      track("outbound_order_created", {
        exitId: created.id,
        ingredientId: Number(form.ingredient_id),
        restaurant: selectedProduct?.restaurant ?? "unknown",
        quantity,
        stockBefore,
        stockAfter,
        reasonProvided: form.reason.trim() !== "",
      });
      const before = stockLevel(stockBefore);
      const after = stockLevel(stockAfter);
      if (after !== "healthy" && after !== before) {
        track("stock_threshold_triggered", {
          ingredientId: Number(form.ingredient_id),
          restaurant: selectedProduct?.restaurant ?? "unknown",
          level: after === "critical" ? "critical" : "low",
          thresholdValue: after === "critical" ? LOW_STOCK_THRESHOLD : HEALTHY_STOCK_THRESHOLD,
          stockBefore,
          stockAfter,
          triggeringExitId: created.id,
        });
      }
      flow.submitAttempt(true);
      overdrawWarned.current = false;
      setForm(EMPTY);
      setCurrentStock(null);
      setSuccess(true);
    } catch {
      flow.submitAttempt(false);
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
