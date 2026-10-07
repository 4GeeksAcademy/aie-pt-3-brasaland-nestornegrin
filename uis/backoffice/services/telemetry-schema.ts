// ARCHIVO GENERADO por scripts/gen-telemetry-schema.py — no editar a mano.
// Fuente: docs/telemetry/event-schemas.json

export const SCHEMA_VERSION = "1.0.0";

export type EventAllowlist = { allowed: readonly string[]; required: readonly string[] };

export const EVENT_ALLOWLISTS: Record<string, EventAllowlist> = {
  outbound_order_created: { allowed: ["exitId", "ingredientId", "restaurant", "quantity", "stockBefore", "stockAfter", "reasonProvided"], required: ["exitId", "ingredientId", "restaurant", "quantity", "stockBefore", "stockAfter", "reasonProvided"] },
  inventory_validation_failed: { allowed: ["operation", "errorCode", "httpStatus", "ingredientId", "restaurant", "requestedQuantity", "availableStock"], required: ["operation", "errorCode", "httpStatus"] },
  direct_stock_edit_rejected: { allowed: ["attemptKind", "httpMethod", "routeTemplate", "httpStatus", "offendingFields", "ingredientId"], required: ["attemptKind", "httpMethod", "routeTemplate", "httpStatus"] },
  stock_threshold_triggered: { allowed: ["ingredientId", "restaurant", "level", "thresholdValue", "stockBefore", "stockAfter", "triggeringExitId"], required: ["ingredientId", "restaurant", "level", "thresholdValue", "stockBefore", "stockAfter", "triggeringExitId"] },
  login_failed: { allowed: ["failureReason", "accountKey", "sourceKey"], required: ["failureReason", "accountKey", "sourceKey"] },
  navigation_section_viewed: { allowed: ["section", "previousSection", "entryKind"], required: ["section", "entryKind"] },
  flow_abandoned: { allowed: ["flow", "flowInstanceId", "lastStep", "fieldsTouchedCount", "elapsedMs", "exitTrigger", "hadSubmitError"], required: ["flow", "flowInstanceId", "lastStep", "fieldsTouchedCount", "elapsedMs", "exitTrigger", "hadSubmitError"] },
  inbound_order_created: { allowed: ["entryId", "ingredientId", "restaurant", "quantity", "stockAfter", "supplierProvided"], required: ["entryId", "ingredientId", "restaurant", "quantity", "stockAfter", "supplierProvided"] },
  ingredient_created: { allowed: ["ingredientId", "restaurant", "creatorRole"], required: ["ingredientId", "restaurant", "creatorRole"] },
  outbound_overdraw_warning_shown: { allowed: ["ingredientId", "requestedQuantity", "availableStock", "trigger"], required: ["ingredientId", "requestedQuantity", "availableStock", "trigger"] },
  stock_snapshot_recorded: { allowed: ["restaurant", "ingredientsTotal", "zeroCount", "criticalCount", "lowCount", "healthyCount"], required: ["restaurant", "ingredientsTotal", "zeroCount", "criticalCount", "lowCount", "healthyCount"] },
  incident_created: { allowed: ["incidentId", "category", "origin", "branch"], required: ["incidentId", "category", "origin", "branch"] },
  incident_status_changed: { allowed: ["incidentId", "fromStatus", "toStatus", "category", "ageHours"], required: ["incidentId", "fromStatus", "toStatus", "category", "ageHours"] },
  incident_csv_analyzed: { allowed: ["outcome", "fileSizeBytes", "totalRows", "invalidRows", "durationMs"], required: ["outcome", "durationMs"] },
  incident_list_filtered: { allowed: ["filtersApplied", "resultCount"], required: ["filtersApplied", "resultCount"] },
  incident_results_exported: { allowed: ["outcome", "rowCount"], required: ["outcome"] },
  supplier_rate_updated: { allowed: ["supplierId", "country", "previousRate", "newRate"], required: ["supplierId", "country", "previousRate", "newRate"] },
  login_succeeded: { allowed: ["tokenTtlMinutes"], required: ["tokenTtlMinutes"] },
  session_expired: { allowed: ["section", "sessionAgeMinutes", "formDirty", "flow"], required: ["section", "sessionAgeMinutes", "formDirty"] },
  password_reset_requested: { allowed: ["accountKnown", "emailSendOutcome"], required: ["accountKnown", "emailSendOutcome"] },
  password_reset_completed: { allowed: ["tokenAgeMinutes"], required: ["tokenAgeMinutes"] },
  password_reset_failed: { allowed: ["failureReason", "tokenAgeMinutes"], required: ["failureReason"] },
  user_registered: { allowed: ["registrationOutcome", "hasPhone", "hasAddress"], required: ["registrationOutcome", "hasPhone", "hasAddress"] },
  api_latency_recorded: { allowed: ["method", "routeTemplate", "statusClass", "durationMs", "responseBytes", "cache", "sampleRate"], required: ["method", "routeTemplate", "statusClass", "durationMs", "cache", "sampleRate"] },
  web_vital_measured: { allowed: ["metric", "value", "rating", "routeTemplate", "navigationType"], required: ["metric", "value", "rating", "routeTemplate", "navigationType"] },
  api_unhandled_error_raised: { allowed: ["method", "routeTemplate", "exceptionType", "fingerprint"], required: ["method", "routeTemplate", "exceptionType", "fingerprint"] },
  frontend_error_captured: { allowed: ["errorSource", "errorName", "fingerprint", "topFrame", "routeTemplate"], required: ["errorSource", "errorName", "fingerprint", "routeTemplate"] },
  network_request_failed: { allowed: ["method", "routeTemplate", "errorKind", "online", "elapsedMs"], required: ["method", "routeTemplate", "errorKind", "online", "elapsedMs"] },
  request_validation_failed: { allowed: ["method", "routeTemplate", "failedFields", "errorTypes"], required: ["method", "routeTemplate", "failedFields", "errorTypes"] },
  flow_started: { allowed: ["flow", "flowInstanceId", "section"], required: ["flow", "flowInstanceId", "section"] },
  flow_completed: { allowed: ["flow", "flowInstanceId", "elapsedMs", "submitAttempts"], required: ["flow", "flowInstanceId", "elapsedMs", "submitAttempts"] },
};
