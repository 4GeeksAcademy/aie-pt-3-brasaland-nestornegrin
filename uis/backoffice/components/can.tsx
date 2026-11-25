"use client";

import type { ReactNode } from "react";
import { can, useMe, type Capability } from "@/lib/access";

/** Muestra a sus hijos solo si el rol del usuario tiene la capacidad. El servidor sigue siendo la autoridad (403). */
export function Can({ capability, children, fallback = null }: { capability: Capability; children: ReactNode; fallback?: ReactNode }) {
  const { me } = useMe();
  return <>{can(me, capability) ? children : fallback}</>;
}
