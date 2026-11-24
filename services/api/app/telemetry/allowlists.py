"""ARCHIVO GENERADO por app/telemetry/generate_allowlists.py — no editar a mano.
Fuente: docs/telemetry/event-schemas.json"""
from __future__ import annotations

from typing import NamedTuple

SCHEMA_VERSION = "1.1.0"


class EventAllowlist(NamedTuple):
    allowed: tuple[str, ...]
    required: tuple[str, ...]


EVENT_ALLOWLISTS: dict[str, EventAllowlist] = {
    "outbound_order_created": EventAllowlist(allowed=('exitId', 'ingredientId', 'restaurant', 'quantity', 'stockBefore', 'stockAfter', 'reasonProvided'), required=('exitId', 'ingredientId', 'restaurant', 'quantity', 'stockBefore', 'stockAfter', 'reasonProvided')),
    "inventory_validation_failed": EventAllowlist(allowed=('operation', 'errorCode', 'httpStatus', 'ingredientId', 'restaurant', 'requestedQuantity', 'availableStock'), required=('operation', 'errorCode', 'httpStatus')),
    "direct_stock_edit_rejected": EventAllowlist(allowed=('attemptKind', 'httpMethod', 'routeTemplate', 'httpStatus', 'offendingFields', 'ingredientId'), required=('attemptKind', 'httpMethod', 'routeTemplate', 'httpStatus')),
    "stock_threshold_triggered": EventAllowlist(allowed=('ingredientId', 'restaurant', 'level', 'thresholdValue', 'stockBefore', 'stockAfter', 'triggeringExitId'), required=('ingredientId', 'restaurant', 'level', 'thresholdValue', 'stockBefore', 'stockAfter', 'triggeringExitId')),
    "login_failed": EventAllowlist(allowed=('failureReason', 'accountKey', 'sourceKey'), required=('failureReason',)),
    "navigation_section_viewed": EventAllowlist(allowed=('section', 'previousSection', 'entryKind'), required=('section', 'entryKind')),
    "flow_abandoned": EventAllowlist(allowed=('flow', 'flowInstanceId', 'lastStep', 'fieldsTouchedCount', 'elapsedMs', 'exitTrigger', 'hadSubmitError'), required=('flow', 'flowInstanceId', 'lastStep', 'fieldsTouchedCount', 'elapsedMs', 'exitTrigger', 'hadSubmitError')),
    "inbound_order_created": EventAllowlist(allowed=('entryId', 'ingredientId', 'restaurant', 'quantity', 'stockAfter', 'supplierProvided'), required=('entryId', 'ingredientId', 'restaurant', 'quantity', 'stockAfter', 'supplierProvided')),
    "ingredient_created": EventAllowlist(allowed=('ingredientId', 'restaurant', 'creatorRole'), required=('ingredientId', 'restaurant', 'creatorRole')),
    "outbound_overdraw_warning_shown": EventAllowlist(allowed=('ingredientId', 'requestedQuantity', 'availableStock', 'trigger'), required=('ingredientId', 'requestedQuantity', 'availableStock', 'trigger')),
    "stock_snapshot_recorded": EventAllowlist(allowed=('restaurant', 'ingredientsTotal', 'zeroCount', 'criticalCount', 'lowCount', 'healthyCount'), required=('restaurant', 'ingredientsTotal', 'zeroCount', 'criticalCount', 'lowCount', 'healthyCount')),
    "incident_created": EventAllowlist(allowed=('incidentId', 'category', 'origin', 'branch'), required=('incidentId', 'category', 'origin', 'branch')),
    "incident_status_changed": EventAllowlist(allowed=('incidentId', 'fromStatus', 'toStatus', 'category', 'ageHours'), required=('incidentId', 'fromStatus', 'toStatus', 'category', 'ageHours')),
    "incident_csv_analyzed": EventAllowlist(allowed=('outcome', 'fileSizeBytes', 'totalRows', 'invalidRows', 'durationMs'), required=('outcome', 'durationMs')),
    "incident_list_filtered": EventAllowlist(allowed=('filtersApplied', 'resultCount'), required=('filtersApplied', 'resultCount')),
    "incident_results_exported": EventAllowlist(allowed=('outcome', 'rowCount'), required=('outcome',)),
    "supplier_rate_updated": EventAllowlist(allowed=('supplierId', 'country', 'previousRate', 'newRate'), required=('supplierId', 'country', 'previousRate', 'newRate')),
    "login_succeeded": EventAllowlist(allowed=('tokenTtlMinutes',), required=('tokenTtlMinutes',)),
    "session_expired": EventAllowlist(allowed=('section', 'sessionAgeMinutes', 'formDirty', 'flow'), required=('section', 'sessionAgeMinutes', 'formDirty')),
    "password_reset_requested": EventAllowlist(allowed=('accountKnown', 'emailSendOutcome'), required=('accountKnown', 'emailSendOutcome')),
    "password_reset_completed": EventAllowlist(allowed=('tokenAgeMinutes',), required=('tokenAgeMinutes',)),
    "password_reset_failed": EventAllowlist(allowed=('failureReason', 'tokenAgeMinutes'), required=('failureReason',)),
    "user_registered": EventAllowlist(allowed=('registrationOutcome', 'hasPhone', 'hasAddress'), required=('registrationOutcome', 'hasPhone', 'hasAddress')),
    "api_latency_recorded": EventAllowlist(allowed=('method', 'routeTemplate', 'statusClass', 'durationMs', 'responseBytes', 'cache', 'sampleRate'), required=('method', 'routeTemplate', 'statusClass', 'durationMs', 'sampleRate')),
    "web_vital_measured": EventAllowlist(allowed=('metric', 'value', 'rating', 'routeTemplate', 'navigationType'), required=('metric', 'value', 'rating', 'routeTemplate', 'navigationType')),
    "api_unhandled_error_raised": EventAllowlist(allowed=('method', 'routeTemplate', 'exceptionType', 'fingerprint'), required=('method', 'routeTemplate', 'exceptionType', 'fingerprint')),
    "frontend_error_captured": EventAllowlist(allowed=('errorSource', 'errorName', 'fingerprint', 'topFrame', 'routeTemplate'), required=('errorSource', 'errorName', 'fingerprint', 'routeTemplate')),
    "network_request_failed": EventAllowlist(allowed=('method', 'routeTemplate', 'errorKind', 'online', 'elapsedMs'), required=('method', 'routeTemplate', 'errorKind', 'online', 'elapsedMs')),
    "request_validation_failed": EventAllowlist(allowed=('method', 'routeTemplate', 'failedFields', 'errorTypes'), required=('method', 'routeTemplate', 'failedFields', 'errorTypes')),
    "flow_started": EventAllowlist(allowed=('flow', 'flowInstanceId', 'section'), required=('flow', 'flowInstanceId', 'section')),
    "flow_completed": EventAllowlist(allowed=('flow', 'flowInstanceId', 'elapsedMs', 'submitAttempts'), required=('flow', 'flowInstanceId', 'elapsedMs', 'submitAttempts')),
}
