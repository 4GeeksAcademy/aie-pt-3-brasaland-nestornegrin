"""Servidor MCP de Brasaland: expone el gestor de incidentes (tickets) y el inventario (solo lectura) a cualquier
cliente MCP autorizado, protegido con OAuth 2.1 (MCP Auth) y con scopes de mínimo privilegio por tool.

Mapa del módulo:

    config.py      variables de entorno (issuer OAuth, audience, backend, timeouts, logs)
    domain.py      valores de dominio (estados, orígenes, sedes, categorías) idénticos a los de las APIs reales
    errors.py      catálogo de códigos de error y `McpToolError`
    backend.py     clientes HTTP del backend propio (el inventario SOLO puede hacer GET)
    tools.py       las tools MCP (contrato de entrada/salida y descripción para el discovery)
    middleware.py  auditoría (un log por invocación) y guardia de solo lectura del inventario
    server.py      FastMCP + MCP Auth (Protected Resource Metadata, JWT bearer) montados en una app ASGI
    __main__.py    `python -m mcps.brasaland_mcp` levanta el servidor
"""
