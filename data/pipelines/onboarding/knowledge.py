"""Material oficial de onboarding: carga, presentación adaptada al puesto y consulta de dudas.

Es la ÚNICA fuente del agente. Cada documento es un Markdown con secciones `## Título [dept=Marketing] [sede=Miami]`; las etiquetas
dicen para quién es la sección (sin etiqueta: para todos). Presentar = elegir las secciones de la etapa que aplican a la persona.

Consulta de dudas (`consult`): índice TF-IDF (scikit-learn, sin red ni modelo) sobre TODAS las secciones. La respuesta es EXTRACTIVA: se
devuelven frases literales del documento y su fuente; nunca se redacta nada nuevo, así que no puede inventar. Si la mejor sección no
cubre la pregunta (puntuación o cobertura de términos insuficiente), se reconoce que el material no la cubre y se deriva a una persona."""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from . import config
from .config import normalize
from .sensitive import asks_about_own_sensitive_data

_HEADING = re.compile(r"^##\s+(?P<title>.*?)\s*(?P<tags>(?:\[[^\]]+\]\s*)*)$")
_TAG = re.compile(r"\[(?P<key>dept|sede)=(?P<value>[^\]]+)\]")
_STOP = set(normalize(w) for w in """
a al algo ante con como cual cuales cuando cuanto cuantos cuanta cuantas de del desde donde el ella ellos en entre era es esta estan este esto
fue ha han hay la las le les lo los me mi mis muy no nos o para pero por que se si sin sobre su sus te tu tus un una uno unos unas y ya yo
puedo puede pueden debo debe deben hacer hace tiene tienen tengo quien quienes cual cuales es son ser estar""".split())
MIN_SCORE = 0.12          # similitud coseno mínima de la mejor sección
MIN_COVERAGE = 0.6        # fracción mínima de los términos de la pregunta que debe aparecer en esa sección


def slugify(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", normalize(title)).strip("-")


@dataclass(frozen=True)
class Section:
    document: str                    # clave del documento: "etapa-2-la-empresa"
    document_title: str
    id: str                          # slug del título
    title: str
    body: str
    tags: dict = field(default_factory=dict)  # {"dept": "...", "sede": "..."}

    @property
    def ref(self) -> str:
        return f"{self.document}#{self.id}"

    @property
    def label(self) -> str:
        return f"{self.document_title} › {self.title}"

    def applies_to(self, department: str, site: str) -> bool:
        if "dept" in self.tags and normalize(self.tags["dept"]) != normalize(department):
            return False
        if "sede" in self.tags and normalize(self.tags["sede"]) != normalize(site):
            return False
        return True


def parse_document(key: str, text: str) -> list[Section]:
    lines = text.splitlines()
    title = next((line[2:].strip() for line in lines if line.startswith("# ")), key)
    sections: list[Section] = []
    current: dict | None = None
    for line in lines:
        match = _HEADING.match(line)
        if match:
            if current:
                sections.append(_build(key, title, current))
            tags = {m.group("key"): m.group("value").strip() for m in _TAG.finditer(match.group("tags") or "")}
            current = {"title": match.group("title").strip(), "tags": tags, "body": []}
        elif current is not None:
            current["body"].append(line)
    if current:
        sections.append(_build(key, title, current))
    return sections


def _build(key: str, doc_title: str, raw: dict) -> Section:
    return Section(document=key, document_title=doc_title, id=slugify(raw["title"]), title=raw["title"],
                   body="\n".join(raw["body"]).strip(), tags=raw["tags"])


@lru_cache(maxsize=4)
def load_documents(kb_dir: str | None = None) -> dict[str, tuple[Section, ...]]:
    directory = Path(kb_dir) if kb_dir else config.KB_DIR
    documents = {}
    for path in sorted(directory.glob("*.es.md")):
        key = path.name[: -len(".es.md")]
        documents[key] = tuple(parse_document(key, path.read_text(encoding="utf-8")))
    return documents


def all_sections(kb_dir: str | None = None) -> list[Section]:
    return [section for sections in load_documents(kb_dir).values() for section in sections]


def document_key_for(stage: config.Stage, variant: str | None) -> str | None:
    if stage.document is None:
        return None
    return f"{stage.document}-{variant}" if stage.number == 5 else stage.document


def stage_sections(stage: config.Stage, variant: str | None, department: str, site: str, kb_dir: str | None = None) -> list[Section]:
    """Presentación adaptada al puesto: las secciones comunes de la etapa más las de su departamento y sede."""
    key = document_key_for(stage, variant)
    if key is None:
        return []
    return [section for section in load_documents(kb_dir).get(key, ()) if section.applies_to(department, site)]


def find_section(ref: str, kb_dir: str | None = None) -> Section | None:
    document, _, section_id = ref.partition("#")
    return next((s for s in load_documents(kb_dir).get(document, ()) if s.id == section_id), None)


# ------------------------------------------------------------------------------------------------------------ consulta de dudas
def _stem(word: str) -> str:
    return word[:5]


def keywords(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", normalize(text)) if w not in _STOP and len(w) > 1]


@dataclass(frozen=True)
class Answer:
    answered: bool
    text: str
    sources: tuple[str, ...] = ()
    reason: str = ""            # por qué se deriva: "sensible" | "fuera_del_material"


def _tokens(text: str) -> list[str]:
    words = keywords(text)
    return [_stem(w) for w in words] + words


class _Index:
    """TF-IDF en Python puro (mismas fórmulas que scikit-learn: tf sublineal, idf suavizado, norma L2): sin dependencias de modelos ni de red."""

    def __init__(self, sections: list[Section]):
        self.sections = sections
        documents = [Counter(_tokens(f"{s.title}. {s.title}. {s.body}")) for s in sections]
        frequency = Counter(term for doc in documents for term in doc)
        n = len(documents)
        self.idf = {term: math.log((1 + n) / (1 + df)) + 1 for term, df in frequency.items()}
        self.vectors = [self._weigh(doc) for doc in documents]
        self.stems = [{_stem(w) for w in keywords(f"{s.title} {s.body}")} for s in sections]

    def _weigh(self, counts: Counter) -> dict[str, float]:
        weights = {t: (1 + math.log(c)) * self.idf[t] for t, c in counts.items() if t in self.idf}
        norm = math.sqrt(sum(w * w for w in weights.values())) or 1.0
        return {t: w / norm for t, w in weights.items()}

    def scores(self, question: str) -> list[float]:
        query = self._weigh(Counter(_tokens(question)))
        return [sum(w * vector.get(t, 0.0) for t, w in query.items()) for vector in self.vectors]


@lru_cache(maxsize=2)
def _index(kb_dir: str | None = None) -> _Index:
    return _Index(all_sections(kb_dir))


def consult(question: str, department: str | None = None, site: str | None = None, kb_dir: str | None = None) -> Answer:
    """Responde SOLO con el material oficial citando la fuente; si no está cubierto, lo reconoce y lo deriva (nunca rellena)."""
    if asks_about_own_sensitive_data(question):
        return Answer(False, "Esa información es personal y la gestiona el equipo de Personas: este asistente no la tiene ni puede consultarla. "
                             "He dejado tu pregunta para Personas.", reason="sensible")
    terms = keywords(question)
    if not terms:
        return Answer(False, "No he entendido la pregunta. He dejado la duda para Personas.", reason="fuera_del_material")
    index = _index(kb_dir)
    scores = index.scores(question)
    order = sorted(range(len(scores)), key=lambda i: -scores[i])
    best = None
    for i in order[:5]:
        section = index.sections[i]
        if department and site and not section.applies_to(department, site):
            continue
        best = (i, section, float(scores[i]))
        break
    if best is None or best[2] < MIN_SCORE:
        return _not_covered()
    i, section, score = best
    coverage = sum(1 for w in terms if _stem(w) in index.stems[i]) / len(terms)
    if coverage < MIN_COVERAGE:
        return _not_covered()
    sentences = _best_sentences(section.body, terms)
    return Answer(True, " ".join(sentences) or section.body[:400], (section.ref,))


def _not_covered() -> Answer:
    return Answer(False, "El material oficial de onboarding no cubre esa duda, así que no voy a inventar una respuesta. "
                         "He dejado tu pregunta para Personas (Ashley Turner), que te responderá.", reason="fuera_del_material")


def _best_sentences(body: str, terms: list[str], limit: int = 3) -> list[str]:
    pieces = [p.strip(" -*\n") for p in re.split(r"(?<=[.!?])\s+|\n+", body) if p.strip(" -*\n")]
    wanted = {_stem(w) for w in terms}
    scored = sorted(range(len(pieces)), key=lambda i: -len(wanted & {_stem(w) for w in keywords(pieces[i])}))
    chosen = [i for i in scored[:limit] if wanted & {_stem(w) for w in keywords(pieces[i])}]
    return [pieces[i] for i in sorted(chosen)]
