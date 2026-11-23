"""Detectores de lo que el BRIEFING (Hito 8 · Parte 2 §3) prohíbe revelar.

Se usan en TRES sitios con los mismos criterios: la entrada (pedir esos datos), la salida (que el modelo los suelte
aunque no se los pidieran) y la memoria de la Parte 1 (que una «corrección» no los cuele para sacarlos después).

    receta madre / fórmula propietaria       cantidades e ingredientes de la salsa de la casa, aunque sea ingrediente a ingrediente
    contratos y precios con proveedores      costo por porción que se cobra al proveedor, términos de contrato, precios negociados
    nómina y evaluaciones de desempeño       salarios, bonos, evaluaciones de otros empleados
    PII de clientes / Brasa Points           correos, teléfonos, documentos, listas de clientes
"""
from __future__ import annotations

import re

from .text import plain

_RECIPE_SUBJECT = (r"(?:receta|recetas|salsa|salsas|marinado|marinada|marinadas|adobo|aderezo|sazon|especias|formula|mezcla|recipe|"
                   r"sauce|marinade|seasoning|rub|dressing|preparacion)")
_HOUSE = r"(?:de\s+la\s+casa|secreta|madre|brasaland|propia|house|signature|de\s+brasaland|especial)"
_ALLERGEN_CUE = re.compile(r"\b(?:alerg\w*|allerg\w*|soya|soja|gluten|lacteos?|mani|nueces|nuez|huevo|marisco|trazas|celiac\w*|"
                           r"intoleran\w*|vegan\w*|vegetarian\w*|apto|puede\s+comer)\b")
_RECIPE_FORMULA = re.compile(
    rf"(?:\b{_RECIPE_SUBJECT}\b.{{0,60}}\b(?:completa|completo|exacta|exactas|exacto|exactos|con\s+cantidades|cantidades|proporci\w+|"
    rf"gramos|mililitros|medidas|paso\s+a\s+paso|madre|secreta|formula|full|exact|complete|step\s+by\s+step|quantities|amounts|"
    rf"proportions|grams)\b|"
    rf"\b(?:receta|recipe)\s+(?:completa\s+|madre\s+|secreta\s+|exacta\s+|full\s+|master\s+)?(?:de|del|of)\s+(?:la\s+|el\s+|the\s+)?"
    rf"(?:salsa|marinado|adobo|{_RECIPE_SUBJECT})\s+{_HOUSE}|\breceta\s+madre\b|\bmaster\s+recipe\b|"
    rf"\b(?:cantidades|proporciones|quantities|amounts|proportions)\s+(?:exactas|exactos|exact)?\s*(?:de|del|of)\b.{{0,40}}\b{_RECIPE_SUBJECT}\b)")
_RECIPE_INGREDIENT = re.compile(
    rf"(?:\b{_RECIPE_SUBJECT}\b.{{0,40}}\b{_HOUSE}\b.{{0,60}}\b(?:ingrediente|ingredientes|lleva|llevan|se\s+hace\s+con|hecha\s+con|"
    rf"hecho\s+con|contiene|componentes|que\s+tiene|ingredient|ingredients|made\s+(?:of|with)|contains|what'?s\s+in)\b|"
    rf"\b(?:ingrediente|ingredientes|ingredient|ingredients|componentes)\b.{{0,40}}\b{_RECIPE_SUBJECT}\b.{{0,30}}\b{_HOUSE}\b|"
    rf"\b(?:que|cual|cuales)\s+(?:ingredientes?\s+)?(?:lleva|llevan|tiene|contiene)\s+(?:la\s+|el\s+)?{_RECIPE_SUBJECT}\s+{_HOUSE}\b|"
    rf"\b(?:con\s+que|de\s+que)\s+(?:se\s+hace|esta\s+hech\w+|se\s+prepara)\s+(?:la\s+|el\s+)?{_RECIPE_SUBJECT}\s+{_HOUSE}\b|"
    rf"\b(?:un|el|el\s+primer|primer|siguiente|segundo|tercer|otro)\w*\s+ingrediente\b.{{0,30}}\b(?:salsa|receta|marinado|adobo|sauce|recipe)\b)")
_FOLLOWUP = re.compile(
    r"^\W*(?:y\s+|ahora\s+|dime\s+|dame\s+|y\s+ahora\s+|and\s+|now\s+|what\s+about\s+)?(?:el|la|los|las|the)?\s*"
    r"(?:siguiente|segundo|tercero|tercer|cuarto|quinto|otro|proximo|ultimo|resto|next|second|third|another|rest|last)\b"
    r"|^\W*(?:y\s+)?(?:luego|despues|ademas|que\s+mas|entonces|continua|sigue|continue|then|next|go\s+on|and\s+then|what\s+else)\b"
    r"|^\W*(?:y\s+)?(?:cuanto|cuanta|cuantos|how\s+much|how\s+many)\b"
    r"|\b(?:otro|siguiente|segundo|tercer\w*|resto\s+de\s+los|next|another)\s+ingredientes?\b")

_COMMERCIAL_WORDS = r"(?:costo|costos|precio|precios|tarifa|tarifas|cobra\w*|cobramos|pagamos|pagan|paga|pago|cuesta\w*|descuento|descuentos|margen|cotizacion|factura\w*|price|prices|cost|costs|rate|rates|charge\w*|pay|paid|negotiated|discount\w*|quote)"
_SUPPLIER_WORDS = r"(?:proveedor|proveedores|supplier|suppliers|vendor|vendors|contrato|contratos|contract|contracts|procurement|compras)"
_COMMERCIAL = re.compile(
    rf"(?:\b{_COMMERCIAL_WORDS}\b.{{0,70}}\b{_SUPPLIER_WORDS}\b|\b{_SUPPLIER_WORDS}\b.{{0,70}}\b{_COMMERCIAL_WORDS}\b|"
    r"\bcosto\s+por\s+porcion\b|\bcost\s+per\s+(?:portion|serving)\b|"
    r"\b(?:terminos|condiciones|clausulas|vigencia|terms|conditions|clauses)\s+(?:del|de\s+los|of\s+the|of)\s+(?:contrato|contratos|contract|contracts)\b|"
    r"\bprecios?\s+negociad\w+\b|\bnegotiated\s+(?:prices?|rates?|terms)\b)")
_COMMERCIAL_BENIGN = re.compile(r"\b(?:frecuencia|cuando|dias?|fecha|horario|entrega|entregan|categoria|categorias|pedido|when|delivery|"
                                r"schedule|frequency)\b")

_EMPLOYEE = re.compile(
    r"\b(?:salario|salarios|sueldo|sueldos|nomina|nominas|bonificacion\w*|bono|bonos|compensacion|payroll|salary|salaries|wage|wages|"
    r"paycheck|aumento\s+de\s+(?:sueldo|salario)|cuanto\s+(?:gana|cobra|le\s+pagan|le\s+pagamos)|how\s+much\s+(?:does\s+\w+\s+)?(?:earn|make))\b|"
    r"\b(?:evaluacion|evaluaciones|calificacion|calificaciones|review|reviews|appraisal|appraisals)\s+(?:anual(?:es)?\s+|semestral(?:es)?\s+)?"
    r"(?:de\s+|del\s+|of\s+)?(?:desempeno|rendimiento|performance)\b|\bperformance\s+(?:review|evaluation|appraisal)s?\b|"
    r"\bdesempeno\s+(?:de|del)\s+(?:empleado|empleada|mesero|mesera|cocinero|cocinera|cajero|cajera|personal|trabajador|equipo)\b")
_CUSTOMER_FIELD = r"(?:telefono|celular|correo|email|mail|direccion|documento|cedula|datos\s+personales|nombre\s+completo|historial|saldo|numero|phone|address|personal\s+(?:data|information)|full\s+name|contact)"
_CUSTOMER_WORD = r"(?:cliente|clienta|clientes|socio|socia|miembro|member|members|customer|customers|titular)"
_CUSTOMER_REQUEST = re.compile(
    rf"(?:\b{_CUSTOMER_FIELD}\b.{{0,40}}\b{_CUSTOMER_WORD}\b|\b(?:lista|listado|base\s+de\s+datos|todos\s+los|list\s+of|database\s+of|all)\b.{{0,25}}\b{_CUSTOMER_WORD}\b|"
    r"\b(?:datos|informacion|data|information)\b.{0,30}\bbrasa\s+points\b.{0,40}\b(?:de|of)\s+[a-z]+\s+[a-z]+)")
_INCIDENT_CONTEXT = re.compile(r"\b(?:ticket|tickets|incidente|incidencia|incident|queja|reclamo)\b")

_QUANTITY = re.compile(r"\b\d+(?:[.,]\d+)?\s?(?:g|gr|grs|gramos?|kg|kilos?|ml|l|litros?|cucharadas?|cucharaditas?|tazas?|oz|onzas?|"
                       r"libras?|lb|cups?|tbsp|tsp|teaspoons?|tablespoons?|%|por\s+ciento|partes?)\b")
_RECIPE_VOCAB = re.compile(r"\b(?:receta|salsa|marinado|marinada|adobo|sazon|formula|ingrediente|ingredientes|aderezo|mezcla|recipe|sauce|"
                           r"marinade|ingredient|ingredients|seasoning|dressing)\b")
_MONEY = re.compile(r"(?:\$\s?\d|\b\d[\d.,]*\s?(?:cop|usd|dolares|pesos|mil\s+pesos)\b|\b(?:cop|usd)\s?\d)")
_SALARY_WORDS = re.compile(r"\b(?:salario|sueldo|nomina|bonificacion|bono|compensacion|payroll|salary|wage|paycheck|gana|cobra)\b")

PII_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PII_PHONE = re.compile(r"(?<![\w.])(?:\+\d{1,3}[\s.-]?)?(?:\(?\d{2,4}\)?[\s.-]?){2,4}\d{2,4}(?![\w])")
PII_ID = re.compile(r"\b(?:cedula|cc|nit|pasaporte|passport|ssn|dni|documento)\b\s*[:#]?\s*\d[\d.\s-]{5,}", re.I)
_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}/\d{2,4}\b|\b\d{1,2}:\d{2}\b")


def recipe_request(text: str) -> str | None:
    """«formula» (pide la receta completa o con cantidades), «ingredient» (pide ingredientes de una receta de la casa) o None.
    Las preguntas de alérgenos («¿la salsa BBQ tiene soya?») NO cuentan: son información de seguridad del cliente."""
    clean = plain(text)
    if _ALLERGEN_CUE.search(clean):
        return None
    if _RECIPE_FORMULA.search(clean):
        return "formula"
    if _RECIPE_INGREDIENT.search(clean):
        return "ingredient"
    return None


def mentions_recipe(text: str) -> bool:
    return bool(_RECIPE_VOCAB.search(plain(text)))


def is_followup(text: str) -> bool:
    """Mensaje corto de seguimiento («¿y el siguiente?», «¿y cuánto?»): solo significa algo según de qué se venía hablando."""
    clean = plain(text).strip()
    return len(clean) <= 70 and bool(_FOLLOWUP.search(clean))


def commercial_request(text: str) -> bool:
    clean = plain(text)
    if not _COMMERCIAL.search(clean):
        return False
    # «¿cada cuánto paga el proveedor…?» no, pero «¿cuándo entrega el proveedor?» tampoco es precio: exige palabra de dinero.
    return not (_COMMERCIAL_BENIGN.search(clean) and not re.search(r"\b(?:costo|precio|tarifa|cobra\w*|pagamos|cuesta\w*|negociad\w*|contrato|"
                                                                  r"descuento|margen|price|cost|negotiated|contract)\b", clean))


def employee_request(text: str) -> bool:
    return bool(_EMPLOYEE.search(plain(text)))


def customer_pii_request(text: str) -> bool:
    clean = plain(text)
    return bool(_CUSTOMER_REQUEST.search(clean)) and not _INCIDENT_CONTEXT.search(clean)


def sensitive_request(text: str) -> str | None:
    """Motivo (código estable) si el mensaje PIDE algo de lo que nunca se revela, o None."""
    if commercial_request(text):
        return "confidential_commercial"
    if employee_request(text):
        return "employee_data"
    if customer_pii_request(text):
        return "customer_pii"
    return None


def sensitive_text_reasons(text: str, *, allowed: str = "") -> list[str]:
    """Lo prohibido que CONTIENE un texto (una respuesta del modelo o un hecho a guardar en memoria).
    `allowed`: texto del propio usuario; un correo o teléfono que ÉL escribió no se considera una fuga."""
    reasons: list[str] = []
    clean = plain(text)
    sentences = re.split(r"(?<=[.!?\n])\s+", clean)
    if len(_QUANTITY.findall(clean)) >= 2 and _RECIPE_VOCAB.search(clean):
        reasons.append("receta_con_cantidades")
    for sentence in sentences:
        if _MONEY.search(sentence) and re.search(rf"\b{_SUPPLIER_WORDS}\b", sentence) and re.search(rf"\b{_COMMERCIAL_WORDS}\b", sentence):
            reasons.append("precio_o_contrato_de_proveedor")
            break
    for sentence in sentences:
        if _SALARY_WORDS.search(sentence) and (_MONEY.search(sentence) or re.search(r"\d{3,}", sentence)):
            reasons.append("nomina_o_compensacion")
            break
    if re.search(r"\b(?:evaluacion|evaluaciones|review)\b.{0,30}\b(?:desempeno|performance)\b.{0,80}\b(?:de|of)\s+[a-z]{3,}", clean):
        reasons.append("evaluacion_de_desempeno")
    allowed_plain = plain(allowed)
    pii = [m for m in PII_EMAIL.findall(text) if plain(m) not in allowed_plain]
    pii += [m for m in PII_ID.findall(text) if plain(m) not in allowed_plain]
    for match in PII_PHONE.findall(_DATE.sub(" ", text)):
        digits = re.sub(r"\D", "", match)
        if len(digits) >= 7 and plain(match).strip() not in allowed_plain:
            pii.append(match)
    if pii:
        reasons.append("dato_personal_de_cliente")
    return reasons


def redact_pii(text: str, allowed: str = "") -> str:
    """Sustituye correos, documentos y teléfonos que NO escribió el propio manager (`allowed`) por un marcador."""
    allowed_plain = plain(allowed)
    mark = "[dato personal omitido]"

    def mask(match: re.Match) -> str:
        return match.group(0) if plain(match.group(0)).strip() in allowed_plain else mark

    def mask_phone(match: re.Match) -> str:
        digits = re.sub(r"\D", "", match.group(0))
        if len(digits) < 7 or _DATE.fullmatch(match.group(0).strip()):
            return match.group(0)
        return mask(match)

    return PII_PHONE.sub(mask_phone, PII_ID.sub(mask, PII_EMAIL.sub(mask, text)))
