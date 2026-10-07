"use client";

import dynamic from "next/dynamic";
import { DeferUntilVisible } from "./defer-until-visible";

// Secciones de la home del backoffice que están por debajo del pliegue y solo
// se necesitan al llegar a ellas (el directorio) o al subir un CSV (el
// análisis). Se cargan con next/dynamic desde un Client Component: según la
// documentación de Next, importar dinámicamente desde un Server Component no
// divide el bundle. El motivo de cada una está en CACHING_REPORT.md.
const SupplierDirectory = dynamic(() => import("./supplier-directory").then((module) => module.SupplierDirectory), {
  loading: () => <p className="text-sm text-zinc-500">Cargando directorio de proveedores...</p>,
});

const IncidentAnalysis = dynamic(() => import("./incident-analysis").then((module) => module.IncidentAnalysis), {
  loading: () => <p className="text-sm text-zinc-500">Cargando análisis de incidencias...</p>,
});

export function LazySupplierDirectory() {
  // El id vive aquí y no en <SupplierDirectory>: el enlace "#suppliers" del
  // menú debe encontrar el ancla antes de que el directorio se haya cargado.
  return (
    <DeferUntilVisible id="suppliers" minHeight={480} label="Directorio de proveedores">
      <SupplierDirectory />
    </DeferUntilVisible>
  );
}

export function LazyIncidentAnalysis() {
  return (
    <DeferUntilVisible minHeight={320} label="Análisis de incidencias">
      <IncidentAnalysis />
    </DeferUntilVisible>
  );
}
