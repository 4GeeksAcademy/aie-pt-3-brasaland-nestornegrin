"""Doble de modelo para la Parte 2 (generadores + evaluador de pertinencia). Distingue al agente por su system prompt y REGISTRA
cada llamada para comprobar qué recibe cada uno. Los borradores buenos cumplen el BRIEFING §5; los malos incumplen UNA regla."""
from __future__ import annotations

import json
import re

from rfp_support import ScriptedRfpModel  # noqa: F401  (Parte 1: genera el handoff que consume la Parte 2)

GOOD = {
    "marketing": (
        "{client} busca un socio para un servicio de alimentación con la marca Brasaland. Nuestra propuesta se apoya en tres pilares: "
        "calidad consistente, experiencia cálida y velocidad de servicio.\n\n"
        "- Co-branding: definimos juntos los términos de marca y el proceso de aprobación.\n"
        "- Exclusividad: revisaremos la cláusula pedida. Su duración está pendiente de confirmar.\n"
        "- Precio: el valor de la propuesta está pendiente de definir.\n\n"
        "La oferta tiene una validez de 30 días desde su emisión."),
    "operaciones": (
        "Operaciones evaluará la viabilidad de atender a {client}. Revisaremos la capacidad de cocina, el personal y el flujo de servicio "
        "en el sitio del cliente. El plazo de montaje está pendiente de confirmar y nunca será menor a 10 días hábiles.\n\n"
        "- Capacidad: la RFP no indica el volumen completo, por eso queda pendiente de confirmar.\n"
        "- Costo operativo por evento: pendiente de definir cuando recibamos los datos que faltan.\n"
        "- Personal: el plan se ajustará a la temporada y al horario del servicio."),
    "procurement": (
        "Procurement calculará el costo de los insumos para {client} según el volumen que confirme el cliente. Consultaremos a nuestros "
        "proveedores habituales y compararemos sus tiempos de entrega.\n\n"
        "- Costo de insumos: pendiente de confirmar, porque falta el volumen exacto.\n"
        "- Tiempos de proveedores: los confirmaremos antes de comprometer una fecha de entrega.\n"
        "- Entrega: no prometeremos plazos menores a 10 días hábiles."),
    "training": (
        "Training definirá el estándar de calidad que necesita el servicio para {client}. Si el pedido requiere una receta nueva, la "
        "desarrollaremos y la certificaremos antes de servirla.\n\n"
        "- Receta o estándar nuevo: lo diseñaremos junto con Operaciones.\n"
        "- Tiempo de desarrollo y certificación: pendiente de confirmar con el cliente.\n"
        "- Capacitación del personal: la planificaremos cuando se confirme el alcance."),
}
BAD_SLA = " Garantizamos el montaje en 5 días hábiles."  # setup-sla-breach
BAD_PRICE = " El costo es USD 60,000 al año."  # price-dual-currency
BAD_COMPETITOR = " Somos mejores que El Corral."  # no-competitors
BAD_FIGURE = " Atenderemos a 450 personas por día."  # no-invented-figures
SHORT = "Lo revisaremos pronto."  # legibilidad: muy corta


class ScriptedResponseModel:
    """`drafts[dept]` es una cola de textos: cada llamada del generador de ese departamento consume uno; al vaciarse, el borrador bueno."""

    def __init__(self):
        self.calls: list[tuple[str, str, list[dict]]] = []  # (agente, departamento|"", mensajes)
        self.drafts: dict[str, list[str]] = {}
        self.relevance_override = None
        self.generator_hook = None  # callable(dept) para sincronizar/inyectar fallos

    def __call__(self, messages: list[dict]) -> str:
        system, user = messages[0]["content"], messages[1]["content"]
        if system.startswith("Eres el agente GENERADOR"):
            dept = re.search(r"\(`(\w+)`", system).group(1)
            self.calls.append(("generator", dept, messages))
            if self.generator_hook:
                self.generator_hook(dept)
            queue = self.drafts.get(dept, [])
            if queue:
                text = queue.pop(0)
            else:
                client = json.loads(re.search(r"<analisis>\n(.*?)\n</analisis>", user, re.S).group(1))["metadatos"]["client_name"]
                text = GOOD[dept].format(client=client)
            return json.dumps({"content": text, "pending_items": ["Volumen del servicio"]})
        if system.startswith("Eres el agente EVALUADOR DE PERTINENCIA"):
            self.calls.append(("relevance", "", messages))
            if self.relevance_override is not None:
                return self.relevance_override(messages) if callable(self.relevance_override) else str(self.relevance_override)
            draft = re.search(r"<borrador>\n(.*?)\n</borrador>", user, re.S).group(1)
            first = re.split(r"(?<=[.!?])\s", draft.strip())[0]
            n = len(re.findall(r"(?m)^\d+\. ", user))
            return json.dumps({"aspects": [{"index": i, "covered": True, "evidence": first} for i in range(n)]})
        raise AssertionError(f"agente desconocido: {system[:60]}")

    def agent_calls(self, agent: str, dept: str | None = None):
        return [m for a, d, m in self.calls if a == agent and (dept is None or d == dept)]
