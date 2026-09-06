"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetch, getAccessToken } from "@/lib/api-client";

export function AuthGuard({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [authorized, setAuthorized] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    if (!getAccessToken()) {
      router.replace("/login");
      return () => {
        active = false;
      };
    }

    void apiFetch("/auth/me")
      .then((response) => {
        if (!active) return;
        if (response.ok) {
          setAuthorized(true);
          return;
        }
        // apiFetch ya redirige a /login en un 401; cualquier otro código
        // (500, etc.) llega aquí y necesita su propia salida clara.
        if (response.status !== 401) {
          setError("No se pudo comprobar tu sesión. Puede que el servidor no esté disponible.");
        }
      })
      .catch(() => {
        if (active) setError("No se pudo conectar con el servidor. Comprueba tu conexión e inténtalo de nuevo.");
      });
    return () => {
      active = false;
    };
  }, [router]);

  if (error) {
    return (
      <div role="alert" className="rounded-xl border border-red-200 bg-red-50 p-6 text-sm text-red-800">
        <p className="font-semibold">{error}</p>
        <div className="mt-3 flex gap-4">
          <button type="button" onClick={() => window.location.reload()} className="font-bold underline">
            Reintentar
          </button>
          <button type="button" onClick={() => router.push("/login")} className="font-bold underline">
            Ir a iniciar sesión
          </button>
        </div>
      </div>
    );
  }

  if (!authorized) {
    return <p className="rounded-xl border border-zinc-200 bg-white p-6 text-sm text-zinc-600">Comprobando sesión...</p>;
  }
  return <>{children}</>;
}