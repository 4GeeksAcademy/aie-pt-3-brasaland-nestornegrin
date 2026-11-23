"""Doble de modelo y utilidades para probar el pipeline `rfp_intake` sin red ni claves.

`ScriptedRfpModel` responde como lo haría un buen modelo para los 3 PDF de muestra del BRIEFING (se distingue el agente por su
system prompt y el documento por su contenido) y REGISTRA cada llamada, para comprobar qué recibe cada agente.
Lo que se prueba es la mecánica del pipeline y sus verificadores en código; la calidad con el modelo real se comprueba con
`scripts/rfp_smoke.py`.
"""
from __future__ import annotations

import json
from pathlib import Path

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "rfp"
PDF_FORMAL, PDF_INFORMAL, PDF_INVALID = (FIXTURES / f"brasaland-request-{n}.pdf" for n in (1, 2, 3))

SIGNALS_ALL = {"service_requested": True, "scope_or_volume": True, "deadline": True, "budget": True}

SUNSET = {
    "classification": {"is_rfp": True, "document_type": "rfp_formal", "confidence": 0.97, "signals": SIGNALS_ALL,
                       "reasons": ["Solicitud formal con alcance, fechas y valor del contrato."]},
    "metadata": {"reference": "SBR-2026-0417", "client_name": "Sunset Bay Resorts, LLC", "location": "Florida",
                 "service_type": "Concesión co-branded de alimentos y bebidas", "scope": "3 resorts, exclusividad, menú de autor, plan de personal",
                 "deadline": "Sep 2, 2026", "deadline_iso": "2026-09-02", "budget_range": "$60,000–$75,000 USD",
                 "budget_usd_min": 60000, "budget_usd_max": 75000, "open_questions": []},
    "plan": {"assignments": [
        {"department_id": "marketing", "reason": "Co-branding y exclusividad.", "excerpts": ["Exclusivity clause: no competing grill/BBQ concept permitted on resort premises for the contract term"]},
        {"department_id": "operaciones", "reason": "Operar 3 puntos.", "excerpts": ["Design and operate a branded concession stand in each of the 3 resort properties", "Staffing plan covering peak season (Nov–Apr) and off-season operations"]},
        {"department_id": "procurement", "reason": "Costear insumos.", "excerpts": ["Estimated annual contract value: $60,000–$75,000 USD"]},
        {"department_id": "training", "reason": "Menú de autor nuevo.", "excerpts": ["Develop a co-branded signature menu item exclusive to Sunset Bay Resorts"]}], "unknown_departments": []},
    "workers": {
        "marketing": {"key_aspects": [{"aspect": "Exclusividad", "detail": "Sin otro concepto grill/BBQ en las instalaciones.", "source_excerpt": "Exclusivity clause"}],
                      "asks": ["Definir términos de exclusividad y co-branding."], "figures": {"resorts": "3"}, "open_questions": ["No indica duración del contrato."]},
        "operaciones": {"key_aspects": [{"aspect": "Operación en 3 resorts", "detail": "Puntos de concesión en 3 propiedades, con temporada alta (Nov–Apr).", "source_excerpt": "3 resort properties"}],
                        "asks": ["Evaluar capacidad y plan de personal."], "figures": {"resorts": "3"}, "open_questions": ["No indica comensales por día."]},
        "procurement": {"key_aspects": [{"aspect": "Valor anual", "detail": "Entre 60,000 y 75,000 USD al año.", "source_excerpt": "$60,000–$75,000 USD"}],
                        "asks": ["Estimar costo de insumos según volumen."], "figures": {}, "open_questions": ["No indica volumen de insumos."]},
        "training": {"key_aspects": [{"aspect": "Menú de autor", "detail": "Ítem exclusivo co-branded.", "source_excerpt": "co-branded signature menu item"}],
                     "asks": ["Estimar tiempo de desarrollo y certificación."], "figures": {}, "open_questions": []}},
}
ANDES = {
    "classification": {"is_rfp": True, "document_type": "rfp_informal", "confidence": 0.86,
                       "signals": {"service_requested": True, "scope_or_volume": True, "deadline": True, "budget": False},
                       "reasons": ["Correo informal que pide propuesta con precios, 220 personas y plazo."]},
    "metadata": {"reference": None, "client_name": "Andes Tech Solutions", "location": "Medellín", "service_type": "Catering semanal",
                 "scope": "220 personas, martes y jueves, contrato de un año, menú estándar", "deadline": "18 de agosto", "deadline_iso": None,
                 "budget_range": None, "budget_usd_min": None, "budget_usd_max": None,
                 "open_questions": ["No indica presupuesto.", "La fecha límite no incluye el año."]},
    "plan": {"assignments": [
        {"department_id": "marketing", "reason": "Dueña del ticket.", "excerpts": ["Nos gustaría tener una propuesta de ustedes con precios"]},
        {"department_id": "operaciones", "reason": "Logística de 220 almuerzos.", "excerpts": ["somos alrededor de 220 personas", "quizás martes y jueves para empezar"]},
        {"department_id": "procurement", "reason": "Costo de insumos del menú estándar.", "excerpts": ["usando el menú estándar que ya manejan"]}], "unknown_departments": []},
    "workers": {
        "marketing": {"key_aspects": [{"aspect": "Propuesta con precios", "detail": "Pide precios y logística.", "source_excerpt": "propuesta de ustedes con precios"}],
                      "asks": ["Preparar la oferta comercial y su validez."], "figures": {}, "open_questions": ["No indica presupuesto."]},
        "operaciones": {"key_aspects": [{"aspect": "220 personas, 2 días/semana", "detail": "Almuerzo semanal en Medellín.", "source_excerpt": "alrededor de 220 personas"}],
                        "asks": ["Confirmar capacidad de cocina para 220 almuerzos."], "figures": {"comensales": "220"}, "open_questions": ["No indica horario de entrega."]},
        "procurement": {"key_aspects": [{"aspect": "Menú estándar", "detail": "Insumos del menú estándar para 220 personas.", "source_excerpt": "menú estándar"}],
                        "asks": ["Estimar costo de insumos y entrega en Medellín."], "figures": {"comensales": "220"}, "open_questions": []}},
}
NOT_RFP = {"classification": {"is_rfp": False, "document_type": "consulta_general", "confidence": 0.93,
                              "signals": {"service_requested": False, "scope_or_volume": False, "deadline": False, "budget": False},
                              "reasons": ["Consulta general sobre franquicias, sin alcance, presupuesto ni fecha."]}}


def document_in(messages: list[dict]) -> dict | None:
    text = " ".join(m["content"] for m in messages if m["role"] == "user")
    for marker, data in (("Sunset Bay", SUNSET), ("Andes Tech", ANDES), ("franquicias", NOT_RFP)):
        if marker in text:
            return data
    return None


class ScriptedRfpModel:
    def __init__(self):
        self.calls: list[tuple[str, list[dict]]] = []  # (agente, mensajes)
        self.overrides: dict[str, object] = {}  # agente -> respuesta fija (str o callable(messages))

    def __call__(self, messages: list[dict]) -> str:
        system = messages[0]["content"]
        agent = next((name for name, prefix in (("classifier", "Eres el agente CLASIFICADOR"), ("metadata", "Eres el agente EXTRACTOR"),
                                                ("orchestrator", "Eres el agente ORQUESTADOR"), ("worker", "Eres el agente WORKER"),
                                                ("synthesizer", "Eres el agente SYNTHESIZER")) if system.startswith(prefix)), "?")
        self.calls.append((agent, messages))
        if agent in self.overrides:
            override = self.overrides[agent]
            return override(messages) if callable(override) else str(override)
        doc = document_in(messages) or ANDES if agent not in ("worker", "synthesizer") else None
        if agent == "classifier":
            return json.dumps(doc["classification"])
        if agent == "metadata":
            return json.dumps(doc.get("metadata", {}))
        if agent == "orchestrator":
            return json.dumps(doc.get("plan", {"assignments": [], "unknown_departments": []}))
        if agent == "worker":
            department = system.split("`")[1]
            user = messages[1]["content"]
            data = SUNSET if "Sunset Bay" in user or "SBR-2026" in user else ANDES
            return json.dumps({"department_id": department, **data["workers"][department]})
        if agent == "synthesizer":
            payload = json.loads(messages[1]["content"])
            return json.dumps({"headline": "Oportunidad B2B analizada.",
                               "by_department": {h["department_id"]: "; ".join(h["asks"]) for h in payload["hallazgos"]}})
        raise AssertionError(f"agente desconocido: {system[:60]}")

    def agents_called(self) -> list[str]:
        return [a for a, _ in self.calls]
