"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetch, getAccessToken } from "@/lib/api-client";

export function AuthGuard({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [authorized, setAuthorized] = useState(false);

  useEffect(() => {
    let active = true;
    if (!getAccessToken()) {
      router.replace("/login");
      return () => { active = false; };
    }

    void apiFetch("/auth/me").then((response) => {
      if (active && response.ok) setAuthorized(true);
    });
    return () => { active = false; };
  }, [router]);

  if (!authorized) {
    return <p className="rounded-xl border border-zinc-200 bg-white p-6 text-sm text-zinc-600">Comprobando sesión...</p>;
  }
  return <>{children}</>;
}