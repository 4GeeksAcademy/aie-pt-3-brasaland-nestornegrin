/** @jest-environment jsdom */
/**
 * Contrato: cada evento que emite el frontend debe validar contra
 * docs/telemetry/event-schemas.json (envelope + allowlist de propiedades).
 */
import fs from "fs";
import path from "path";
import Ajv from "ajv";
import { __resetTelemetryForTests, flush, startTelemetrySession, track } from "@/services/telemetry";
import { EVENT_ALLOWLISTS } from "@/services/telemetry-schema";

const schema = JSON.parse(fs.readFileSync(path.join(__dirname, "../../../docs/telemetry/event-schemas.json"), "utf-8"));
const ajv = new Ajv({ strict: false, allErrors: true });
const validate = ajv.compile(schema);

const UUID = "7c9e6679-7425-40de-944b-e07fc1f90ae7";
const RESTAURANT = "Brasaland El Poblado";

// Una muestra por cada forma en que el código emite el evento.
const SAMPLES: Array<[string, Record<string, unknown>]> = [
  ["outbound_order_created", { exitId: 9, ingredientId: 3, restaurant: RESTAURANT, quantity: 2.5, stockBefore: 20, stockAfter: 17.5, reasonProvided: false }],
  ["inventory_validation_failed", { operation: "outbound_order", errorCode: "insufficient_stock", httpStatus: 400, ingredientId: 3, restaurant: RESTAURANT, requestedQuantity: 50, availableStock: 20 }],
  ["inventory_validation_failed", { operation: "outbound_order", errorCode: "ingredient_not_found", httpStatus: 404, ingredientId: 3, requestedQuantity: 1 }],
  ["stock_threshold_triggered", { ingredientId: 3, restaurant: RESTAURANT, level: "low", thresholdValue: 30, stockBefore: 35, stockAfter: 28, triggeringExitId: 9 }],
  ["direct_stock_edit_rejected", { attemptKind: "unsupported_method", httpMethod: "PUT", routeTemplate: "/inventory/products/{ingredient_id}", httpStatus: 405 }],
  ["direct_stock_edit_rejected", { attemptKind: "extra_field_on_create", httpMethod: "POST", routeTemplate: "/inventory/products", httpStatus: 400, offendingFields: ["current_stock"] }],
  ["login_failed", { failureReason: "invalid_credentials" }],
  ["login_failed", { failureReason: "network_error" }],
  ["login_failed", { failureReason: "server_error" }],
  ["login_succeeded", { tokenTtlMinutes: 30 }],
  ["session_expired", { section: "inventory_outbound", sessionAgeMinutes: 31.2, formDirty: true, flow: "outbound_order" }],
  ["incident_created", { incidentId: 4, category: "Queja", origin: "branch", branch: RESTAURANT }],
  ["incident_status_changed", { incidentId: 4, fromStatus: "open", toStatus: "in_progress", category: "Queja", ageHours: 3.5 }],
  ["incident_csv_analyzed", { outcome: "analyzed", fileSizeBytes: 1024, totalRows: 100, invalidRows: 3, durationMs: 250 }],
  ["incident_csv_analyzed", { outcome: "rejected_extension", fileSizeBytes: 12, durationMs: 40 }],
  ["incident_list_filtered", { filtersApplied: ["status", "branch"], resultCount: 7 }],
  ["user_registered", { registrationOutcome: "created", hasPhone: true, hasAddress: false }],
  ["api_latency_recorded", { method: "GET", routeTemplate: "/api/incidents/{id}/status", statusClass: "2xx", durationMs: 812, sampleRate: 1 }],
  ["api_latency_recorded", { method: "GET", routeTemplate: "/api/incidents", statusClass: "2xx", durationMs: 40, sampleRate: 0.05, cache: "hit", responseBytes: 2048 }],
  ["web_vital_measured", { metric: "LCP", value: 1234.5, rating: "good", routeTemplate: "/", navigationType: "navigate" }],
  ["frontend_error_captured", { errorSource: "window_error", errorName: "TypeError", fingerprint: "0123456789abcdef", routeTemplate: "/incidents", topFrame: "/_next/static/chunks/app_page.js:10" }],
  ["frontend_error_captured", { errorSource: "error_boundary", errorName: "Error", fingerprint: "0123456789abcdef", routeTemplate: "/" }],
  ["network_request_failed", { method: "POST", routeTemplate: "/auth/login", errorKind: "network", online: false, elapsedMs: 15 }],
  ["navigation_section_viewed", { section: "incidents_manager", previousSection: "dashboard", entryKind: "menu_click" }],
  ["flow_started", { flow: "incident_report", flowInstanceId: UUID, section: "incident_new" }],
  ["flow_completed", { flow: "incident_report", flowInstanceId: UUID, elapsedMs: 12000, submitAttempts: 2 }],
  ["flow_abandoned", { flow: "outbound_order", flowInstanceId: UUID, lastStep: "submit_rejected", fieldsTouchedCount: 2, elapsedMs: 8000, exitTrigger: "navigation_away", hadSubmitError: true }],
  ["outbound_overdraw_warning_shown", { ingredientId: 3, requestedQuantity: 50, availableStock: 20, trigger: "typing" }],
];

describe("contrato frontend ↔ event-schemas.json", () => {
  let sent: Array<Record<string, unknown>> = [];

  beforeEach(() => {
    process.env.NEXT_PUBLIC_TELEMETRY_ENDPOINT = "http://localhost:8000/telemetry/events";
    __resetTelemetryForTests();
    window.sessionStorage.clear();
    window.localStorage.clear();
    sent = [];
    global.fetch = jest.fn(async (_url: unknown, init?: RequestInit) => {
      sent.push(...JSON.parse(String(init?.body)).events);
      return { ok: true, status: 200 } as Response;
    }) as unknown as typeof fetch;
  });

  it.each(SAMPLES.map((entry, index) => [`${entry[0]} #${index}`, entry] as const))("%s valida contra el esquema", async (_name, [type, props]) => {
    startTelemetrySession();
    track(type, props);
    await flush();
    expect(sent).toHaveLength(1);
    const ok = validate(sent[0]);
    expect(validate.errors ?? []).toEqual([]);
    expect(ok).toBe(true);
  });

  it("el cliente solo conoce eventos del plan y ninguna propiedad con PII", () => {
    const pii = ["email", "name", "password", "phone", "address", "token", "ip", "title", "description", "message"];
    for (const [type, rule] of Object.entries(EVENT_ALLOWLISTS)) {
      expect(schema.definitions.events[type]).toBeDefined();
      expect(rule.allowed.filter((key) => pii.includes(key.toLowerCase()))).toEqual([]);
    }
  });
});
