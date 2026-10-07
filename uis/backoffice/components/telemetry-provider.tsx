"use client";

import { useEffect, useRef } from "react";
import { usePathname } from "next/navigation";
import { useReportWebVitals } from "next/web-vitals";
import { track } from "@/services/telemetry";
import { installGlobalErrorHandlers } from "@/services/telemetry-errors";
import { routeTemplate } from "@/services/telemetry-http";
import { sectionForPath, type Section } from "@/services/telemetry-sections";

const VITALS = ["LCP", "INP", "CLS", "FCP", "TTFB"] as const;
const NAV_TYPES = ["navigate", "reload", "back-forward", "prerender", "restore"] as const;
const SECTION_DEDUPE_MS = 30_000;

type EntryKind = "menu_click" | "direct_url" | "redirect" | "anchor_link" | "scroll_into_view";

// Última emisión por sección: misma sección dentro de 30 s no vuelve a emitirse.
const lastSectionView = new Map<Section, number>();

export function trackSectionView(section: Section, previous: Section | null, entryKind: EntryKind): void {
  const now = Date.now();
  const last = lastSectionView.get(section);
  if (last !== undefined && now - last < SECTION_DEDUPE_MS) return;
  lastSectionView.set(section, now);
  track("navigation_section_viewed", {
    section,
    entryKind,
    ...(previous ? { previousSection: previous } : {}),
  });
}

// Referencia estable: useReportWebVitals no debe recibir una función nueva en cada render.
function reportWebVital(metric: { name: string; value: number; rating?: string; navigationType?: string }): void {
  if (!(VITALS as readonly string[]).includes(metric.name)) return; // p. ej. métricas internas de Next.js
  const rating = metric.rating === "good" || metric.rating === "needs-improvement" || metric.rating === "poor" ? metric.rating : "good";
  const navigationType = (NAV_TYPES as readonly string[]).includes(metric.navigationType ?? "") ? metric.navigationType : "navigate";
  track("web_vital_measured", {
    metric: metric.name,
    value: Math.round(metric.value * 1000) / 1000,
    rating,
    routeTemplate: routeTemplate(window.location.pathname),
    navigationType,
  });
}

/**
 * Montado una vez en el layout raíz. Captura los eventos transversales:
 * errores no controlados, Web Vitals y vistas de sección.
 */
export function TelemetryProvider() {
  const pathname = usePathname();
  const previous = useRef<Section | null>(null);
  const first = useRef(true);

  useReportWebVitals(reportWebVital);

  useEffect(() => installGlobalErrorHandlers(), []);

  useEffect(() => {
    const section = sectionForPath(pathname);
    if (!section) return;
    const kind: EntryKind = first.current
      ? "direct_url"
      : previous.current === "login" || previous.current === "register" || previous.current === "reset_password"
        ? "redirect"
        : "menu_click";
    first.current = false;
    trackSectionView(section, previous.current, kind);
    previous.current = section;
  }, [pathname]);

  // Enlaces ancla de la home (#suppliers, #incidents).
  useEffect(() => {
    const onHash = () => {
      const anchor: Section | null = window.location.hash === "#suppliers" ? "suppliers" : window.location.hash === "#incidents" ? "incident_analysis" : null;
      if (!anchor) return;
      trackSectionView(anchor, previous.current, "anchor_link");
      previous.current = anchor;
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  return null;
}
