"""Generador mínimo de PDF de texto (sin dependencias): Helvetica, codificación WinAnsi (acentos del español), A4, con saltos de página
explícitos. Existe para fabricar los contratos FICTICIOS de prueba; la lectura se hace con pdfplumber, que es lo que usaría un PDF real."""
from __future__ import annotations

import textwrap

PAGE_BREAK = "\f"
_W, _H, _MARGIN, _FS, _LEAD = 595, 842, 56, 10.5, 14
_LINES_PER_PAGE = int((_H - 2 * _MARGIN) / _LEAD)
_WRAP = 92


def _esc(line: str) -> bytes:
    data = line.encode("cp1252", errors="replace")
    return data.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def _pages(lines: list[str]) -> list[list[str]]:
    pages: list[list[str]] = [[]]
    for raw in lines:
        if raw == PAGE_BREAK:
            pages.append([])
            continue
        for part in (textwrap.wrap(raw, _WRAP) or [""]):
            if len(pages[-1]) >= _LINES_PER_PAGE:
                pages.append([])
            pages[-1].append(part)
    return [p for p in pages if p] or [[""]]


def build_pdf(lines: list[str]) -> bytes:
    pages = _pages(lines)
    objs: list[bytes] = []                      # índice 0 = objeto 1
    n = len(pages)
    kids = " ".join(f"{4 + 2 * i} 0 R" for i in range(n))
    objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objs.append(f"<< /Type /Pages /Kids [{kids}] /Count {n} >>".encode())
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    for i, page in enumerate(pages):
        content_id = 5 + 2 * i
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {_W} {_H}] /Resources << /Font << /F1 3 0 R >> >> /Contents {content_id} 0 R >>".encode())
        stream = [f"BT /F1 {_FS} Tf {_LEAD} TL {_MARGIN} {_H - _MARGIN} Td".encode()]
        for line in page:
            stream.append(b"(" + _esc(line) + b") Tj T*")
        stream.append(b"ET")
        body = b"\n".join(stream)
        objs.append(f"<< /Length {len(body)} >>\nstream\n".encode() + body + b"\nendstream")
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)
