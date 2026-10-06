"""封场/解封端到端验收：写入口闸、快照仓只读、待生效配置三处联动。

注意：StaticPool 内存库只有一条共享连接，而 TestClient 的请求在独立线程执行。
因此测试侧所有直连 DB 的操作都用短会话即用即关，请求进行中绝不持有打开的会话。
"""
import json

from sqlalchemy import func, select

from app.models.models import Hall, HallSnapshot, SeatPlan
from app.services.seed import seed_if_empty


def _count(Session_, model, hall_id: int) -> int:
    s = Session_()
    try:
        return s.scalar(
            select(func.count()).select_from(model).where(model.hall_id == hall_id)
        ) or 0
    finally:
        s.close()


def _latest_raw(Session_, model, hall_id: int) -> str:
    s = Session_()
    try:
        return s.scalars(
            select(model.result_json)
            .where(model.hall_id == hall_id)
            .order_by(model.id.desc())
        ).first()
    finally:
        s.close()


def test_seal_flow(Session_, client):
    # 1. 种子排完座：seed 后即有一条初始方案
    db = Session_()
    seed_if_empty(db)
    db.close()
    assert _count(Session_, SeatPlan, 1) == 1
    plan_json = _latest_raw(Session_, SeatPlan, 1)
    plan_payload = json.loads(plan_json)

    # 2. 初始 halls 状态
    r = client.get("/api/halls")
    assert r.status_code == 200
    h1 = next(x for x in r.json() if x["id"] == 1)
    assert h1["is_sealed"] is False
    assert h1["pending_min_manhattan"] is None
    assert h1["min_manhattan"] == 2

    # 3. 从未排过座的空考室不允许封场
    db = Session_()
    db.add(Hall(code="H102", name="二号考室", rows=4, cols=4, min_manhattan=2))
    db.commit()
    db.close()
    r = client.post("/api/sealing/seal?hall_id=2")
    assert r.status_code == 409
    assert "尚未生成排座图" in r.text

    # 4. 封场前无快照
    r = client.get("/api/seating/snapshot/latest?hall_id=1")
    assert r.status_code == 404

    # 5. 封场：快照仓写入，方案条数不变
    r = client.post("/api/sealing/seal?hall_id=1")
    assert r.status_code == 200, r.text
    sealed = r.json()
    assert sealed["snapshot"] is True
    for key in ("assignments", "violations", "unplaced", "stats"):
        assert sealed[key] == plan_payload[key]
    assert _count(Session_, HallSnapshot, 1) == 1
    assert _count(Session_, SeatPlan, 1) == 1
    snap0 = _latest_raw(Session_, HallSnapshot, 1)
    assert snap0 == plan_json

    # 6. 封场后生成新方案必须失败，条数不变
    r = client.post("/api/seating/run?hall_id=1")
    assert r.status_code == 409
    assert "已封场" in r.text
    assert _count(Session_, SeatPlan, 1) == 1

    # 7. 封场期间读取走快照，且不增行
    r = client.get("/api/seating/latest?hall_id=1")
    assert r.status_code == 200
    latest = r.json()
    assert latest["snapshot"] is True
    assert latest["assignments"] == plan_payload["assignments"]
    r = client.get("/api/seating/violations?hall_id=1")
    assert r.status_code == 200
    assert r.json()["snapshot"] is True
    assert r.json()["violations"] == plan_payload["violations"]
    r = client.get("/api/seating/stats?hall_id=1")
    assert r.status_code == 200
    assert r.json()["snapshot"] is True
    assert r.json()["seated"] == plan_payload["stats"]["seated"]
    assert _count(Session_, SeatPlan, 1) == 1

    # 8. 封场期间改距只进待生效：生效距/方案/快照都不变
    r = client.post("/api/seating/config?hall_id=1&min_manhattan=3")
    assert r.status_code == 200
    assert r.json()["min_manhattan"] == 2
    assert r.json()["pending_min_manhattan"] == 3
    assert r.json()["is_sealed"] is True
    assert _count(Session_, SeatPlan, 1) == 1
    assert _latest_raw(Session_, HallSnapshot, 1) == snap0
    h1 = next(x for x in client.get("/api/halls").json() if x["id"] == 1)
    assert h1["min_manhattan"] == 2 and h1["pending_min_manhattan"] == 3

    # 9. 重复封场 409
    assert client.post("/api/sealing/seal?hall_id=1").status_code == 409

    # 10. 解封：待生效距当下生效，快照逐字不动
    r = client.post("/api/seating/unseal?hall_id=1")
    assert r.status_code == 200, r.text
    state = r.json()
    assert state["is_sealed"] is False
    assert state["min_manhattan"] == 3
    assert state["pending_min_manhattan"] is None
    assert _count(Session_, HallSnapshot, 1) == 1
    assert _latest_raw(Session_, HallSnapshot, 1) == snap0

    # 11. 重复解封 409
    assert client.post("/api/seating/unseal?hall_id=1").status_code == 409

    # 12. 解封后按新约束重排：新增一条方案，快照不改写
    r = client.post("/api/seating/run?hall_id=1")
    assert r.status_code == 200, r.text
    new_plan = r.json()
    assert new_plan["hall"]["min_manhattan"] == 3
    assert "snapshot" not in new_plan
    assert _count(Session_, SeatPlan, 1) == 2
    assert _count(Session_, HallSnapshot, 1) == 1
    assert _latest_raw(Session_, HallSnapshot, 1) == snap0

    # 13. 解封后仍可读取封场当时的快照
    r = client.get("/api/seating/snapshot/latest?hall_id=1")
    assert r.status_code == 200
    snap_view = r.json()
    assert snap_view["assignments"] == plan_payload["assignments"]
    assert snap_view["stats"] == plan_payload["stats"]
    assert json.dumps(
        {k: snap_view[k] for k in ("assignments", "violations", "unplaced", "stats")},
        ensure_ascii=False,
    ) == json.dumps(
        {k: plan_payload[k] for k in ("assignments", "violations", "unplaced", "stats")},
        ensure_ascii=False,
    )

    # 14. 未封场改距直接生效，不增行；非法值 400
    r = client.post("/api/seating/config?hall_id=1&min_manhattan=1")
    assert r.status_code == 200
    assert r.json()["min_manhattan"] == 1
    assert r.json()["pending_min_manhattan"] is None
    assert _count(Session_, SeatPlan, 1) == 2
    r = client.post("/api/seating/config?hall_id=1&min_manhattan=0")
    assert r.status_code == 400
