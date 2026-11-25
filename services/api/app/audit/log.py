"""Almacén APPEND-ONLY del audit log, con cadena de hash para que cualquier alteración posterior sea detectable.

Propiedades (todas verificadas en tests/test_audit_log.py):
  * Solo existen operaciones de AÑADIR y de LEER. La clase no tiene `update`, `delete`, `truncate` ni nada equivalente, y la API
    no expone ninguna ruta que no sea GET sobre el registro. No hay forma de modificar ni borrar una entrada desde la aplicación.
  * Encadenamiento: `hash = HMAC-SHA256(clave, prev_hash | contenido canónico)`. Editar, borrar o reordenar una entrada rompe la cadena
    desde ese punto. Al llevar HMAC, quien tenga el fichero pero no la clave del servidor no puede recalcular una cadena válida.
  * `audit_head.json` guarda (seq, hash) de la última entrada, firmado con la misma clave: detecta que borren el final o todo el fichero.
  * Escritura atómica (O_APPEND + flock entre procesos + fsync): API, workers y trabajos nocturnos pueden añadir a la vez.

Límite honesto: quien controle el servidor Y su clave puede reescribirlo todo. Para ese caso hay que anclar el último hash fuera
(almacenamiento WORM o un export periódico del `head_hash` que devuelve `GET /audit-log/verify`).
"""

from __future__ import annotations

import fcntl
import hashlib
import hmac
import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

from .models import GENESIS_HASH, AuditEntry, VerifyResult

SECRET_KEY_FRAGMENTS = ("password", "token", "secret", "authorization", "cookie")
MAX_DETAIL_VALUE = 300


class AuditIntegrityError(RuntimeError):
    """El final del registro no es legible: añadir encima ocultaría la alteración, así que se falla en voz alta."""


def sanitize_details(details: dict[str, Any] | None) -> dict[str, Any]:
    """Solo datos simples y cortos; nunca contraseñas, tokens ni secretos (por si alguien los pasa por error)."""
    clean: dict[str, Any] = {}
    for key, value in (details or {}).items():
        if any(fragment in key.lower() for fragment in SECRET_KEY_FRAGMENTS):
            continue
        if isinstance(value, dict):
            clean[key] = sanitize_details(value)
        elif isinstance(value, (list, tuple)):
            clean[key] = [str(v)[:MAX_DETAIL_VALUE] for v in value][:50]
        elif isinstance(value, (int, float, bool)) or value is None:
            clean[key] = value
        else:
            clean[key] = str(value)[:MAX_DETAIL_VALUE]
    return clean


def _derive_key(explicit: bytes | str | None) -> bytes:
    raw = explicit or os.environ.get("AUDIT_CHAIN_KEY") or os.environ.get("JWT_SECRET_KEY")
    if not raw:
        raise RuntimeError("El audit log necesita AUDIT_CHAIN_KEY (o JWT_SECRET_KEY) para firmar la cadena.")
    material = raw if isinstance(raw, bytes) else raw.encode()
    return hmac.new(material, b"brasaland-audit-chain-v1", hashlib.sha256).digest()


def _canonical(data: dict[str, Any]) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


class AuditLog:
    """Colección append-only en JSON Lines (`audit_log.jsonl`) + cabeza firmada (`audit_head.json`)."""

    def __init__(self, path: Path, head_path: Path | None = None, key: bytes | str | None = None) -> None:
        self._path = Path(path)
        self._head_path = Path(head_path) if head_path else self._path.with_name("audit_head.json")
        self._key = _derive_key(key)
        self._thread_lock = threading.Lock()

    # ------------------------------------------------------------------ firma
    def _mac(self, prev_hash: str, body: dict[str, Any]) -> str:
        return hmac.new(self._key, f"{prev_hash}|{_canonical(body)}".encode(), hashlib.sha256).hexdigest()

    def _head_mac(self, seq: int, entry_hash: str) -> str:
        return hmac.new(self._key, f"head|{seq}|{entry_hash}".encode(), hashlib.sha256).hexdigest()

    # ------------------------------------------------------------------ añadir (única operación de escritura)
    def append(self, *, actor_type: str, actor_id: str, action: str, category: str, resource_type: str, origin: str,
               resource_id: str | None = None, department: str | None = None, outcome: str = "success", channel: str = "http",
               actor_label: str | None = None, actor_role: str | None = None, actor_department: str | None = None,
               details: dict[str, Any] | None = None) -> AuditEntry:
        with self._thread_lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(self._path, os.O_RDWR | os.O_CREAT | os.O_APPEND, 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)  # exclusión entre procesos mientras se lee la cola y se escribe
                prev_seq, prev_hash = self._read_tail(fd)
                body: dict[str, Any] = {
                    "seq": prev_seq + 1, "id": str(uuid.uuid4()), "timestamp": datetime.now(timezone.utc).isoformat(),
                    "actor_type": actor_type, "actor_id": str(actor_id), "actor_label": actor_label, "actor_role": actor_role,
                    "actor_department": actor_department, "action": action, "category": category, "resource_type": resource_type,
                    "resource_id": None if resource_id is None else str(resource_id), "department": department, "outcome": outcome,
                    "origin": origin, "channel": channel, "details": sanitize_details(details), "prev_hash": prev_hash,
                }
                # El hash se calcula sobre la forma EXACTA que se guarda (fechas normalizadas por el modelo), no sobre `body`.
                stored = AuditEntry.model_validate({**body, "hash": ""}).model_dump(mode="json")
                stored.pop("hash")
                entry = AuditEntry.model_validate({**stored, "hash": self._mac(prev_hash, stored)})
                os.write(fd, (_canonical(entry.model_dump(mode="json")) + "\n").encode())
                os.fsync(fd)
                self._write_head(entry.seq, entry.hash)
                return entry
            finally:
                os.close(fd)  # libera también el flock

    def _read_tail(self, fd: int) -> tuple[int, str]:
        """(seq, hash) de la última entrada, leyendo desde el final sin cargar el fichero entero."""
        size = os.fstat(fd).st_size
        if size == 0:
            return 0, GENESIS_HASH
        chunk, data, position = 8192, b"", size
        while position > 0 and data.count(b"\n") < 2:
            step = min(chunk, position)
            position -= step
            data = os.pread(fd, step, position) + data
        last_line = data.rstrip(b"\n").rsplit(b"\n", 1)[-1]
        try:
            last = json.loads(last_line)
            return int(last["seq"]), str(last["hash"])
        except (ValueError, KeyError, TypeError) as error:
            raise AuditIntegrityError("La última entrada del audit log es ilegible: se rechaza escribir encima.") from error

    def _write_head(self, seq: int, entry_hash: str) -> None:
        tmp = self._head_path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"seq": seq, "hash": entry_hash, "mac": self._head_mac(seq, entry_hash)}))
        os.replace(tmp, self._head_path)

    # ------------------------------------------------------------------ leer
    def iter_entries(self) -> Iterator[AuditEntry]:
        """Todas las entradas en orden de escritura (sin validar la cadena: para eso está `verify`)."""
        if not self._path.exists():
            return
        with self._path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    try:
                        yield AuditEntry.model_validate_json(line)
                    except ValueError:
                        continue  # línea dañada: `verify` la señala; la lectura sigue siendo posible

    def query(self, *, visible: Callable[[AuditEntry], bool] | None = None, actor: str | None = None, actor_type: str | None = None,
              action: str | None = None, category: str | None = None, resource_type: str | None = None, resource_id: str | None = None,
              department: str | None = None, outcome: str | None = None, date_from: datetime | None = None, date_to: datetime | None = None,
              before_seq: int | None = None, limit: int = 50) -> tuple[list[AuditEntry], int, int | None]:
        """(página, total de coincidencias, cursor). Orden: la más reciente primero. `visible` impone el alcance del usuario."""
        needle = actor.lower() if actor else None
        matches: list[AuditEntry] = []
        for entry in self.iter_entries():
            if visible and not visible(entry):
                continue
            if needle and needle not in entry.actor_id.lower() and needle not in (entry.actor_label or "").lower():
                continue
            if actor_type and entry.actor_type != actor_type or category and entry.category != category:
                continue
            if action and entry.action != action or resource_type and entry.resource_type != resource_type:
                continue
            if resource_id and (entry.resource_id or "") != resource_id or department and entry.department != department:
                continue
            if outcome and entry.outcome != outcome:
                continue
            if date_from and entry.timestamp < _aware(date_from) or date_to and entry.timestamp > _aware(date_to):
                continue
            matches.append(entry)
        matches.reverse()
        total = len(matches)
        if before_seq is not None:
            matches = [e for e in matches if e.seq < before_seq]
        page = matches[:limit]
        next_cursor = page[-1].seq if len(matches) > limit and page else None
        return page, total, next_cursor

    def facets(self, visible: Callable[[AuditEntry], bool]) -> tuple[list[str], list[str], list[str]]:
        actions, resources, categories = set(), set(), set()
        for entry in self.iter_entries():
            if visible(entry):
                actions.add(entry.action)
                resources.add(entry.resource_type)
                categories.add(entry.category)
        return sorted(actions), sorted(resources), sorted(categories)

    # ------------------------------------------------------------------ evidencia de alteración
    def verify(self) -> VerifyResult:
        """Recorre TODA la cadena y la cabeza firmada. `valid=False` indica la primera entrada alterada, borrada o reordenada."""
        prev_hash, count, head_seq = GENESIS_HASH, 0, 0
        if self._path.exists():
            with self._path.open("r", encoding="utf-8") as handle:
                for number, line in enumerate(handle, start=1):
                    if not line.strip():
                        continue
                    try:
                        raw = json.loads(line)
                        stored_hash = raw.pop("hash")
                        seq = int(raw["seq"])
                        AuditEntry.model_validate({**raw, "hash": stored_hash})
                    except (ValueError, KeyError, TypeError):
                        return VerifyResult(valid=False, entries=count, head_seq=head_seq, head_hash=prev_hash,
                                            broken_at_seq=count + 1, reason=f"línea {number} ilegible o con campos inválidos")
                    if seq != count + 1:
                        return VerifyResult(valid=False, entries=count, head_seq=head_seq, head_hash=prev_hash, broken_at_seq=seq,
                                            reason=f"la secuencia salta de {count} a {seq} (entradas borradas o reordenadas)")
                    if raw.get("prev_hash") != prev_hash:
                        return VerifyResult(valid=False, entries=count, head_seq=head_seq, head_hash=prev_hash, broken_at_seq=seq,
                                            reason="prev_hash no coincide con la entrada anterior")
                    if not hmac.compare_digest(self._mac(prev_hash, raw), stored_hash):
                        return VerifyResult(valid=False, entries=count, head_seq=head_seq, head_hash=prev_hash, broken_at_seq=seq,
                                            reason="el contenido de la entrada fue alterado (el hash no coincide)")
                    prev_hash, count, head_seq = stored_hash, count + 1, seq
        head = self._read_head()
        if head is None:
            if count:
                return VerifyResult(valid=False, entries=count, head_seq=head_seq, head_hash=prev_hash, broken_at_seq=count,
                                    reason="falta la cabeza firmada (audit_head.json)")
        elif (head["seq"], head["hash"]) != (head_seq, prev_hash):
            return VerifyResult(valid=False, entries=count, head_seq=head_seq, head_hash=prev_hash, broken_at_seq=min(count, head["seq"]) + 1,
                                reason="la cabeza firmada no coincide con el final del registro (entradas finales borradas)")
        return VerifyResult(valid=True, entries=count, head_seq=head_seq, head_hash=prev_hash)

    def _read_head(self) -> dict[str, Any] | None:
        try:
            head = json.loads(self._head_path.read_text())
            seq, entry_hash = int(head["seq"]), str(head["hash"])
            if not hmac.compare_digest(self._head_mac(seq, entry_hash), str(head["mac"])):
                return {"seq": -1, "hash": "firma de la cabeza inválida"}
            return {"seq": seq, "hash": entry_hash}
        except (OSError, ValueError, KeyError, TypeError):
            return None


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
