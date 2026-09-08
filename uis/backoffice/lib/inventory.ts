// Centraliza TODAS las llamadas a la API de inventario (/inventory).
// Ningun componente debe llamar a fetch directamente: siempre pasa por
// las funciones exportadas de este modulo.
//
// Vocabulario de dominio (ver CONTEXT.es.md, Hito 6): el equivalente a
// "producto" en Brasaland es un insumo de cocina (Ingredient), gestionado
// por restaurante. Las ordenes de entrada/salida son IngredientEntry /
// IngredientExit.

import { getAccessToken, readApiErrorDetails } from "./api-client";

const INVENTORY_API_URL =
  process.env.NEXT_PUBLIC_INVENTORY_API_URL ?? "http://localhost:8000";

function redirectToLogin(): void {
  if (typeof window === "undefined") return;
  if (window.location.pathname !== "/login") window.location.assign("/login");
}

async function inventoryFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  const token = getAccessToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(`${INVENTORY_API_URL}${path}`, { ...init, headers });
  if (response.status === 401) redirectToLogin();
  return response;
}

export { readApiErrorDetails as readInventoryErrorDetails };

// --- Tipos (deben reflejar exactamente services/api/app/inventory/schemas.py) ---

export type Ingredient = {
  id: number;
  name: string;
  sku: string;
  restaurant: string;
  current_stock: number;
};

export type IngredientCreate = {
  name: string;
  sku: string;
  restaurant: string;
};

export type InboundOrderPayload = {
  ingredient_id: number;
  quantity: number;
  supplier?: string;
};

export type OutboundOrderPayload = {
  ingredient_id: number;
  quantity: number;
  reason?: string;
};

export type InventoryOrder = {
  id: number;
  type: "inbound" | "outbound";
  ingredient_id: number;
  ingredient_name: string;
  quantity: number;
  created_at: string;
  user_uuid: number;
};

// --- Umbrales de nivel de stock ---
// Definidos para insumos de cocina medidos en kilogramos (ver seed de
// CONTEXT.es.md: los insumos sembrados van de 30 a 100 kg). Un insumo
// se considera:
//  - critico  (rojo)   si current_stock <= LOW_STOCK_THRESHOLD
//  - bajo     (ambar)  si current_stock <= HEALTHY_STOCK_THRESHOLD
//  - saludable (verde) en cualquier otro caso
export const LOW_STOCK_THRESHOLD = 10;
export const HEALTHY_STOCK_THRESHOLD = 30;

export function stockLevel(currentStock: number): "critical" | "low" | "healthy" {
  if (currentStock <= LOW_STOCK_THRESHOLD) return "critical";
  if (currentStock <= HEALTHY_STOCK_THRESHOLD) return "low";
  return "healthy";
}

// --- Llamadas a la API ---

export function listProducts(): Promise<Response> {
  return inventoryFetch("/inventory/products");
}

export function getProduct(id: number): Promise<Response> {
  return inventoryFetch(`/inventory/products/${id}`);
}

export function createProduct(payload: IngredientCreate): Promise<Response> {
  return inventoryFetch("/inventory/products", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function createInboundOrder(payload: InboundOrderPayload): Promise<Response> {
  return inventoryFetch("/inventory/orders/inbound", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function createOutboundOrder(payload: OutboundOrderPayload): Promise<Response> {
  return inventoryFetch("/inventory/orders/outbound", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function listOrders(): Promise<Response> {
  return inventoryFetch("/inventory/orders");
}
