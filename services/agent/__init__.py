"""Agente de Brasaland (LangGraph, Parte 1): el flujo del RAG como grafo explícito, con estado, nodos y aristas.

No reescribe el RAG: los nodos llaman a `retrieve()` y `generate_answer()` de `data/pipelines/rag.py`.

    state.py      estado mínimo del grafo
    nodes.py      nodos de una sola responsabilidad y funciones de enrutamiento (aristas condicionales)
    graph.py      construcción, compilación explícita y checkpointer
    tracing.py    trace consultable de cada corrida
    service.py    `AgentService`: compila el grafo una vez y ejecuta corridas con trace y checkpoints
    router.py     endpoint `POST /agent/query` (solo invoca el servicio)
"""
