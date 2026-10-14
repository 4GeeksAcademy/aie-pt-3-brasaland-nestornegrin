"use client";

import { useEffect, useState } from "react";
import { FlowTracker, type Flow } from "@/services/telemetry-flow";
import type { Section } from "@/services/telemetry-sections";

/**
 * Conecta un formulario con flow_started / flow_completed / flow_abandoned.
 *   const flow = useFlowTracking("incident_report", "incident_new");
 *   flow.touch("title");          // al modificar un campo
 *   flow.submitAttempt(ok);       // tras cada intento de envío
 */
export function useFlowTracking(flow: Flow, section: Section) {
  const [tracker] = useState(() => new FlowTracker(flow, section));

  useEffect(() => {
    const onPageHide = () => tracker.abandon("tab_closed");
    window.addEventListener("pagehide", onPageHide);
    return () => {
      window.removeEventListener("pagehide", onPageHide);
      tracker.abandon("navigation_away"); // el componente se desmonta: el usuario se fue
      tracker.dispose();
    };
  }, [tracker]);

  return tracker;
}
