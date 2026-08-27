"use client";

import { useEffect, useState } from "react";

type Supplier = {
  id: number;
  name: string;
  categories: string[];
  country: string;
  rate: number;
  status: "Activo" | "Suspendido";
  updated_at: string;
};

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export function SupplierDirectory() {
  const [suppliers, setSuppliers] = useState<Supplier[]>([]);
  const [country, setCountry] = useState("all");
  const [category, setCategory] = useState("all");
  const [rates, setRates] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [newSupplier, setNewSupplier] = useState({ name: "", categories: "Carnes", country: "Colombia", rate: "", status: "Activo" as Supplier["status"] });

  useEffect(() => {
    void loadSuppliers();
  }, [country, category]);

  async function loadSuppliers() {
    setLoading(true);
    setError(null);
    const params = new URLSearchParams();
    if (country !== "all") params.set("country", country);
    if (category !== "all") params.set("category", category);
    try {
      const response = await fetch(`${API_URL}/api/suppliers?${params.toString()}`);
      const payload = (await response.json()) as Supplier[] | { detail?: string };
      if (!response.ok) throw new Error("detail" in payload ? payload.detail : "No se pudo cargar el directorio");
      setSuppliers(payload as Supplier[]);
      setRates(Object.fromEntries((payload as Supplier[]).map((supplier) => [supplier.id, String(supplier.rate)])));
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "No se pudo conectar con la API");
    } finally {
      setLoading(false);
    }
  }

  async function updateRate(supplierId: string) {
    const currentRate = Number(rates[supplierId]);
    if (!Number.isFinite(currentRate) || currentRate <= 0) {
      setError("La tarifa debe ser un número mayor que cero.");
      return;
    }
    setSaving(supplierId);
    setError(null);
    try {
      const response = await fetch(`${API_URL}/api/suppliers/${supplierId}/rate`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ current_rate: currentRate }),
      });
      const payload = (await response.json()) as Supplier | { detail?: string };
      if (!response.ok) throw new Error("detail" in payload ? payload.detail : "No se pudo actualizar la tarifa");
      setSuppliers((current) => current.map((supplier) => supplier.id === Number(supplierId) ? payload as Supplier : supplier));
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "No se pudo conectar con la API");
    } finally {
      setSaving(null);
    }
  }

  async function updateStatus(supplier: Supplier) {
    const status = supplier.status === "Activo" ? "Suspendido" : "Activo";
    const response = await fetch(`${API_URL}/api/suppliers/${supplier.id}/status`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status }) });
    if (!response.ok) { setError("No se pudo actualizar el estado."); return; }
    const updated = (await response.json()) as Supplier;
    setSuppliers((current) => current.map((item) => item.id === supplier.id ? updated : item));
  }

  async function createSupplier(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    const response = await fetch(`${API_URL}/api/suppliers`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...newSupplier, rate: Number(newSupplier.rate), categories: [newSupplier.categories] }) });
    const payload = (await response.json()) as Supplier | { detail?: string };
    if (!response.ok) { setError("detail" in payload && typeof payload.detail === "string" ? payload.detail : "La API rechazó el proveedor."); return; }
    setSuppliers((current) => [...current, payload as Supplier]);
    setNewSupplier({ name: "", categories: "Carnes", country: "Colombia", rate: "", status: "Activo" });
  }

  return (
    <section id="suppliers" aria-labelledby="suppliers-title" className="rounded-xl border border-zinc-200 bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-xs font-bold uppercase tracking-wide text-red-800">Fuente única de verdad</p>
          <h2 id="suppliers-title" className="mt-1 text-2xl font-black text-zinc-900">Directorio de proveedores</h2>
          <p className="mt-2 max-w-xl text-sm text-zinc-600">Tarifas vigentes, cobertura y estado operativo centralizados en la API.</p>
        </div>
        <div className="flex flex-wrap gap-3 text-sm">
          <label className="flex items-center gap-2 text-zinc-700">País
            <select value={country} onChange={(event) => setCountry(event.target.value)} className="rounded-lg border border-zinc-300 px-2 py-2">
              <option value="all">Todos</option><option>Colombia</option><option>Estados Unidos</option>
            </select>
          </label>
          <label className="flex items-center gap-2 text-zinc-700">Categoría
            <select value={category} onChange={(event) => setCategory(event.target.value)} className="rounded-lg border border-zinc-300 px-2 py-2">
              <option value="all">Todas</option><option>Carnes</option><option>Vegetales</option><option>Lácteos</option><option>Bebidas</option><option>Empaques</option>
            </select>
          </label>
        </div>
      </div>
      {error ? <p role="alert" className="mt-4 rounded-lg bg-red-50 p-3 text-sm font-semibold text-red-800">{error}</p> : null}
      <form onSubmit={createSupplier} className="mt-5 grid gap-3 border-t border-zinc-100 pt-5 sm:grid-cols-5">
        <input required value={newSupplier.name} onChange={(event) => setNewSupplier({ ...newSupplier, name: event.target.value })} placeholder="Nombre del proveedor" className="rounded-lg border border-zinc-300 px-3 py-2 text-sm" />
        <select value={newSupplier.categories} onChange={(event) => setNewSupplier({ ...newSupplier, categories: event.target.value })} className="rounded-lg border border-zinc-300 px-3 py-2 text-sm"><option>Carnes</option><option>Vegetales</option><option>Lácteos</option><option>Bebidas</option><option>Empaques</option></select>
        <select value={newSupplier.country} onChange={(event) => setNewSupplier({ ...newSupplier, country: event.target.value })} className="rounded-lg border border-zinc-300 px-3 py-2 text-sm"><option>Colombia</option><option>Estados Unidos</option></select>
        <input required min="0.01" step="0.01" type="number" value={newSupplier.rate} onChange={(event) => setNewSupplier({ ...newSupplier, rate: event.target.value })} placeholder="Tarifa" className="rounded-lg border border-zinc-300 px-3 py-2 text-sm" />
        <button type="submit" className="rounded-lg bg-red-800 px-4 py-2 text-sm font-bold text-white hover:bg-red-900">Añadir proveedor</button>
      </form>
      {loading ? <p className="mt-6 text-sm text-zinc-500">Cargando proveedores...</p> : null}
      {!loading && !error && suppliers.length === 0 ? <p className="mt-6 text-sm text-zinc-500">No hay proveedores para estos filtros.</p> : null}
      {!loading && suppliers.length > 0 ? (
        <div className="mt-6 overflow-x-auto">
          <table className="w-full min-w-[760px] text-left text-sm">
            <thead><tr className="border-b border-zinc-200 text-xs uppercase tracking-wide text-zinc-500"><th className="pb-3 pr-4">Proveedor</th><th className="pb-3 pr-4">Categoría</th><th className="pb-3 pr-4">País</th><th className="pb-3 pr-4">Estado</th><th className="pb-3 pr-4">Tarifa vigente</th><th className="pb-3">Último cambio</th></tr></thead>
            <tbody>{suppliers.map((supplier) => <tr key={supplier.id} className="border-b border-zinc-100 text-zinc-800">
              <td className="py-3 pr-4"><span className="font-semibold">{supplier.name}</span><span className="block text-xs text-zinc-500">ID {supplier.id}</span></td>
              <td className="py-3 pr-4">{supplier.categories.join(", ")}</td><td className="py-3 pr-4">{supplier.country}</td>
              <td className="py-3 pr-4"><button type="button" onClick={() => void updateStatus(supplier)} className={supplier.status === "Activo" ? "font-semibold text-emerald-700" : "font-semibold text-amber-700"}>{supplier.status}</button></td>
              <td className="py-3 pr-4"><div className="flex items-center gap-2"><input aria-label={`Tarifa de ${supplier.name}`} type="number" min="0.01" step="0.01" value={rates[supplier.id] ?? ""} onChange={(event) => setRates((current) => ({ ...current, [supplier.id]: event.target.value }))} className="w-24 rounded-lg border border-zinc-300 px-2 py-1" /><button type="button" onClick={() => void updateRate(String(supplier.id))} disabled={saving === String(supplier.id)} className="rounded-lg bg-zinc-900 px-3 py-1 text-xs font-bold text-white hover:bg-red-800 disabled:opacity-50">{saving === String(supplier.id) ? "..." : "Guardar"}</button></div></td>
              <td className="py-3 text-xs text-zinc-500">{new Date(supplier.updated_at).toLocaleString("es-CO")}</td>
            </tr>)}</tbody>
          </table>
        </div>
      ) : null}
    </section>
  );
}