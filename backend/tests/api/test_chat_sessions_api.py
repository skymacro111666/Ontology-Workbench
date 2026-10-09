"""Chat session REST: CRUD shapes, isolation, agent-token 403."""

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select

from ontoworkbench.db.models import User
from ontoworkbench.db.repositories import ChatMessageRepository, ChatSessionRepository
from ontoworkbench.db.session import sessionmaker_or_fail


def _oid(client: TestClient) -> str:
    """A blank ontology to hang sessions off."""
    return client.post("/api/v1/ontologies/blank", json={"name": "Chat"}).json()["data"]["id"]


def _admin_id() -> str:
    """The conftest-seeded admin's user id."""
    with sessionmaker_or_fail()() as s:
        return str(s.scalars(select(User)).one().id)


def _seed(oid: str, title: str, messages: list[tuple[str, str]]) -> str:
    """One session + messages via the repos (sessions are born lazily via chat, never via REST)."""
    with sessionmaker_or_fail()() as s:
        srepo = ChatSessionRepository(s)
        srow = srepo.create(user_id=uuid.UUID(_admin_id()), ontology_id=uuid.UUID(oid), title=title)
        s.commit()
        mrepo = ChatMessageRepository(s)
        for role, content in messages:
            mrepo.append(srow.id, role, content)
        # mirror the SSE flow: every send touches the session (python-side
        # now() carries microseconds — sqlite CURRENT_TIMESTAMP does not)
        srepo.touch(srow)
        s.commit()
        return str(srow.id)


def test_list_rename_delete_history(client: TestClient) -> None:
    """List order, rename roundtrip, delete cascade, ordered history rows."""
    oid = _oid(client)
    s_old = _seed(oid, "old", [("user", "你好"), ("assistant", "你好!")])
    s_new = _seed(oid, None, [("user", "第二条")])

    r = client.get(f"/api/v1/ontologies/{oid}/chat/sessions")
    assert r.status_code == 200
    rows = r.json()["data"]
    assert [row["id"] for row in rows] == [s_new, s_old]  # updatedAt DESC
    assert set(rows[0]) == {"id", "title", "updatedAt", "messageCount"}
    assert rows[1]["messageCount"] == 2

    r = client.put(f"/api/v1/ontologies/{oid}/chat/sessions/{s_old}", json={"title": "改名了"})
    assert r.status_code == 200
    assert r.json()["data"] == {"id": s_old, "title": "改名了"}

    r = client.delete(f"/api/v1/ontologies/{oid}/chat/sessions/{s_new}")
    assert r.status_code == 200
    r = client.get(f"/api/v1/ontologies/{oid}/chat/sessions/{s_new}/messages")
    assert r.status_code == 404

    r = client.get(f"/api/v1/ontologies/{oid}/chat/sessions/{s_old}/messages")
    assert r.status_code == 200
    msgs = r.json()["data"]
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert set(msgs[0]) == {"id", "role", "content", "createdAt"}


def test_messages_isolated_between_sessions(client: TestClient) -> None:
    """Messages never leak across sessions of the same ontology."""
    oid = _oid(client)
    s1 = _seed(oid, "one", [("user", "s1-only")])
    s2 = _seed(oid, "two", [("user", "s2-only"), ("assistant", "s2-answer")])

    r1 = client.get(f"/api/v1/ontologies/{oid}/chat/sessions/{s1}/messages").json()["data"]
    r2 = client.get(f"/api/v1/ontologies/{oid}/chat/sessions/{s2}/messages").json()["data"]
    assert [m["content"] for m in r1] == ["s1-only"]
    assert [m["content"] for m in r2] == ["s2-only", "s2-answer"]


def test_sessions_other_user_404(client: TestClient) -> None:
    """A session owned by another user is indistinguishable from a missing one."""
    oid = _oid(client)
    with sessionmaker_or_fail()() as s:
        srow = ChatSessionRepository(s).create(
            user_id=uuid.UUID(int=99), ontology_id=uuid.UUID(oid), title="theirs"
        )
        s.commit()
        sid = str(srow.id)

    for method, path in [
        ("GET", f"/api/v1/ontologies/{oid}/chat/sessions/{sid}/messages"),
        ("PUT", f"/api/v1/ontologies/{oid}/chat/sessions/{sid}"),
        ("DELETE", f"/api/v1/ontologies/{oid}/chat/sessions/{sid}"),
    ]:
        r = client.request(method, path, json={"title": "x"} if method == "PUT" else None)
        assert r.status_code == 404
        assert r.json()["code"] == "NOT_FOUND"


def test_agent_token_forbidden(client: TestClient) -> None:
    """Agent tokens ride an allowlist; chat routes stay off it by default."""
    oid = _oid(client)
    r = client.post("/api/v1/agent-tokens", json={"label": "chat-probe"})
    assert r.status_code == 201
    token = r.json()["data"]["token"]

    r = client.get(
        f"/api/v1/ontologies/{oid}/chat/sessions",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403
    assert r.json()["code"] == "AGENT_FORBIDDEN"
