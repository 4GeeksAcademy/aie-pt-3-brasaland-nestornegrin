"use client";

import { useEffect, useState } from "react";
import { AUTH_CHANGE_EVENT, apiFetch } from "@/lib/api-client";

/** Acciones del eje de CAPACIDAD (rol). El servidor es quien decide; esto solo adapta la interfaz. */
export type Capability = "read" | "create" | "update" | "approve" | "delete" | "administer" | "cross_department";

export type Me = {
  email: string;
  role: string;
  role_id: number;
  role_label: string;
  rank: number;
  department: string | null;
  department_id: number | null;
  department_label: string | null;
  capabilities: Capability[];
};

/** ¿Tiene el usuario esta capacidad? Sin sesión cargada → no (se deshabilita por defecto, nunca se asume permiso). */
export function can(me: Me | null | undefined, capability: Capability): boolean {
  return Boolean(me && Array.isArray(me.capabilities) && me.capabilities.includes(capability));
}

/** Admin ve todos los departamentos: es una capacidad de rol, no un departamento vacío. */
export function seesAllDepartments(me: Me | null | undefined): boolean {
  return can(me, "cross_department");
}

let cached: Promise<Me | null> | null = null;

export function loadMe(): Promise<Me | null> {
  if (!cached) {
    cached = apiFetch("/auth/me")
      .then(async (response) => (response.ok ? ((await response.json()) as Me) : null))
      .catch(() => null);
  }
  return cached;
}

export function resetMeCache(): void {
  cached = null;
}

if (typeof window !== "undefined") window.addEventListener(AUTH_CHANGE_EVENT, resetMeCache); // login/logout → otro usuario

/** Rol, departamento y capacidades del usuario autenticado (`null` mientras carga o sin sesión). */
export function useMe(): { me: Me | null; loading: boolean } {
  const [state, setState] = useState<{ me: Me | null; loading: boolean }>({ me: null, loading: true });
  useEffect(() => {
    let active = true;
    void loadMe().then((me) => {
      if (active) setState({ me, loading: false });
    });
    return () => {
      active = false;
    };
  }, []);
  return state;
}
