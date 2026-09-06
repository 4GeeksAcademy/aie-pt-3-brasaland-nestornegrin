"use client";

import Link from "next/link";
import { useSyncExternalStore } from "react";
import { useRouter } from "next/navigation";
import { AUTH_CHANGE_EVENT, clearAccessToken, getAccessToken } from "@/lib/api-client";

export function SessionActions() {
  const router = useRouter();
  const authenticated = useSyncExternalStore(
    (onStoreChange) => {
      window.addEventListener("storage", onStoreChange);
      window.addEventListener(AUTH_CHANGE_EVENT, onStoreChange);
      return () => {
        window.removeEventListener("storage", onStoreChange);
        window.removeEventListener(AUTH_CHANGE_EVENT, onStoreChange);
      };
    },
    () => Boolean(getAccessToken()),
    () => false,
  );

  if (!authenticated) return <Link href="/login" className="font-bold text-red-800 hover:text-red-950">Iniciar sesión</Link>;

  return (
    <div className="flex items-center gap-3">
      <Link href="/account/profile" className="font-bold text-zinc-700 hover:text-red-800">Mi perfil</Link>
      <Link href="/account/change-password" className="font-bold text-zinc-700 hover:text-red-800">Cambiar contraseña</Link>
      <button type="button" onClick={() => { clearAccessToken(); router.push("/login"); }} className="font-bold text-red-800 hover:text-red-950">Cerrar sesión</button>
    </div>
  );
}