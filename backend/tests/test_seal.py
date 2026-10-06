"""封场验收：写入口闸 / 快照仓 / 待生效配置 三处同时落下，封解互斥。"""
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models.models import Candidate, Hall, PaperSet, SealSnapshot, SeatPlan

engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
TestingSession = sessionmaker(bind=engine)


def override_get_db():
    db = TestingSession()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)  # 不进 lifespan，不触 Postgres


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = TestingSession()
    hall = Hall(code="H101", name="一号考室", rows=5, cols=6, min_manhattan=2)
    db.add(hall)
    db.flush()
    papers = []
    for code, title in [("P-A", "语文 A 卷"), ("P-B", "语文 B 卷"), ("P-C", "语文 C 卷")]:
        p = PaperSet(code=code, title=title)
        db.add(p)
        db.flush()
        papers.append(p.id)
    for i in range(12):
        db.add(Candidate(hall_id=hall.id, name=f"考生{i+1}", ticket_no=f"T{2026001+i}",
                         paper_id=papers[i % 3]))
    db.commit()
    db.close()
    yield


def plan_count() -> int:
    db = TestingSession()
    try:
        return db.scalar(select(func.count()).select_from(SeatPlan)) or 0
    finally:
        db.close()


def snapshot_count() -> int:
    db = TestingSession()
    try:
        return db.scalar(select(func.count()).select_from(SealSnapshot)) or 0
    finally:
        db.close()


def test_empty_hall_cannot_seal():
    # 从未排过座的空考室不允许封场
    r = client.post("/api/halls/1/seal")
    assert r.status_code == 409
    assert plan_count() == 0
    assert snapshot_count() == 0
    hall = client.get("/api/halls").json()[0]
    assert hall["sealed"] is False


def test_seal_blocks_regenerate_and_plan_count_unchanged():
    assert client.post("/api/seating/run?hall_id=1").status_code == 200
    assert plan_count() == 1
    r = client.post("/api/halls/1/seal")
    assert r.status_code == 200
    assert snapshot_count() == 1
    # 封场后所有生成入口失败且方案条数不变
    r = client.post("/api/seating/run?hall_id=1")
    assert r.status_code == 409
    assert plan_count() == 1
    # 封场期间 latest 只读快照
    data = client.get("/api/seating/latest?hall_id=1").json()
    assert data["snapshot"] is True
    assert data["hall"]["sealed"] is True
    assert plan_count() == 1
    v = client.get("/api/seating/violations?hall_id=1").json()
    assert v["sealed"] is True
    s = client.get("/api/seating/stats?hall_id=1").json()
    assert s["sealed"] is True


def test_config_change_while_sealed_goes_pending_only():
    client.post("/api/seating/run?hall_id=1")
    client.post("/api/halls/1/seal")
    snap_before = client.get("/api/halls/1/snapshot").json()
    r = client.patch("/api/halls/1", json={"min_manhattan": 3})
    assert r.status_code == 200
    body = r.json()
    assert body["pending"] is True
    assert body["min_manhattan"] == 2  # 生效值不动
    assert body["pending_min_manhattan"] == 3  # 只进待生效配置
    # 不得改快照，也不得偷偷出新方案
    assert plan_count() == 1
    snap_after = client.get("/api/halls/1/snapshot").json()
    assert snap_after == snap_before
    assert snap_after["min_manhattan"] == 2


def test_unseal_applies_pending_then_new_plan_uses_new_distance():
    client.post("/api/seating/run?hall_id=1")
    client.post("/api/halls/1/seal")
    client.patch("/api/halls/1", json={"min_manhattan": 3})
    r = client.post("/api/halls/1/unseal")
    assert r.status_code == 200
    assert r.json()["min_manhattan"] == 3  # 待生效配置在解封时生效
    assert r.json()["pending_min_manhattan"] is None
    # 解封后才允许新排，新排按解封当下约束出图
    r = client.post("/api/seating/run?hall_id=1")
    assert r.status_code == 200
    assert r.json()["hall"]["min_manhattan"] == 3
    assert plan_count() == 2
    # 快照仍保持封场当时的字
    snap = client.get("/api/halls/1/snapshot").json()
    assert snap["min_manhattan"] == 2
    assert snapshot_count() == 1


def test_seal_unseal_mutually_exclusive():
    client.post("/api/seating/run?hall_id=1")
    assert client.post("/api/halls/1/seal").status_code == 200
    assert client.post("/api/halls/1/seal").status_code == 409  # 已封不能再封
    assert client.post("/api/halls/1/unseal").status_code == 200
    assert client.post("/api/halls/1/unseal").status_code == 409  # 未封不能解封
    # 解封后改距直接写生效值
    r = client.patch("/api/halls/1", json={"min_manhattan": 4})
    assert r.json()["pending"] is False
    assert r.json()["min_manhattan"] == 4


def test_snapshot_keeps_seal_time_content_after_unseal_and_rerun():
    client.post("/api/seating/run?hall_id=1")
    client.post("/api/halls/1/seal")
    snap_id = client.get("/api/halls/1/snapshot").json()["snapshot_id"]
    sealed_stats = client.get("/api/seating/stats?hall_id=1").json()
    client.patch("/api/halls/1", json={"min_manhattan": 1})
    client.post("/api/halls/1/unseal")
    client.post("/api/seating/run?hall_id=1")
    snap = client.get("/api/halls/1/snapshot").json()
    assert snap["snapshot_id"] == snap_id
    assert snap["min_manhattan"] == 2
    assert snap["stats"] == {k: v for k, v in sealed_stats.items()
                             if k in ("seated", "unplaced", "violations", "capacity")}
    # 新方案存在但不回写快照仓
    assert snapshot_count() == 1
    latest = client.get("/api/seating/latest?hall_id=1").json()
    assert latest.get("snapshot") is None
    assert latest["hall"]["min_manhattan"] == 1


def test_reseal_appends_new_snapshot_without_rewriting_old():
    client.post("/api/seating/run?hall_id=1")
    client.post("/api/halls/1/seal")
    first = client.get("/api/halls/1/snapshot").json()
    client.post("/api/halls/1/unseal")
    client.post("/api/seating/run?hall_id=1")
    client.post("/api/halls/1/seal")
    assert snapshot_count() == 2
    second = client.get("/api/halls/1/snapshot").json()
    assert second["snapshot_id"] != first["snapshot_id"]
    db = TestingSession()
    try:
        old = db.get(SealSnapshot, first["snapshot_id"])
        assert json.loads(old.snapshot_json)["stats"] == first["stats"]
        assert old.min_manhattan == first["min_manhattan"]
    finally:
        db.close()
