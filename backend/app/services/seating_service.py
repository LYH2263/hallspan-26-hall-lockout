"""排座与封场领域服务。

封场三态在后端强制：
- is_sealed 写入口闸：封场后任何生成新方案的路径都 409，seat_plans 不增行；
- hall_snapshots 快照仓：封场当时的图/违规/统计原样复制、只追加不改写；
- pending_min_manhattan 待生效槽：封场期改距只进待生效，解封当下一次性生效。
"""
import json
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.models import Candidate, Hall, HallSnapshot, SeatPlan
from app.services.seat_engine import find_violations, place_candidates, plan_to_dict


def _get_hall_or_404(db: Session, hall_id: int) -> Hall:
    hall = db.get(Hall, hall_id)
    if not hall:
        raise HTTPException(404, "考室不存在")
    return hall


def _lock_hall(db: Session, hall_id: int) -> Hall:
    """锁 hall 行后再做闸检/写入（SQLite 下 for update 被忽略，无害）。"""
    hall = db.scalars(
        select(Hall).where(Hall.id == hall_id).with_for_update()
    ).first()
    if not hall:
        raise HTTPException(404, "考室不存在")
    return hall


def build_plan_payload(db: Session, hall: Hall) -> dict:
    """按当下生效约束构建排座结果，不写库。"""
    cands = [
        {"id": c.id, "name": c.name, "ticket_no": c.ticket_no, "paper_id": c.paper_id}
        for c in db.scalars(select(Candidate).where(Candidate.hall_id == hall.id)).all()
    ]
    assigns, unplaced = place_candidates(hall.rows, hall.cols, hall.min_manhattan, cands)
    viols = find_violations(hall.rows, hall.cols, hall.min_manhattan, assigns)
    result = plan_to_dict(assigns, unplaced, viols, hall.rows, hall.cols)
    result["hall"] = {"id": hall.id, "name": hall.name, "min_manhattan": hall.min_manhattan}
    return result


def generate_plan(db: Session, hall: Hall, *, commit: bool = True) -> dict:
    """构建并落一条新 SeatPlan（调用方须先完成封场闸检）。"""
    payload = build_plan_payload(db, hall)
    plan = SeatPlan(
        hall_id=hall.id,
        created_at=datetime.utcnow(),
        result_json=json.dumps(payload, ensure_ascii=False),
    )
    db.add(plan)
    db.flush()
    db.refresh(plan)
    if commit:
        db.commit()
        db.refresh(plan)
    return {"id": plan.id, **payload}


def latest_seat_plan(db: Session, hall_id: int) -> SeatPlan | None:
    return db.scalars(
        select(SeatPlan).where(SeatPlan.hall_id == hall_id).order_by(SeatPlan.id.desc())
    ).first()


def latest_snapshot(db: Session, hall_id: int) -> HallSnapshot | None:
    return db.scalars(
        select(HallSnapshot)
        .where(HallSnapshot.hall_id == hall_id)
        .order_by(HallSnapshot.id.desc())
    ).first()


def read_active_plan(db: Session, hall: Hall) -> dict | None:
    """读取当前应展示的方案。封场读快照、未封场读最新方案；本函数绝不生成。"""
    if hall.is_sealed:
        snap = latest_snapshot(db, hall.id)
        if snap is None:
            raise HTTPException(409, "封场快照缺失，请联系管理员")
        return {"id": snap.id, "snapshot": True, "snapshot_id": snap.id,
                **json.loads(snap.result_json)}
    plan = latest_seat_plan(db, hall.id)
    if plan is None:
        return None
    return {"id": plan.id, **json.loads(plan.result_json)}


def _hall_state(hall: Hall) -> dict:
    return {
        "id": hall.id,
        "code": hall.code,
        "name": hall.name,
        "rows": hall.rows,
        "cols": hall.cols,
        "min_manhattan": hall.min_manhattan,
        "is_sealed": hall.is_sealed,
        "pending_min_manhattan": hall.pending_min_manhattan,
        "sealed_at": hall.sealed_at.isoformat() if hall.sealed_at else None,
    }


def seal_hall(db: Session, hall_id: int) -> dict:
    """封场：闸落 + 最新方案原样入快照仓，单事务。从未排过座不允许封场。"""
    hall = _lock_hall(db, hall_id)
    if hall.is_sealed:
        raise HTTPException(409, "考室已封场，请勿重复封场")
    plan = latest_seat_plan(db, hall.id)
    if plan is None:
        raise HTTPException(409, "该考室尚未生成排座图，无法封场")
    now = datetime.utcnow()
    snap = HallSnapshot(
        hall_id=hall.id,
        seat_plan_id=plan.id,
        sealed_at=now,
        result_json=plan.result_json,  # 原样字符串复制，保证与封场当时逐字一致
    )
    db.add(snap)
    hall.is_sealed = True
    hall.sealed_at = now
    db.commit()
    db.refresh(snap)
    return {
        "id": snap.id,
        "snapshot": True,
        "snapshot_id": snap.id,
        "seat_plan_id": plan.id,
        "sealed_at": now.isoformat(),
        **json.loads(snap.result_json),
    }


def unseal_hall(db: Session, hall_id: int) -> dict:
    """解封：闸开 + 待生效距一次性生效；不触碰方案与快照。"""
    hall = _lock_hall(db, hall_id)
    if not hall.is_sealed:
        raise HTTPException(409, "考室未封场，无需解封")
    hall.is_sealed = False
    if hall.pending_min_manhattan is not None:
        hall.min_manhattan = hall.pending_min_manhattan
    hall.pending_min_manhattan = None
    hall.sealed_at = None
    db.commit()
    return _hall_state(hall)


def stage_or_apply_distance(db: Session, hall_id: int, min_manhattan: int) -> dict:
    """改最小距：封场只进待生效槽；未封场直接改生效距。"""
    if not isinstance(min_manhattan, int) or isinstance(min_manhattan, bool) or min_manhattan < 1:
        raise HTTPException(400, "最小曼哈顿间距必须为不小于 1 的整数")
    hall = _lock_hall(db, hall_id)
    if hall.is_sealed:
        hall.pending_min_manhattan = min_manhattan
    else:
        hall.min_manhattan = min_manhattan
        hall.pending_min_manhattan = None
    db.commit()
    return _hall_state(hall)
