"""Study contract and FSRS checks; optional PostgreSQL tests use only study_test_* databases."""
import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fsrs import Card, Rating, State
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.engine import make_url

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.study import router
from core.database import get_session
from models.database import Base, Document, DocumentChunk
from models.study import StudyAttempt, StudyDeck, StudyItem, StudySession
from models.study_schemas import GenerateRequest, ItemDraft, Source
from services import study_service as study

NOW = datetime(2026, 9, 22, 10, tzinfo=timezone.utc)
MODEL = {"model": "fake", "provider": "ollama", "apiKey": "", "baseUrl": None}


def draft(kind="flashcard", **overrides):
    return {"kind": kind, "knowledge_point": "间隔复习", "prompt": "什么是间隔复习？",
            "answer": "间隔一段时间再次回忆", "explanation": "通过多次主动回忆巩固记忆。",
            "options": ["间隔一段时间再次回忆", "只学习一次", "不做回忆", "不停重读"] if kind == "choice" else [],
            "source": {"mode": "topic", "title": "学习方法", "document_id": None, "chunk_index": None, "excerpt": ""}, **overrides}


def test_three_question_types_and_validation():
    for kind in ("flashcard", "choice", "short_answer"):
        assert ItemDraft.model_validate(draft(kind)).kind == kind
    for invalid in (draft("choice", answer="E"), draft("choice", options=["A"] * 4),
                    draft(prompt="  "), draft("flashcard", options=["A"])):
        with pytest.raises(ValueError):
            ItemDraft.model_validate(invalid)


def test_generation_evidence_kind_count_and_duplicate_validation():
    request = GenerateRequest(**MODEL, mode="text", text="通过间隔一段时间再次回忆来巩固记忆。", count=2)
    sources = [Source(mode="text", title="笔记", excerpt=request.text)]
    item = {k: v for k, v in draft().items() if k != "source"}
    item.update(source_index=0, evidence="间隔一段时间再次回忆")
    result = study.validate_generated({"items": [item]}, request, sources)
    assert result[0].source.excerpt == item["evidence"]
    for data in ({"items": []}, {"items": [item, item]},
                 {"items": [{**item, "source_index": 1}]},
                 {"items": [{**item, "evidence": "不存在的原文"}]}):
        with pytest.raises(HTTPException) as exc:
            study.validate_generated(data, request, sources)
        assert exc.value.status_code == 502
    with pytest.raises(HTTPException):
        study.validate_generated({"items": [item]}, request.model_copy(update={"kinds": ["choice"]}), sources)
    topic_item = {**item, "source_index": None, "evidence": ""}
    topic = request.model_copy(update={"mode": "topic"})
    assert study.validate_generated({"items": [topic_item]}, topic, [])[0].source.mode == "topic"
    with pytest.raises(HTTPException):
        study.validate_generated({"items": [item]}, topic, [])


@pytest.mark.parametrize("rating", list(Rating))
def test_fsrs_roundtrip_and_four_ratings(rating):
    original = Card(card_id=123, due=NOW)
    card, log = study.scheduler.review_card(original, rating, NOW)
    assert original.last_review is None
    assert card.due > NOW and card.due.tzinfo == timezone.utc
    assert Card.from_dict(card.to_dict()).to_dict() == card.to_dict()
    assert log.rating == rating
    assert study.scheduler.review_card(original, rating, NOW)[0].due == card.due


def test_fsrs_early_overdue_and_relearning():
    card, _ = study.scheduler.review_card(Card(due=NOW), Rating.Easy, NOW)
    assert card.state == State.Review
    for now in (NOW + timedelta(hours=1), card.due + timedelta(days=7)):
        updated, log = study.scheduler.review_card(card, Rating.Again, now)
        assert updated.state == State.Relearning
        assert updated.last_review == now and updated.due > now
        assert log.review_datetime == now


def queue_item(card, count=1, **kwargs):
    return SimpleNamespace(id=uuid4(), fsrs_card=card.to_dict(), due=card.due,
                           review_count=count, created_at=NOW, knowledge_point="间隔复习", **kwargs)


def test_queue_priority_weak_samples_and_latest_mistake():
    new = queue_item(Card(due=NOW), 0)
    learning = queue_item(Card(due=NOW - timedelta(minutes=1), last_review=NOW - timedelta(hours=1)))
    mature = Card(state=State.Review, stability=5, difficulty=5, due=NOW, last_review=NOW - timedelta(days=3))
    risky = queue_item(mature)
    safer = queue_item(Card(state=State.Review, stability=20, difficulty=5, due=NOW, last_review=NOW - timedelta(days=3)))
    future = queue_item(Card(state=State.Review, stability=5, difficulty=5, due=NOW + timedelta(days=2), last_review=NOW))
    assert study.select_queue([new, safer, future, risky, learning], [], "daily", 20, NOW) == [learning, risky, safer, new]
    attempts = [SimpleNamespace(item_id=risky.id, snapshot=draft(), rating=1 if i < 4 else 3,
                               objective_correct=None, reviewed_at=NOW - timedelta(days=i)) for i in range(12)]
    points = study.weak_points(attempts)
    assert points[0]["samples"] == 10 and points[0]["ratio"] == 0.4
    assert study.select_queue([future], attempts, "weak", 20, NOW) == [future]
    assert study.select_queue([risky], attempts, "mistakes", 20, NOW) == [risky]
    attempts.append(SimpleNamespace(item_id=risky.id, snapshot=draft(), rating=3,
                                    objective_correct=True, reviewed_at=NOW + timedelta(seconds=1)))
    assert study.select_queue([risky], attempts, "mistakes", 20, NOW) == []


async def test_model_failures_and_fenced_json(monkeypatch):
    async def completion(*args, **kwargs):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='```json\n{"items": []}\n```'))])
    monkeypatch.setattr(study.query_service, "acompletion", completion)
    request = GenerateRequest(**MODEL, mode="topic", text="学习")
    assert await study.model_json(request, "system", {}) == {"items": []}
    async def failure(*args, **kwargs):
        raise RuntimeError("do not expose secret")
    monkeypatch.setattr(study.query_service, "acompletion", failure)
    with pytest.raises(HTTPException) as exc:
        await study.model_json(request, "system", {})
    assert exc.value.status_code == 502 and "secret" not in exc.value.detail
    async def timeout(*args, **kwargs):
        raise TimeoutError()
    monkeypatch.setattr(study.query_service, "acompletion", timeout)
    with pytest.raises(HTTPException) as exc:
        await study.model_json(request, "system", {})
    assert exc.value.status_code == 504


@pytest.fixture
async def database():
    url = os.getenv("STUDY_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set STUDY_TEST_DATABASE_URL to an isolated PostgreSQL database named study_test_*")
    parsed = make_url(url)
    if not (parsed.database or "").startswith("study_test_"):
        pytest.fail("Refusing to create/drop tables outside a study_test_* database")
    engine = create_async_engine(parsed.set(drivername="postgresql+asyncpg"))
    tables = [Document.__table__, DocumentChunk.__table__, StudyDeck.__table__, StudyItem.__table__,
              StudySession.__table__, StudyAttempt.__table__]
    async with engine.begin() as connection:
        await connection.run_sync(lambda sync: Base.metadata.create_all(sync, tables=tables))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    app = FastAPI()
    app.include_router(router)
    async def get_test_session():
        async with factory() as session:
            yield session
    app.dependency_overrides[get_session] = get_test_session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client, factory
    finally:
        async with engine.begin() as connection:
            await connection.run_sync(lambda sync: Base.metadata.drop_all(sync, tables=list(reversed(tables))))
        await engine.dispose()


async def create_items(client, kinds=("flashcard",)):
    deck = (await client.post("/api/study/decks", json={"title": "测试卡组"})).json()
    payload = {"items": [{"id": str(uuid4()), **draft(kind)} for kind in kinds]}
    response = await client.post(f"/api/study/decks/{deck['id']}/items", json=payload)
    assert response.status_code == 200, response.text
    return deck, response.json(), payload


async def round_for(client, deck, **kwargs):
    response = await client.post("/api/study/sessions", json={"id": str(uuid4()), "deck_id": deck["id"], **kwargs})
    assert response.status_code == 200, response.text
    return response.json()


async def answer(client, attempt, text=""):
    response = await client.post(f"/api/study/attempts/{attempt['id']}/answer", json={**MODEL, "answer": text})
    assert response.status_code == 200, response.text
    return response.json()


async def test_postgres_idempotency_restart_and_concurrent_confirmation(database):
    client, factory = database
    deck, items, payload = await create_items(client)
    again = await client.post(f"/api/study/decks/{deck['id']}/items", json=payload)
    assert again.status_code == 200 and len(again.json()) == 1
    record = await round_for(client, deck)
    second = await round_for(client, deck)
    attempt = record["attempts"][0]
    assert attempt["question"]["answer"] is None  # The queue must not leak the answer.
    answered = await answer(client, attempt)
    await answer(client, second["attempts"][0])
    assert len(answered["intervals"]) == 4
    restored = (await client.get(f"/api/study/sessions/{record['id']}")).json()
    assert restored["attempts"][0]["feedback"] is not None
    confirmation = {"confirmation_id": str(uuid4()), "version": attempt["item_version"], "rating": 3}
    path = f"/api/study/attempts/{attempt['id']}/confirm"
    responses = await asyncio.gather(client.post(path, json=confirmation), client.post(path, json=confirmation))
    assert [r.status_code for r in responses] == [200, 200]
    assert responses[0].json()["next_due"] == responses[1].json()["next_due"]
    async with factory() as session:
        item = await session.get(StudyItem, UUID(items[0]["id"]))
        assert item.review_count == 1 and item.version == 2
        saved = (await session.execute(select(StudyAttempt).where(StudyAttempt.rating.is_not(None)))).scalars().all()
        assert len(saved) == 1 and saved[0].fsrs_log["rating"] == 3
    completed = (await client.get(f"/api/study/sessions/{record['id']}")).json()
    assert completed["completed_at"] is not None
    stale = second["attempts"][0]
    conflict = await client.post(f"/api/study/attempts/{stale['id']}/confirm", json={**confirmation, "confirmation_id": str(uuid4())})
    assert conflict.status_code == 409
    assert (await client.post(path, json={**confirmation, "rating": 1})).status_code == 409
    stats = (await client.get("/api/study/stats?timezone=Asia%2FShanghai")).json()
    assert stats["reviewed_today"] == 1 and sum(d["reviewed"] for d in stats["trend"]) == 1


async def test_postgres_edit_archive_and_transaction_rollback(database):
    client, factory = database
    deck, items, _ = await create_items(client)
    record = await round_for(client, deck)
    attempt = record["attempts"][0]
    await answer(client, attempt)
    await client.post(f"/api/study/attempts/{attempt['id']}/confirm", json={"confirmation_id": str(uuid4()), "version": 1, "rating": 4})
    updated = {k: v for k, v in draft(prompt="修改后的问题").items() if k != "source"}
    response = await client.patch(f"/api/study/items/{items[0]['id']}", json={**updated, "version": 2})
    assert response.status_code == 200 and response.json()["review_count"] == 0
    old = (await client.get(f"/api/study/sessions/{record['id']}")).json()
    assert old["attempts"][0]["question"]["prompt"] == draft()["prompt"]
    new_id = str(uuid4())
    response = await client.post(f"/api/study/decks/{deck['id']}/items", json={"items": [
        {"id": new_id, **draft()}, {"id": items[0]["id"], **draft(prompt="冲突")}]})
    assert response.status_code == 409
    async with factory() as session:
        assert await session.get(StudyItem, UUID(new_id)) is None
    response = await client.post(f"/api/study/items/{items[0]['id']}/archive", json={"archived": True, "version": 3})
    assert response.status_code == 200
    assert (await client.post("/api/study/sessions", json={"id": str(uuid4()), "deck_id": deck["id"]})).status_code == 422
    assert (await client.get(f"/api/study/sessions/{record['id']}")).json()["attempts"][0]["rating"] == 4


async def test_postgres_generation_grading_fallback_recap_and_deleted_source(database, monkeypatch):
    client, factory = database
    calls = []
    async def completion(*args, **kwargs):
        system = kwargs["messages"][0]["content"]
        payload = json.loads(kwargs["messages"][1]["content"])
        calls.append(system)
        if "出题助手" in system:
            source = payload["sources"][0] if payload["sources"] else None
            generated = [{**{k: v for k, v in draft(kind).items() if k != "source"},
                          "source_index": 0 if source else None, "evidence": source["excerpt"] if source else ""}
                         for kind in payload["kinds"]]
            result = {"items": generated}
        elif "复盘" in system:
            result = {"recap": "需要加强主动回忆，请结合原文练习。"}
        else:
            raise RuntimeError("simulated model outage")
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(result, ensure_ascii=False)))])
    monkeypatch.setattr(study.query_service, "acompletion", completion)
    doc_id = uuid4()
    async with factory() as session:
        session.add(Document(id=doc_id, title="测试文档", status="completed"))
        await session.flush()
        session.add(DocumentChunk(document_id=doc_id, chunk_index=0, content="间隔一段时间再次回忆。", embedding=None))
        await session.commit()
    for mode in ("document", "text", "topic"):
        response = await client.post("/api/study/generate", json={**MODEL, "mode": mode, "document_id": str(doc_id),
                                                               "text": "间隔一段时间再次回忆。", "count": 3})
        assert response.status_code == 200, response.text
        assert len(response.json()["items"]) == 3
        if mode == "document":
            document_drafts = response.json()["items"]
    deck = (await client.post("/api/study/decks", json={"title": "来源测试"})).json()
    saved = await client.post(f"/api/study/decks/{deck['id']}/items", json={"items": [{**d, "id": str(uuid4())} for d in document_drafts]})
    assert saved.status_code == 200
    record = await round_for(client, deck)
    for attempt in record["attempts"]:
        text = "错误的选项" if attempt["question"]["kind"] == "choice" else "我的理解"
        if attempt["question"]["kind"] == "choice":
            text = attempt["question"]["options"][1]
        answered = await answer(client, attempt, text if attempt["question"]["kind"] != "flashcard" else "")
        if attempt["question"]["kind"] == "short_answer":
            assert answered["feedback"]["unavailable"]
        if attempt["question"]["kind"] == "choice":
            assert answered["objective_correct"] is False
        response = await client.post(f"/api/study/attempts/{attempt['id']}/confirm", json={"confirmation_id": str(uuid4()), "version": 1, "rating": 1})
        assert response.status_code == 200
    first = await client.post(f"/api/study/sessions/{record['id']}/recap", json=MODEL)
    call_count = len(calls)
    second = await client.post(f"/api/study/sessions/{record['id']}/recap", json=MODEL)
    assert first.json()["recap"] == second.json()["recap"] and len(calls) == call_count
    async with factory() as session:
        doc = await session.get(Document, doc_id)
        await session.delete(doc)
        await session.commit()
    restored = (await client.get(f"/api/study/sessions/{record['id']}")).json()
    assert all(not a["source_available"] for a in restored["attempts"])
    assert restored["attempts"][0]["question"]["source"]["excerpt"]
    variant = await client.post("/api/study/generate", json={**MODEL, "mode": "topic", "text": "变式", "variant_item_id": saved.json()[0]["id"]})
    assert variant.status_code == 200
    assert variant.json()["items"][0]["knowledge_point"] == "间隔复习"
    save_variant = await client.post(f"/api/study/decks/{deck['id']}/items", json={"items": [{**variant.json()["items"][0], "id": str(uuid4())}]})
    assert save_variant.status_code == 200
