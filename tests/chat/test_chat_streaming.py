"""Chat en vivo del Manager support agent (Hito 10 · Parte 2): contrato de eventos, interrupción REAL, turno nuevo y rehidratación.

Todo con el `AgentService` real (grafo de LangGraph) y un proveedor de LLM falso con streaming controlable: sin red ni claves.
"""
from __future__ import annotations

import asyncio
import json
import time

import pytest

from chat_support import FakeProvider, FakeStream, collect, install_provider, make_manager, names, real_agent_service
from data.pipelines import rag
from data.pipelines.streaming import GenerationCancelled, StreamSink, use_sink
from services.agent.chat.broker import ChatBroker, channel_for
from services.agent.chat.extract import VisibleTextExtractor
from services.agent.chat.store import MESSAGE_COMPLETED, MESSAGE_INTERRUPTED, SESSION_INTERRUPTED

SESSION = "chat_0044"


def words(text: str) -> list[str]:
    return [piece for piece in text.replace(" ", " \u0000").split("\u0000") if piece]


# ---------------------------------------------------------------- extractor de texto visible
def feed_all(extractor: VisibleTextExtractor, pieces: list[str]) -> str:
    return "".join(extractor.feed(piece) for piece in pieces)


def test_texto_plano_pasa_tal_cual():
    assert feed_all(VisibleTextExtractor(), ["Para ", "Miami ", "es martes."]) == "Para Miami es martes."


def test_json_de_memoria_solo_muestra_la_respuesta_aunque_los_trozos_corten_escapes():
    raw = json.dumps({"respuesta": "Línea 1\n\"Miami\" é", "propuesta_memoria": None}, ensure_ascii=False)
    raw = raw.replace("é", "\\u00e9")
    for size in (1, 2, 3, 7):
        pieces = [raw[i:i + size] for i in range(0, len(raw), size)]
        assert feed_all(VisibleTextExtractor(), pieces) == 'Línea 1\n"Miami" é'


def test_json_del_clasificador_no_produce_texto_visible():
    assert feed_all(VisibleTextExtractor(), ['{"decision": ', '"confirmar"}']) == ""


# ---------------------------------------------------------------- gancho de streaming en rag.complete
def test_sin_sink_complete_no_hace_streaming(monkeypatch):
    provider = FakeProvider(lambda q: FakeStream(["Hola ", "mundo"]))
    install_provider(monkeypatch, provider)
    assert rag.complete([{"role": "user", "content": "PREGUNTA:\nhola"}]) == "Hola mundo"
    assert provider.blocking_calls == 1


def test_con_sink_entrega_cada_fragmento_y_devuelve_el_texto_completo(monkeypatch):
    provider = FakeProvider(lambda q: FakeStream(["Hola ", "mundo"]))
    install_provider(monkeypatch, provider)
    received: list[str] = []
    with use_sink(StreamSink(received.append)):
        assert rag.complete([{"role": "user", "content": "PREGUNTA:\nhola"}]) == "Hola mundo"
    assert received == ["Hola ", "mundo"] and provider.blocking_calls == 0


def test_cancelar_cierra_el_stream_del_proveedor_y_deja_de_consumir(monkeypatch):
    stream = FakeStream([f"t{i} " for i in range(50)])
    install_provider(monkeypatch, FakeProvider(lambda q: stream))
    received: list[str] = []
    sink = StreamSink(lambda delta: (received.append(delta), sink.cancel() if len(received) == 3 else None))
    with use_sink(sink), pytest.raises(GenerationCancelled):
        rag.complete([{"role": "user", "content": "PREGUNTA:\nhola"}])
    assert stream.closed and len(received) == 3 and stream.produced < 50


# ---------------------------------------------------------------- contrato de eventos con el agente real
def test_token_chunk_en_orden_y_generation_completed(monkeypatch, tmp_path):
    answer = "El proveedor de Miami entrega los martes."
    provider = FakeProvider(lambda q: FakeStream(words(answer)))
    install_provider(monkeypatch, provider)
    manager = make_manager(real_agent_service(tmp_path))

    async def scenario():
        manager.open_session(SESSION, "7", "loc_miami")
        snapshot, sub = manager.attach(SESSION)
        assert snapshot == {"session_id": SESSION, "messages": []}  # sesión nueva: snapshot vacío, pero existe
        manager.submit(SESSION, "¿Cuándo entrega el proveedor de Miami?", "7")
        return await collect(sub, "generation_completed")

    events = asyncio.run(scenario())
    assert names(events)[0] == "user_message" and names(events)[-1] == "generation_completed"
    chunks = [e for e in events if e["event"] == "token_chunk"]
    assert [c["data"]["sequence"] for c in chunks] == list(range(1, len(chunks) + 1))
    assert "".join(c["data"]["token"] for c in chunks) == answer
    assert all(e["data"]["session_id"] == SESSION for e in events)
    assert provider.blocking_calls == 0 and len(chunks) == len(words(answer))  # streaming real hasta el hilo del nodo de LangGraph
    completed = events[-1]["data"]
    assert set(completed) == {"session_id", "message_id"}
    stored = manager.store.messages(SESSION)
    assert [m["role"] for m in stored] == ["user", "assistant"]
    assert stored[1]["text"] == answer and stored[1]["status"] == MESSAGE_COMPLETED and stored[1]["message_id"] == completed["message_id"]


def test_interrumpir_aborta_el_stream_conserva_el_parcial_y_abre_un_turno_nuevo(monkeypatch, tmp_path):
    long_stream = FakeStream(words("El proveedor de Chicago entrega los lunes y los jueves por la mañana temprano."), gate_after=3)

    def script(question: str) -> FakeStream:
        if "Chicago" in question or "dónde" in question:
            return long_stream
        return FakeStream(words(f"Entendido, hablamos de Miami: {question}"))

    provider = FakeProvider(script)
    install_provider(monkeypatch, provider)
    manager = make_manager(real_agent_service(tmp_path))

    async def scenario():
        manager.open_session(SESSION, "7", "loc_miami")
        _, sub = manager.attach(SESSION)
        manager.submit(SESSION, "¿Cuándo entrega el proveedor de Chicago?", "7")
        first = await collect(sub, "token_chunk", count=3)  # se muestran 3 tokens del primer intento…
        assert await asyncio.to_thread(long_stream.reached_gate.wait, 5)  # …el proveedor sigue generando
        manager.submit(SESSION, "espera, pregunté por el local de Miami", "7")  # INTERRUPCIÓN
        long_stream.gate.set()  # el proveedor «seguiría» generando si nadie lo hubiera cerrado
        rest = await collect(sub, "generation_completed")
        return first + rest

    events = asyncio.run(scenario())
    order = names(events)
    # 1) secuencia de eventos del contrato
    assert order.index("interrupt_requested") < order.index("generation_interrupted") < order.index("user_message", order.index("interrupt_requested"))
    interrupted = next(e for e in events if e["event"] == "generation_interrupted")["data"]
    assert interrupted["status"] == "interrupted"
    requested = next(e for e in events if e["event"] == "interrupt_requested")["data"]
    assert requested["new_input"] == "espera, pregunté por el local de Miami"
    # 2) el aborto es REAL: tras `generation_interrupted` no hay ni un token del primer intento y el stream del proveedor se cerró
    cut = order.index("generation_interrupted")
    old_tokens = [e["data"]["token"] for e in events[:cut] if e["event"] == "token_chunk"]
    assert len(old_tokens) == 3
    deadline = time.time() + 5
    while not long_stream.closed and time.time() < deadline:
        time.sleep(0.01)
    assert long_stream.closed and long_stream.produced <= 4
    # 3) el parcial queda marcado `interrupted` con lo que se mostró, y el turno siguiente es OTRO mensaje que refleja `new_input`
    stored = manager.store.messages(SESSION)
    partial = next(m for m in stored if m["message_id"] == interrupted["message_id"])
    assert partial["status"] == MESSAGE_INTERRUPTED and partial["text"] == "".join(old_tokens)
    new_turn = [m for m in stored if m["role"] == "assistant" and m["message_id"] != interrupted["message_id"]]
    assert len(new_turn) == 1 and new_turn[0]["status"] == MESSAGE_COMPLETED
    assert "Miami" in new_turn[0]["text"] and "espera, pregunté por el local de Miami" in provider.questions[-1]
    assert events[-1]["data"]["message_id"] == new_turn[0]["message_id"]
    assert manager.store.get_session(SESSION)["status"] == "active"
    # ningún token posterior al corte pertenece al mensaje interrumpido (el texto guardado no creció)
    assert next(m for m in manager.store.messages(SESSION) if m["message_id"] == interrupted["message_id"])["text"] == partial["text"]


def test_estado_de_sesion_es_interrupted_al_abortar(monkeypatch, tmp_path):
    stream = FakeStream(words("uno dos tres cuatro cinco seis"), gate_after=2)
    install_provider(monkeypatch, FakeProvider(lambda q: stream if "primera" in q else FakeStream(["ok"])))
    manager = make_manager(real_agent_service(tmp_path))

    async def scenario():
        manager.open_session(SESSION, "7", None)
        _, sub = manager.attach(SESSION)
        manager.submit(SESSION, "primera", "7")
        await collect(sub, "token_chunk", count=2)
        manager._abort(manager._generations[SESSION])
        stream.gate.set()

    asyncio.run(scenario())
    assert manager.store.get_session(SESSION)["status"] == SESSION_INTERRUPTED


# ---------------------------------------------------------------- varios clientes, una sola ejecución del agente
def test_varios_suscriptores_reciben_los_mismos_eventos_con_una_sola_llamada_al_agente(monkeypatch, tmp_path):
    provider = FakeProvider(lambda q: FakeStream(words("Respuesta común para todos.")))
    install_provider(monkeypatch, provider)
    manager = make_manager(real_agent_service(tmp_path))

    async def scenario():
        manager.open_session(SESSION, "7", None)
        _, owner = manager.attach(SESSION)
        _, supervisor = manager.attach(SESSION)
        manager.submit(SESSION, "¿Horario?", "7")
        return await collect(owner, "generation_completed"), await collect(supervisor, "generation_completed")

    a, b = asyncio.run(scenario())
    assert a == b and len(provider.questions) == 1
    assert manager.broker.subscriber_count(SESSION) == 2 and channel_for(SESSION) == f"chat.{SESSION}"


# ---------------------------------------------------------------- reconexión: snapshot con el historial
def test_reconectar_con_el_mismo_session_id_rehidrata_el_historial(monkeypatch, tmp_path):
    install_provider(monkeypatch, FakeProvider(lambda q: FakeStream(words("Los martes."))))
    manager = make_manager(real_agent_service(tmp_path))

    async def scenario():
        manager.open_session(SESSION, "7", None)
        _, sub = manager.attach(SESSION)
        manager.submit(SESSION, "¿Qué día entrega Miami?", "7")
        await collect(sub, "generation_completed")
        manager.detach(sub)  # se cae la conexión
        manager.open_session(SESSION, "7", None)
        return manager.attach(SESSION)

    snapshot, sub = asyncio.run(scenario())
    assert snapshot["session_id"] == SESSION
    assert [(m["role"], m["text"], m["status"]) for m in snapshot["messages"]] == [
        ("user", "¿Qué día entrega Miami?", "completed"), ("assistant", "Los martes.", "completed")]


def test_un_mensaje_que_quedo_streaming_sin_generacion_viva_se_cierra_como_interrupted(tmp_path):
    manager = make_manager(real_agent_service(tmp_path))
    manager.open_session(SESSION, "7", None)
    message_id = manager.store.add_message(SESSION, "assistant", "parcial", "streaming")  # el proceso murió a mitad

    async def scenario():
        return manager.attach(SESSION)

    snapshot, _ = asyncio.run(scenario())
    assert snapshot["messages"][0]["message_id"] == message_id and snapshot["messages"][0]["status"] == "interrupted"


# ---------------------------------------------------------------- guardrails y fallos
def test_si_el_texto_final_difiere_del_mostrado_se_emite_message_corrected(monkeypatch, tmp_path):
    install_provider(monkeypatch, FakeProvider(lambda q: FakeStream(words("Texto sin validar."))))
    service = real_agent_service(tmp_path, generate_fn=lambda q, ctx: (rag.complete(rag.build_messages(q, ctx)), "TEXTO FINAL VALIDADO")[1])
    manager = make_manager(service)

    async def scenario():
        manager.open_session(SESSION, "7", None)
        _, sub = manager.attach(SESSION)
        manager.submit(SESSION, "hola", "7")
        return await collect(sub, "generation_completed")

    events = asyncio.run(scenario())
    assert names(events)[-2:] == ["message_corrected", "generation_completed"]
    assert events[-2]["data"]["text"] == "TEXTO FINAL VALIDADO"
    assert manager.store.messages(SESSION)[-1]["text"] == "TEXTO FINAL VALIDADO"


def test_si_nada_se_mostro_el_texto_final_se_emite_como_token_chunk(tmp_path):
    manager = make_manager(real_agent_service(tmp_path, generate_fn=lambda q, ctx: "No puedo ayudar con eso."))

    async def scenario():
        manager.open_session(SESSION, "7", None)
        _, sub = manager.attach(SESSION)
        manager.submit(SESSION, "hola", "7")
        return await collect(sub, "generation_completed")

    events = asyncio.run(scenario())
    assert "".join(e["data"]["token"] for e in events if e["event"] == "token_chunk") == "No puedo ayudar con eso."
    assert "message_corrected" not in names(events)


def test_un_fallo_del_agente_publica_generation_failed(tmp_path):
    def boom(question, context):
        raise RuntimeError("detalle interno que no debe viajar al cliente")

    manager = make_manager(real_agent_service(tmp_path, generate_fn=boom))

    async def scenario():
        manager.open_session(SESSION, "7", None)
        _, sub = manager.attach(SESSION)
        manager.submit(SESSION, "hola", "7")
        return await collect(sub, "generation_failed")

    events = asyncio.run(scenario())
    assert events[-1]["data"]["status"] == "failed" and "detalle interno" not in json.dumps(events[-1])
    assert manager.store.messages(SESSION)[-1]["status"] == "failed"


def test_mensaje_vacio_o_demasiado_largo_se_rechaza(tmp_path):
    from services.agent.chat.manager import ChatError, MAX_INPUT_LENGTH

    manager = make_manager(real_agent_service(tmp_path))
    manager.open_session(SESSION, "7", None)
    for bad in ("   ", "x" * (MAX_INPUT_LENGTH + 1), None):
        with pytest.raises(ChatError):
            manager.submit(SESSION, bad, "7")


def test_el_broker_cierra_al_consumidor_lento_en_vez_de_perder_eventos_en_silencio():
    async def scenario():
        broker = ChatBroker(queue_size=2)
        slow, fast = broker.subscribe(SESSION), broker.subscribe(SESSION)
        for i in range(5):
            broker.publish(SESSION, "token_chunk", {"token": str(i), "sequence": i})
            await asyncio.sleep(0)
            fast.queue.get_nowait()  # el rápido vacía su cola
        await asyncio.sleep(0.01)
        return slow.overflowed, fast.overflowed

    assert asyncio.run(scenario()) == (True, False)
