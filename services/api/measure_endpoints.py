"""Mide la latencia de los endpoints de lectura de un API en marcha.

Uso (con el API arrancado, p. ej. sobre los datos de seed_load.py):

    python measure_endpoints.py --label antes --requests 40 --out antes.json

Registra (o reutiliza) un usuario de prueba, inicia sesión y lanza N peticiones
seguidas a cada endpoint. Informa de la mediana y el p95 del tiempo de servidor
(cabecera X-Process-Time-Ms, sin red) y del tamaño de la respuesta. Solo usa la
biblioteca estándar. Las peticiones son secuenciales: miden coste por petición,
no rendimiento bajo concurrencia.
"""

from __future__ import annotations

import argparse
import json
import statistics
import urllib.error
import urllib.request

ENDPOINTS = [
    ("GET /api/suppliers", "/api/suppliers"),
    ("GET /api/suppliers?country=Colombia&category=Carnes", "/api/suppliers?country=Colombia&category=Carnes"),
    ("GET /api/suppliers/1", "/api/suppliers/1"),
    ("GET /api/incidents", "/api/incidents"),
    ("GET /api/incidents?status=open", "/api/incidents?status=open"),
    ("GET /api/incidents/summary", "/api/incidents/summary"),
    ("GET /auth/me", "/auth/me"),
]


def request(base: str, method: str, path: str, token: str | None = None, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method)
    req.add_header("content-type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req) as response:
            return response.status, response.read(), {k.lower(): v for k, v in response.headers.items()}
    except urllib.error.HTTPError as error:
        return error.code, error.read(), dict(error.headers)


def percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(pct / 100 * (len(ordered) - 1)))]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", default="http://localhost:8000")
    parser.add_argument("--requests", type=int, default=40)
    parser.add_argument("--label", default="medicion")
    parser.add_argument("--email", default="medicion@example.com")
    parser.add_argument("--password", default="ValidPass123")
    parser.add_argument("--inventory", action="store_true", help="medir también /inventory (requiere Postgres con datos)")
    parser.add_argument("--out", help="guardar los resultados en este fichero JSON")
    args = parser.parse_args()

    request(args.base, "POST", "/users", body={"email": args.email, "password": args.password, "name": "Medicion"})
    status, body, _ = request(args.base, "POST", "/auth/login", body={"email": args.email, "password": args.password})
    if status != 200:
        raise SystemExit(f"No se pudo iniciar sesión ({status}): {body[:200]!r}")
    token = json.loads(body)["access_token"]

    results = []
    endpoints = ENDPOINTS + ([("GET /inventory/products", "/inventory/products"), ("GET /inventory/orders", "/inventory/orders")] if args.inventory else [])
    for name, path in endpoints:
        times, size = [], 0
        for _ in range(args.requests):
            status, payload, headers = request(args.base, "GET", path, token)
            if status != 200:
                raise SystemExit(f"{name} respondió {status}")
            times.append(float(headers.get("x-process-time-ms", "nan")))
            size = len(payload)
        results.append({
            "endpoint": name,
            "first_ms": times[0],
            "median_ms": round(statistics.median(times), 1),
            "p95_ms": round(percentile(times, 95), 1),
            "size_kb": round(size / 1024, 1),
        })

    print(f"\n### {args.label} ({args.requests} peticiones por endpoint, tiempo de servidor en ms)\n")
    print("| Endpoint | 1.ª petición | Mediana | p95 | Respuesta |")
    print("|---|---:|---:|---:|---:|")
    for row in results:
        print(f"| `{row['endpoint']}` | {row['first_ms']:.1f} | {row['median_ms']} | {row['p95_ms']} | {row['size_kb']} KB |")
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            json.dump({"label": args.label, "requests": args.requests, "results": results}, handle, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()
