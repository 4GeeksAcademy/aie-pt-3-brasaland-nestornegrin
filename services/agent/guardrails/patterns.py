"""Patrones de ataque contra las instrucciones del agente. Se aplican sobre texto YA normalizado (`text.views()`):
minúsculas, sin tildes, con homoglifos/leetspeak traducidos y letras separadas pegadas.

Cada familia es una forma distinta de pedir lo mismo («deja de ser quien eres»), porque un solo patrón se evade
reformulando. Los códigos de familia son estables: aparecen en el registro y en la documentación del PR.

Ninguna familia dispara con un verbo suelto («ignora el ticket 5», «olvida el pedido anterior», «actúa rápido»): todas
exigen el OBJETO del ataque (instrucciones, reglas, prompt, restricciones, la identidad del agente…).
"""
from __future__ import annotations

import re

_GAP = r"(?:\W+\w+){0,6}?\W+"  # hasta 6 palabras de relleno entre el verbo y el objeto

_RULES_OBJECT = (r"(?:instrucciones|instruccion|reglas|regla|restricciones|restriccion|directrices|directriz|normas|limites|"
                 r"prompt|programacion|configuracion|guardrails|filtros|politicas|salvaguardas|protocolos|"
                 r"instructions|rules|guidelines|restrictions|programming|filters|policies|safeguards|constraints|"
                 r"system message|mensaje del sistema)")
_OVERRIDE_VERB = (r"(?:ignor\w*|olvid\w*|omit\w*|descart\w*|salt\w*|anul\w*|desactiv\w*|deshabilit\w*|elimin\w*|borr\w*|"
                  r"suspend\w*|rompe\w*|quita\w*|saltate|bypass\w*|disregard\w*|forget\w*|overrid\w*|override|erase|delete|"
                  r"disable\w*|drop|skip|set aside|stop following|no sigas|deja de (?:seguir|cumplir|obedecer|respetar))")
_UNRESTRICTED = (r"(?:sin (?:ningun[ao]s? )?(?:reglas|restricciones|filtros|limites|censura|etica|normas|moral|barreras|"
                 r"instrucciones|guardrails)|"
                 r"unrestricted|uncensored|unfiltered|without (?:any )?(?:rules|restrictions|limits|filters|guardrails|censorship)|"
                 r"no (?:rules|restrictions|limits|filters)|"
                 r"jailbroken|jailbreak|do anything now|modo (?:dios|desarrollador|sin censura|sin restricciones|libre|admin\w*)|"
                 r"(?:developer|god|admin|debug|sudo|dan) mode)")

# (código de familia, patrón). El primero que casa es el motivo que se registra.
JAILBREAK_FAMILIES: list[tuple[str, re.Pattern]] = [
    ("override_instructions", re.compile(rf"\b{_OVERRIDE_VERB}\b{_GAP}{_RULES_OBJECT}\b")),
    ("override_everything_before", re.compile(
        r"\b(?:ignor\w*|olvid\w*|forget|disregard|ignore)\b(?:\W+\w+){0,3}?\W+(?:todo\s+(?:lo\s+)?(?:anterior|que\s+te\s+(?:dije|dijeron|han\s+dicho)|"
        r"lo\s+de\s+arriba)|everything\s+(?:above|before|you\s+were\s+told)|all\s+(?:previous|prior)|"
        r"(?:todo|todas)\s+(?:las\s+)?(?:anteriores|previas)|lo\s+que\s+te\s+(?:dijeron|programaron))")),
    ("forget_identity", re.compile(
        rf"\b(?:olvid\w*|ignor\w*|forget|stop being|deja\s+de\s+ser|ya\s+no\s+(?:eres|trabajas|tienes|estas)|no\s+eres\s+mas|"
        rf"no\s+longer)\b{_GAP}(?:que\s+)?(?:trabajas|trabaja|eres|work|you\s+work|you\s+are|asistente\s+de|assistant\s+for|"
        rf"para\s+(?:la\s+empresa|brasaland)|(?:the\s+)?(?:company|brasaland))")),
    ("role_change_unrestricted", re.compile(
        rf"\b(?:act\w*|comport\w*|finge|fing\w*|simula\w*|simulate|pretend|imagina\w*|imagine|roleplay|role-play|juega\w*|"
        rf"ahora\s+eres|eres\s+ahora|a\s+partir\s+de\s+ahora|from\s+now\s+on|you\s+are\s+now|you\s+will\s+be|serás|seras|"
        rf"se\s+un|be\s+an?|responde\s+como)\b{_GAP}{_UNRESTRICTED}")),
    ("no_rules_claim", re.compile(
        r"\b(?:como\s+si\s+no\s+tuvieras|no\s+tienes|ya\s+no\s+tienes|no\s+tuvieras|no\s+tengas|sin|carece\w*\s+de|"
        r"you\s+have\s+no|there\s+are\s+no|as\s+if\s+you\s+had\s+no|you\s+don'?t\s+have\s+any|no\s+longer\s+have|"
        r"no\s+existe\w*)\s+(?:ninguna?\s+)?(?:regla|reglas|restriccion|restricciones|limite|limites|filtro|filtros|norma|normas|"
        r"rules|restrictions|limits|filters|guidelines|instrucciones|instructions)\b")),
    ("prompt_extraction", re.compile(
        rf"\b(?:muestr\w*|revel\w*|dime|dinos|repit\w*|imprim\w*|escrib\w*|copi\w*|pega\w*|lista\w*|expon\w*|filtr\w*|"
        rf"print|show|reveal|repeat|display|output|leak|dump|tell\s+me|give\s+me|recite|translate)\b{_GAP}"
        rf"(?:tu|tus|el|los|las|your|the|its|system|initial|original|hidden|secret|internal|oculto\w*|secreto\w*|inicial\w*)\s*"
        rf"(?:\w+\s+){{0,2}}(?:prompt|instrucciones|instructions|reglas\s+internas|configuracion|system\s+message|mensaje\s+del\s+sistema|"
        rf"programacion|directrices)\b")),
    ("prompt_extraction_indirect", re.compile(
        r"\b(?:que\s+(?:te\s+)?(?:dijeron|programaron|escribieron|ordenaron)\s+(?:al\s+(?:inicio|principio)|antes)|"
        r"what\s+(?:was|were)\s+(?:written|said|you\s+told)\s+(?:above|before|at\s+the\s+(?:start|beginning))|"
        r"(?:primeras|primeros|first)\s+\d*\s*(?:palabras|lineas|words|lines)\s+(?:de|of)\s+(?:tu|your)|"
        r"repite\s+(?:todo\s+)?lo\s+(?:de\s+)?(?:arriba|anterior)|everything\s+above\s+this)\b")),
    ("authority_spoof", re.compile(
        r"\b(?:soy|i\s+am|i'?m|this\s+is|habla|aqui)\s+(?:tu|el|la|un|una|your|the|a|an)?\s*(?:desarrollador\w*|administrador\w*|"
        r"creador\w*|dueno|programador\w*|admin\b|developer|administrator|creator|owner|engineer|ingeniero\w*|tech\s+lead|"
        r"jefe\s+de\s+seguridad|equipo\s+de\s+seguridad|security\s+team|openai|anthropic)\b")),
    ("fake_system_message", re.compile(
        r"(?:^|\n|\s)(?:\[?\s*(?:system|sistema|admin|developer|desarrollador|assistant|asistente)\s*\]?\s*[:>]|"
        r"###\s*(?:system|instruction|instruccion)|<\|\w+\|>|\[inst\]|<<sys>>|begin\s+system|"
        r"(?:mensaje|nueva\s+instruccion|aviso|orden)\s+(?:del\s+)?(?:sistema|de\s+seguridad|administrativ\w*|prioritari\w*)|"
        r"system\s+(?:override|prompt\s*:|update|notice))")),
    ("priority_claim", re.compile(
        r"\b(?:esta|estas|this|these|esto)\b(?:\W+\w+){0,3}?\W+(?:instruccion|instrucciones|orden|ordenes|mensaje|message|"
        r"instruction|instructions|command)\b(?:\W+\w+){0,4}?\W+(?:tiene|tienen|has|have|takes|take)?\s*"
        r"(?:prioridad|precedencia|precedence|priority|reemplaza\w*|replace\w*|sustituye\w*|anula\w*|override\w*|supersede\w*)")),
    ("refusal_suppression", re.compile(
        r"\b(?:nunca|jamas|no)\s+(?:te\s+)?(?:niegues|rechaces|digas\s+que\s+no|me\s+digas\s+que\s+no|respondas\s+que\s+no|"
        r"puedes|puedo)|never\s+(?:refuse|say\s+no|decline)|do\s+not\s+refuse|"
        r"responde\s+siempre\s+(?:si|que\s+si)|always\s+(?:comply|obey|answer)|obedece\s+(?:todo|siempre|cualquier)|"
        r"cumple\s+(?:todo|cualquier)\s+(?:lo\s+que|orden|pedido)")),
    ("hypothetical_unrestricted", re.compile(
        rf"\b(?:hipotetic\w*|fictici\w*|hypothetical\w*|fictional|en\s+un\s+juego|en\s+esta\s+(?:historia|novela|ficcion)|"
        rf"para\s+una\s+(?:novela|historia|pelicula|obra)|in\s+a\s+(?:game|story|novel|movie|roleplay))\b{_GAP}{_UNRESTRICTED}")),
    ("named_jailbreak", re.compile(r"\b(?:dan|stan|dude|aim|evil[\s-]?bot|evilgpt|maximum|developer\s+mode|modo\s+dan)\b(?=.*\b(?:mode|modo|prompt|jailbreak|"
                                   r"anything|cualquier\s+cosa|sin\s+reglas|without\s+rules)\b)|\bdo\s+anything\s+now\b|\bjailbreak\w*\b")),
]

# Contenido EXTERNO (documentos del RAG, resultados de tools): además de lo anterior, frases que se dirigen al modelo.
EXTERNAL_ONLY_FAMILIES: list[tuple[str, re.Pattern]] = [
    ("addresses_the_model", re.compile(
        r"\b(?:assistant|asistente|\bia\b|\bai\b|model|modelo|llm|chatbot|gpt|claude|agente|agent)\b[\s,:;-]*(?:you\s+(?:must|should|need|have\s+to|will)|"
        r"debes|tienes\s+que|deberias|necesitas|por\s+favor|please|ahora|now|ignora|ignore|responde|reply|respond|di\b|say\b|"
        r"envia|send|llama|call|ejecuta|execute|run)")),
    ("when_you_read_this", re.compile(r"\b(?:when\s+you\s+(?:read|see|process)|al\s+(?:leer|ver|procesar)\s+(?:esto|este)|if\s+you\s+are\s+an?\s+(?:ai|llm|assistant)|"
                                     r"si\s+eres\s+(?:una?\s+)?(?:ia|asistente|modelo|llm))\b")),
    ("forced_output", re.compile(r"\b(?:responde|respond|reply|answer|di|say|escribe|write|contesta)\s+(?:solo|only|exactamente|exactly|siempre|always|con)\b(?:\W+\w+){0,3}?\W*[\"'«]")),
    ("exfiltration", re.compile(r"!\[[^\]]*\]\([^)]*\)|\b(?:envia|enviar|send|post|upload|exfiltra\w*|forward)\b(?:\W+\w+){0,6}?\W+(?:a|to|hacia)\s+(?:https?://|\S+@\S+)|https?://\S+\?\S*=")),
]

CRISIS = re.compile(
    r"\b(?:suicid\w*|quitarme\s+la\s+vida|quitarle\s+la\s+vida\s+a\s+mi|hacerme\s+dano|lastimarme|matarme|acabar\s+con\s+mi\s+vida|"
    r"no\s+quiero\s+(?:seguir\s+)?vivir|ya\s+no\s+quiero\s+vivir|kill\s+myself|end\s+my\s+life|hurt\s+myself|self[\s-]?harm|"
    r"want\s+to\s+die|don'?t\s+want\s+to\s+live|me\s+quiero\s+morir)\b")


def match_family(text_views: list[str], families: list[tuple[str, re.Pattern]]) -> str | None:
    for code, pattern in families:
        if any(pattern.search(view) for view in text_views):
            return code
    return None


def injection_family(text_views: list[str]) -> str | None:
    """Código de la familia que casa (jailbreak o, en contenido externo, frases dirigidas al modelo), o None."""
    return match_family(text_views, JAILBREAK_FAMILIES + EXTERNAL_ONLY_FAMILIES)
