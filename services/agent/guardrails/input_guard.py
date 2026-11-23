"""Guardia de ENTRADA: decide, ANTES de gastar una llamada al modelo, qué se hace con el mensaje del manager.

Capas independientes (cada una es un «filtro» distinto, el ticket exige más de uno):
  1. seguridad  → intento de cambiar las instrucciones / jailbreak (patterns.py, robusto a ofuscación)
  2. seguridad  → petición de datos que nunca se revelan (sensitive.py), incluida la extracción GRADUAL de la receta madre,
                  que NO depende de una frase gatillo: se acumula estado por conversación
  3. contenido  → crisis personal (se atiende con cuidado, sin seguir la tarea) y uso como chatbot personal
  4. contenido  → small talk / trivia: se permite, pero la respuesta lleva reconducción obligatoria

El resultado es determinista: mismo texto + mismo estado de conversación = misma decisión.
"""
from __future__ import annotations

import re
import threading
from collections import OrderedDict
from dataclasses import dataclass, field

from . import patterns, policy, sensitive
from .text import detect_language, plain, views

# Tipos de fallo que se registran (requisito del ticket).
SECURITY, CONTENT, STRUCTURAL = "seguridad", "contenido", "estructural"

ALLOW, BLOCK, CASUAL = "allow", "block", "casual"
FOLLOWUP_WINDOW = 3  # mensajes de «seguimiento» tras un sondeo de receta que se siguen considerando parte de la extracción
OVERRIDE_ESCALATION = 3  # a partir de este número de intentos la negativa cambia a la versión «ya los registré»
MAX_CONVERSATIONS = 5000

_HARD_PERSONAL = re.compile(
    r"\b(?:poema|poemas|poesia|poem|poems|ensayo|ensayos|essay|essays|cuento|cuentos|story|novela|cancion|canciones|letra\s+de\s+una\s+cancion|song|lyrics|"
    r"tarea\s+(?:de|del|para)\s+(?:la\s+)?(?:escuela|colegio|universidad|clase|matematicas|historia|ingles|quimica|fisica)|homework|"
    r"trabajo\s+(?:escolar|de\s+la\s+universidad|de\s+clase)|tesis|monografia|resumen\s+del\s+libro|book\s+report|"
    r"horoscopo|horoscope|chiste\s+largo|carta\s+de\s+amor|love\s+letter|discurso\s+de\s+boda|wedding\s+speech|"
    r"codigo\s+(?:en|de|para)\s+(?:python|java|javascript|c\+\+|php|rust|go|sql|html|css)|"
    r"(?:programa|script|funcion|clase|app|aplicacion|pagina\s+web|sitio\s+web)\s+(?:en|con|de)\s+(?:python|java|javascript|typescript|c\+\+|php|rust|react)|"
    r"(?:write|code|build|create)\s+(?:me\s+)?(?:a\s+)?(?:python|javascript|java|react)\b|otro\s+proyecto|my\s+other\s+project|"
    r"traduce\s+(?:este|el)\s+(?:libro|capitulo|articulo)\s+)\b")
_SOFT_PERSONAL = re.compile(
    r"\b(?:mi\s+(?:novia|novio|pareja|esposa|esposo|ex|mama|papa|hijo|hija|terapeuta)|my\s+(?:girlfriend|boyfriend|wife|husband|ex|mom|dad)|"
    r"consejo\s+(?:personal|sentimental|amoroso|de\s+pareja)|relationship\s+advice|terapia|psicolog\w+|therapist|"
    r"que\s+(?:carrera|estudio)\s+(?:deberia|debo)|diagnostic\w+|diagnos\w+|inversion\w*\s+en\s+(?:bolsa|cripto)|crypto|bitcoin|"
    r"receta\s+de\s+(?:cocina\s+)?para\s+(?:mi\s+casa|cenar\s+en\s+casa)|vacaciones|itinerario\s+de\s+viaje|horoscopo)\b")
_REQUEST_VERB = re.compile(r"\b(?:escrib\w*|redact\w*|haz\w*|hazme|dame|dime|ayud\w*|genera\w*|crea\w*|programa\w*|resuelve\w*|resolver|explica\w*|"
                           r"traduc\w*|write|make|give|help|generate|create|solve|explain|translate|compose|tell)\b")
_CASUAL_SMALL = re.compile(
    r"^\W*(?:hola|holi|buenas|buenos\s+dias|buenas\s+tardes|buenas\s+noches|buen\s+dia|hey|hi|hello|good\s+(?:morning|afternoon|evening)|"
    r"que\s+tal|como\s+estas|como\s+andas|como\s+te\s+va|how\s+are\s+you|what'?s\s+up|gracias|muchas\s+gracias|thanks|thank\s+you|"
    r"adios|chao|hasta\s+luego|bye|que\s+tal\s+tu\s+turno|como\s+va\s+tu\s+turno|feliz\s+(?:dia|viernes|lunes|navidad)|"
    r"como\s+te\s+llamas|quien\s+eres|que\s+eres|who\s+are\s+you|what\s+are\s+you)\b.{0,50}$")
_CASUAL_TRIVIA = re.compile(
    r"\b(?:que\s+hora\s+es|what\s+time\s+is|cual\s+es\s+la\s+capital|capital\s+de|quien\s+(?:gano|invento|descubrio|escribio|pinto|fue|es)|"
    r"cuentame\s+(?:un\s+)?(?:chiste|dato)|dime\s+un\s+(?:chiste|dato)|tell\s+me\s+a\s+(?:joke|fun\s+fact)|curiosidad|dato\s+curioso|"
    r"fun\s+fact|trivia|cuanto\s+es\s+\d|what\s+is\s+the\s+capital|who\s+(?:won|invented|discovered|wrote|painted)|"
    r"cuando\s+(?:fue|se\s+fundo|nacio)|how\s+tall\s+is|que\s+dia\s+es|que\s+clima|como\s+esta\s+el\s+clima|weather\s+in|"
    r"origen\s+de\s+la\s+(?:pizza|hamburguesa|paella|cocina)|historia\s+de\s+la\s+(?:pizza|hamburguesa|parrilla|cocina))\b")


@dataclass
class ConversationGuardState:
    """Estado de seguridad de UNA conversación (en memoria del proceso; se pierde al reiniciar)."""
    turn: int = 0
    override_attempts: int = 0
    recipe_probes: int = 0
    last_recipe_turn: int = -100
    blocks: int = 0


@dataclass(frozen=True)
class InputDecision:
    action: str  # allow | block | casual
    kind: str | None = None  # seguridad | contenido | estructural (None si allow)
    reason: str | None = None  # código estable, p. ej. override_instructions, personal_task
    refusal: str | None = None  # clave de policy.REFUSALS
    language: str = "es"
    scope: str = "domain"  # domain | unanchored (sin ancla al dominio)
    attempts: int = 0
    detail: dict = field(default_factory=dict)

    @property
    def blocked(self) -> bool:
        return self.action == BLOCK


class GuardStateStore:
    """Estado por conversación con tope de tamaño (LRU) y un candado: la API atiende peticiones en hilos distintos."""

    def __init__(self, max_conversations: int = MAX_CONVERSATIONS):
        self._items: OrderedDict[str, ConversationGuardState] = OrderedDict()
        self._lock = threading.Lock()
        self._max = max_conversations

    def get(self, conversation_id: str | None) -> ConversationGuardState:
        if not conversation_id:
            return ConversationGuardState()  # sin conversación no hay memoria entre mensajes: cada uno se evalúa solo
        with self._lock:
            state = self._items.pop(conversation_id, None) or ConversationGuardState()
            self._items[conversation_id] = state
            while len(self._items) > self._max:
                self._items.popitem(last=False)
            return state

    def snapshot(self, conversation_id: str) -> ConversationGuardState | None:
        with self._lock:
            return self._items.get(conversation_id)


def has_domain_anchor(text: str) -> bool:
    words = set(re.findall(r"[a-z0-9]+", plain(text)))
    return bool(words & policy.DOMAIN_TERMS)


def _personal(clean_views: list[str], anchored: bool) -> str | None:
    text = " ".join(clean_views[:1])
    if _HARD_PERSONAL.search(text) and _REQUEST_VERB.search(text):
        return "personal_task"
    if _HARD_PERSONAL.search(text) and not anchored:
        return "personal_task"
    if _SOFT_PERSONAL.search(text) and not anchored:
        return "personal_advice"
    return None


def inspect(text: str, state: ConversationGuardState, *, pending_proposal: bool = False) -> InputDecision:
    """Evalúa un mensaje y actualiza el estado de la conversación. `pending_proposal`: hay una propuesta de memoria esperando
    respuesta, así que un «sí, gracias» corto es una respuesta a ella y no small talk."""
    state.turn += 1
    lang = detect_language(text)
    all_views = views(text)
    clean = all_views[0]
    anchored = has_domain_anchor(text)

    def block(kind: str, reason: str, refusal: str, **detail) -> InputDecision:
        state.blocks += 1
        return InputDecision(BLOCK, kind, reason, refusal, lang, "domain" if anchored else "unanchored", state.override_attempts, detail)

    # 1) Seguridad: intento de cambiar las instrucciones (cualquier reformulación, ofuscada o no).
    family = patterns.match_family(all_views, patterns.JAILBREAK_FAMILIES)
    if family:
        state.override_attempts += 1
        repeated = state.override_attempts >= OVERRIDE_ESCALATION
        return block(SECURITY, family, "override_repeated" if repeated else "override", attempt=state.override_attempts)

    # 2) Seguridad: datos que nunca se revelan. La receta se vigila también en seguimientos («¿y el segundo?»).
    kind = sensitive.recipe_request(text)
    if kind:
        state.recipe_probes += 1
        state.last_recipe_turn = state.turn
        return block(SECURITY, f"recipe_{kind}", "sensitive", probes=state.recipe_probes)
    if state.turn - state.last_recipe_turn <= FOLLOWUP_WINDOW and state.recipe_probes and sensitive.is_followup(text):
        state.recipe_probes += 1
        state.last_recipe_turn = state.turn
        return block(SECURITY, "recipe_gradual_extraction", "sensitive", probes=state.recipe_probes)
    secret = sensitive.sensitive_request(text)
    if secret:
        return block(SECURITY, secret, "sensitive")

    # 3) Contenido: crisis personal y uso como chatbot personal.
    if patterns.CRISIS.search(clean):
        return block(CONTENT, "personal_crisis", "wellbeing")
    personal = _personal(all_views, anchored)
    if personal:
        return block(CONTENT, personal, "personal")

    # 4) Contenido: small talk / trivia → se responde brevemente y se reconduce.
    # «¿qué tal tu turno?» es small talk aunque «turno» sea un término del dominio: se compara sin él.
    anchored_beyond_shift = has_domain_anchor(re.sub(r"\bturno\b", " ", clean))
    if not pending_proposal and not anchored_beyond_shift and (_CASUAL_SMALL.search(clean) or _CASUAL_TRIVIA.search(clean)):
        return InputDecision(CASUAL, CONTENT, "casual", None, lang, "unanchored", state.override_attempts)
    return InputDecision(ALLOW, None, None, None, lang, "domain" if anchored else "unanchored", state.override_attempts)
