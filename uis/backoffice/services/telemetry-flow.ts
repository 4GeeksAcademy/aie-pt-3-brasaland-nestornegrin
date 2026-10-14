/**
 * Seguimiento de flujos de formulario: flow_started / flow_completed / flow_abandoned.
 * La lógica vive aquí (sin React) para poder probarla; el hook `useFlowTracking`
 * (lib/use-flow-tracking.ts) solo la conecta al ciclo de vida del componente.
 */
import { flushWithBeacon, sessionAgeMinutes, track } from "@/services/telemetry";
import type { Section } from "@/services/telemetry-sections";

export type Flow =
  | "outbound_order" | "inbound_order" | "incident_report" | "csv_analysis"
  | "registration" | "password_reset" | "password_change";
export type ExitTrigger = "navigation_away" | "tab_closed" | "session_expired" | "idle_timeout";

export const IDLE_TIMEOUT_MS = 10 * 60_000;

function newId(): string {
  return typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
    ? crypto.randomUUID()
    : "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
        const r = (Math.random() * 16) | 0;
        return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
      });
}

let active: FlowTracker | null = null;

/** Flujo en curso (para `session_expired.flow` / `formDirty`). */
export function getActiveFlow(): { flow: Flow; dirty: boolean } | null {
  return active && active.started ? { flow: active.flow, dirty: true } : null;
}

/** Cierra como abandonado el flujo activo (p. ej. la sesión caducó). */
export function abandonActiveFlow(trigger: ExitTrigger): void {
  active?.abandon(trigger);
}

export class FlowTracker {
  started = false;
  private id = "";
  private startedAt = 0;
  private touched = new Set<string>();
  private attempts = 0;
  private rejected = false;
  private idleTimer: ReturnType<typeof setTimeout> | null = null;

  constructor(readonly flow: Flow, private readonly section: Section) {}

  /** Primera modificación de un campo = inicio del flujo (no al abrir la página). */
  touch(field: string): void {
    if (!this.started) {
      this.started = true;
      this.id = newId();
      this.startedAt = performance.now();
      // Registro del flujo en curso (lo consulta session_expired).
      // eslint-disable-next-line @typescript-eslint/no-this-alias
      active = this;
      track("flow_started", { flow: this.flow, flowInstanceId: this.id, section: this.section });
    }
    this.touched.add(field);
    this.armIdle();
  }

  /** Intento de envío. `ok = true` cierra el flujo como completado. */
  submitAttempt(ok: boolean): void {
    if (!this.started) this.touch("submit");
    this.attempts += 1;
    if (!ok) {
      this.rejected = true;
      this.armIdle();
      return;
    }
    track("flow_completed", {
      flow: this.flow,
      flowInstanceId: this.id,
      elapsedMs: this.elapsed(),
      submitAttempts: this.attempts,
    });
    this.reset();
  }

  /** El formulario salió sin completarse. No emite nada si nunca se modificó. */
  abandon(trigger: ExitTrigger): void {
    if (!this.started) return;
    track("flow_abandoned", {
      flow: this.flow,
      flowInstanceId: this.id,
      lastStep: this.rejected ? "submit_rejected" : "editing",
      fieldsTouchedCount: this.touched.size,
      elapsedMs: this.elapsed(),
      exitTrigger: trigger,
      hadSubmitError: this.rejected,
    });
    if (trigger === "tab_closed" || trigger === "session_expired") flushWithBeacon();
    this.reset();
  }

  dispose(): void {
    this.clearIdle();
    if (active === this) active = null;
  }

  private elapsed(): number {
    return Math.max(0, Math.round(performance.now() - this.startedAt));
  }

  private armIdle(): void {
    this.clearIdle();
    this.idleTimer = setTimeout(() => this.abandon("idle_timeout"), IDLE_TIMEOUT_MS);
  }

  private clearIdle(): void {
    if (this.idleTimer !== null) clearTimeout(this.idleTimer);
    this.idleTimer = null;
  }

  private reset(): void {
    this.clearIdle();
    this.started = false;
    this.touched.clear();
    this.attempts = 0;
    this.rejected = false;
    if (active === this) active = null;
  }
}

/** 401 en una petición autenticada: sesión caducada (justo antes de redirigir a /login). */
export function reportSessionExpired(section: Section): void {
  const flow = getActiveFlow();
  track("session_expired", {
    section,
    sessionAgeMinutes: sessionAgeMinutes(),
    formDirty: flow !== null,
    ...(flow ? { flow: flow.flow } : {}),
  });
  abandonActiveFlow("session_expired");
  flushWithBeacon(); // la página va a recargarse: no perder la cola
}
