"""Extrae, a medida que llega, el texto visible de la respuesta.

Con la memoria activada el modelo no responde con texto plano sino con JSON (`{"respuesta": "...", "propuesta_memoria": ...}`).
El usuario solo debe ver el valor de `respuesta`, y verlo mientras se escribe: este extractor decodifica el JSON de forma
incremental. Con texto plano (sin memoria, respuestas casuales o de seguridad) lo deja pasar tal cual. Cualquier otro JSON (p. ej. el
clasificador de intención de la memoria) no tiene `respuesta`, así que no produce texto visible.
"""
from __future__ import annotations

import re

_KEY = re.compile(r'"respuesta"\s*:\s*"')
_SIMPLE_ESCAPES = {'"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t"}


class VisibleTextExtractor:
    def __init__(self) -> None:
        self._raw = ""
        self._emitted = 0

    def feed(self, delta: str) -> str:
        """Devuelve el texto visible NUEVO que aporta `delta` (cadena vacía si aún no hay nada que mostrar)."""
        self._raw += delta
        visible = self._visible()
        new = visible[self._emitted:]
        self._emitted = len(visible)
        return new

    def _visible(self) -> str:
        head = self._raw.lstrip()
        if not head:
            return ""
        if not (head.startswith("{") or head.startswith("```")):
            return self._raw  # texto plano
        match = _KEY.search(self._raw)
        if match is None:
            return ""
        out: list[str] = []
        i = match.end()
        raw = self._raw
        while i < len(raw):
            ch = raw[i]
            if ch == '"':
                break  # fin del valor
            if ch != "\\":
                out.append(ch)
                i += 1
                continue
            if i + 1 >= len(raw):
                break  # escape cortado entre dos fragmentos: se espera al siguiente
            esc = raw[i + 1]
            if esc == "u":
                code = raw[i + 2:i + 6]
                if len(code) < 4:
                    break
                try:
                    out.append(chr(int(code, 16)))
                except ValueError:
                    out.append("�")
                i += 6
            else:
                out.append(_SIMPLE_ESCAPES.get(esc, esc))
                i += 2
        return "".join(out)
