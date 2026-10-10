"""Chat SSE endpoint: lazy session, persistence, error path, history replay."""

import asyncio
import json
import uuid

from fastapi.testclient import TestClient
from starlette.requests import Request

from ontoworkbench.core.ai.fake import FakeProvider
from ontoworkbench.core.ai.types import ModelRequest, ModelResponse, TextDelta, ToolCall
from ontoworkbench.core.errors import CoreError
from ontoworkbench.server.routers.ai_settings import get_ai_provider
from ontoworkbench.server.routers.chat import _history_from_rows, _stream_chat


def _oid(client: TestClient) -> str:
    """A blank ontology to chat about."""
    return client.post("/api/v1/ontologies/blank", json={"name": "Chat"}).json()["data"]["id"]


def _payload_of(body: str, event: str) -> str:
    """The data line of the first frame carrying `event`."""
    for frame in body.split("\n\n"):
        if frame.startswith(f"event: {event}\n"):
            return frame.split("data: ", 1)[1]
    raise AssertionError(f"no {event} frame in:\n{body}")


class Raising(FakeProvider):
    """A provider whose every stream call fails."""

    async def stream(self, req: ModelRequest):
        """Fail like an upstream outage."""
        raise CoreError("AI_REQUEST_FAILED", "boom")
        yield  # pragma: no cover - makes this an async generator


class Capturing(FakeProvider):
    """FakeProvider recording every ModelRequest it serves.

    Snapshots the message list: the loop keeps appending to the same list
    after the request, so holding the reference would see post-hoc state.
    """

    def __init__(self, responses: list[ModelResponse]) -> None:
        """Record requests while serving the scripted responses."""
        super().__init__(responses)
        self.seen: list[list[dict]] = []

    async def stream(self, req: ModelRequest):
        """Record, then replay the scripted stream."""
        self.seen.append([dict(m) for m in req.messages])
        async for ev in super().stream(req):
            yield ev


def test_stream_happy_path_events(client: TestClient, monkeypatch) -> None:
    """Session→tools→delta→done on the wire; rows persist in order."""
    monkeypatch.setenv("AI_MODEL", "test-model")
    oid = _oid(client)
    capture = Capturing(
        [
            ModelResponse(text="", tool_calls=[ToolCall(name="get_ontology", arguments={})]),
            ModelResponse(text="共 2 个类。", in_tokens=5, out_tokens=2),
        ]
    )
    client.app.dependency_overrides[get_ai_provider] = lambda: capture
    try:
        with client.stream(
            "POST",
            f"/api/v1/ontologies/{oid}/chat/messages",
            json={"content": "介绍一下"},
        ) as r:
            assert r.headers["content-type"].startswith("text/event-stream")
            body = "".join(r.iter_text())
    finally:
        client.app.dependency_overrides.clear()

    for needle in [
        "event: session",
        "event: tool_start",
        "event: tool_end",
        "event: delta",
        "event: done",
    ]:
        assert needle in body, body
    session = json.loads(_payload_of(body, "session"))
    assert session["title"] == "介绍一下"
    done = json.loads(_payload_of(body, "done"))
    assert done["inTokens"] == 5 and done["outTokens"] == 2 and done["model"]

    sid = session["sessionId"]
    msgs = client.get(f"/api/v1/ontologies/{oid}/chat/sessions/{sid}/messages").json()["data"]
    assert [m["role"] for m in msgs] == ["user", "tool", "assistant"]
    tool_row = json.loads(msgs[1]["content"])
    assert set(tool_row) == {"name", "ok", "result"}
    assert msgs[2]["content"] == "共 2 个类。"


def test_second_send_replays_history(client: TestClient) -> None:
    """A follow-up send targets the session; the model sees prior turns."""
    oid = _oid(client)
    capture = Capturing(
        [
            ModelResponse(text="第一答。"),
            ModelResponse(text="第二答。"),
        ]
    )
    client.app.dependency_overrides[get_ai_provider] = lambda: capture
    try:
        sid: str | None = None
        for content in ("第一问", "第二问"):
            payload: dict = {"content": content}
            if sid is not None:
                payload["sessionId"] = sid
            with client.stream(
                "POST",
                f"/api/v1/ontologies/{oid}/chat/messages",
                json=payload,
            ) as r:
                body = "".join(r.iter_text())
                sid = json.loads(_payload_of(body, "session"))["sessionId"]
    finally:
        client.app.dependency_overrides.clear()

    msgs = client.get(f"/api/v1/ontologies/{oid}/chat/sessions/{sid}/messages").json()["data"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant"]
    # round 2's request carried the whole replayed history
    roles = [m.get("role") for m in capture.seen[1]]
    assert roles == ["user", "assistant", "user"]
    assert capture.seen[1][0]["content"] == "第一问"


def test_failed_send_creates_no_session(client: TestClient) -> None:
    """A provider failure before any output leaves no session row behind."""
    oid = _oid(client)
    client.app.dependency_overrides[get_ai_provider] = lambda: Raising([])
    try:
        with client.stream(
            "POST",
            f"/api/v1/ontologies/{oid}/chat/messages",
            json={"content": "你好"},
        ) as r:
            body = "".join(r.iter_text())
    finally:
        client.app.dependency_overrides.clear()

    assert "event: error" in body
    assert json.loads(_payload_of(body, "error"))["code"] == "AI_REQUEST_FAILED"
    assert client.get(f"/api/v1/ontologies/{oid}/chat/sessions").json()["data"] == []


def test_unconfigured_503_envelope(client: TestClient, monkeypatch) -> None:
    """No provider config: a plain JSON envelope, not a stream."""
    oid = _oid(client)
    for var in ("AI_MODEL_PROVIDER", "AI_BASE_URL", "AI_API_KEY", "AI_MODEL"):
        monkeypatch.delenv(var, raising=False)
    r = client.post(f"/api/v1/ontologies/{oid}/chat/messages", json={"content": "你好"})
    assert r.status_code == 503
    assert r.json()["code"] == "AI_NOT_CONFIGURED"


def test_hard_cancel_persists_partial_turn(client: TestClient, monkeypatch) -> None:
    """A hard cancel still lands the staged turn.

    Client gone mid-answer (GeneratorExit at a yield): session, question,
    partial text persist (plan Task 6), instead of rolling back.
    """
    import types

    from ontoworkbench.core.parsing import parse_store
    from ontoworkbench.db.models import Ontology, User
    from ontoworkbench.db.session import sessionmaker_or_fail
    from ontoworkbench.server.routers.chat import ChatIn

    class DeltaThenHang(FakeProvider):
        """Streams one delta, then hangs like a slow model."""

        def __init__(self) -> None:
            super().__init__([])
            self.gate = asyncio.Event()

        async def stream(self, req: ModelRequest):
            yield TextDelta(text="部分回答:")
            await self.gate.wait()
            yield TextDelta(text="迟到的后半。")  # pragma: no cover - never reached

    monkeypatch.setattr(Request, "is_disconnected", lambda self: _async_false(), raising=True)
    provider = DeltaThenHang()
    client.app.dependency_overrides[get_ai_provider] = lambda: provider
    oid = _oid(client)

    async def scenario() -> None:
        with sessionmaker_or_fail()() as db:
            user = db.query(User).filter_by(username="admin").one()
            row = db.query(Ontology).filter_by(id=uuid.UUID(oid)).one()
            store, prefixes = parse_store(b"", "turtle")
            request = Request(
                {"type": "http", "app": client.app, "headers": [], "method": "POST"},
                receive=_hang_receive,
            )
            gen = _stream_chat(
                request=request,
                user=user,
                db=db,
                provider=provider,
                cfg=types.SimpleNamespace(model="test-model"),
                row=row,
                ix=None,  # type: ignore[arg-type] — no tool round happens
                store=store,
                prefixes=prefixes,
                body=ChatIn(content="中断测试"),
                srow=None,
            )
            while True:
                frame = await gen.__anext__()
                if frame.startswith("event: delta"):
                    break  # suspended mid-turn, like a client that walked away
            await gen.aclose()

    asyncio.run(scenario())

    sessions = client.get(f"/api/v1/ontologies/{oid}/chat/sessions").json()["data"]
    assert len(sessions) == 1
    msgs = client.get(
        f"/api/v1/ontologies/{oid}/chat/sessions/{sessions[0]['id']}/messages"
    ).json()["data"]
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[1]["content"] == "部分回答:"


async def _async_false() -> bool:
    return False


async def _hang_receive() -> dict:
    await asyncio.sleep(3600)  # pragma: no cover - no disconnect ever arrives
    return {"type": "http.disconnect"}


def test_history_from_rows_rebuilds_tool_turns() -> None:
    """Tool rows replay as assistant-tool_calls + tool messages; text rows pass."""
    from ontoworkbench.db.models import ChatMessage

    def row(role: str, content: str) -> ChatMessage:
        m = ChatMessage(session_id=uuid.UUID(int=1), role=role, content=content)
        m.id = 0
        return m

    rows = [
        row("user", "问"),
        row("tool", json.dumps({"name": "search_entities", "ok": True, "result": "[1]"})),
        row("tool", json.dumps({"name": "get_ontology", "ok": False, "result": "err"})),
        row("assistant", "答"),
    ]
    out = _history_from_rows(rows)
    assert [m["role"] for m in out] == ["user", "assistant", "tool", "tool", "assistant"]
    assert [c.name for c in out[1]["tool_calls"]] == ["search_entities", "get_ontology"]
    assert out[2]["content"] == "[1]"
    assert out[3]["name"] == "get_ontology"
