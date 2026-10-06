import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import Hall, SealSnapshot, SeatPlan

router = APIRouter(prefix="/halls", tags=["halls"])


class HallConfigUpdate(BaseModel):
    min_manhattan: int = Field(ge=1, le=50)


def hall_state(r: Hall) -> dict:
    return {
        "id": r.id, "code": r.code, "name": r.name, "rows": r.rows, "cols": r.cols,
        "min_manhattan": r.min_manhattan,
        "sealed": r.sealed,
        "pending_min_manhattan": r.pending_min_manhattan,
    }


@router.get("")
def list_halls(db: Session = Depends(get_db)):
    return [hall_state(r) for r in db.scalars(select(Hall).order_by(Hall.id)).all()]


@router.get("/{hall_id}/snapshot")
def latest_snapshot(hall_id: int, db: Session = Depends(get_db)):
    """封场快照仓只读视图：无论当前封不封场，都返回最近一次封场写下的快照。"""
    hall = db.get(Hall, hall_id)
    if not hall:
        raise HTTPException(404, "考室不存在")
    snap = db.scalars(
        select(SealSnapshot).where(SealSnapshot.hall_id == hall_id)
        .order_by(SealSnapshot.id.desc())
    ).first()
    if not snap:
        raise HTTPException(404, "该考室尚无封场快照")
    data = json.loads(snap.snapshot_json)
    return {
        "snapshot_id": snap.id,
        "hall_id": hall_id,
        "sealed_at": snap.sealed_at.isoformat(),
        "min_manhattan": snap.min_manhattan,
        **data,
    }


@router.post("/{hall_id}/seal")
def seal_hall(hall_id: int, db: Session = Depends(get_db)):
    """封场：写入口闸、快照仓、待生效配置三处在同一事务里同时落下。"""
    hall = db.get(Hall, hall_id)
    if not hall:
        raise HTTPException(404, "考室不存在")
    if hall.sealed:
        raise HTTPException(409, "考室已封场，禁止重复封场")
    plan = db.scalars(
        select(SeatPlan).where(SeatPlan.hall_id == hall_id).order_by(SeatPlan.id.desc())
    ).first()
    if not plan:
        raise HTTPException(409, "空考室从未排过座，不允许封场")
    hall.sealed = True  # 1) 写入口闸落下
    hall.pending_min_manhattan = hall.min_manhattan  # 2) 待生效配置槽启用（镜像当前生效值）
    snap = SealSnapshot(  # 3) 封场当时的图/违规/统计整体入快照仓
        hall_id=hall.id,
        sealed_at=datetime.utcnow(),
        min_manhattan=hall.min_manhattan,
        snapshot_json=plan.result_json,
    )
    db.add(snap)
    db.commit()
    db.refresh(snap)
    return {"ok": True, "sealed": True, "snapshot_id": snap.id, **hall_state(hall)}


@router.post("/{hall_id}/unseal")
def unseal_hall(hall_id: int, db: Session = Depends(get_db)):
    """解封：待生效配置在此刻生效；快照仓保持封场当时的字，不得改写。"""
    hall = db.get(Hall, hall_id)
    if not hall:
        raise HTTPException(404, "考室不存在")
    if not hall.sealed:
        raise HTTPException(409, "考室未封场，无法解封")
    hall.sealed = False
    if hall.pending_min_manhattan is not None:
        hall.min_manhattan = hall.pending_min_manhattan
    hall.pending_min_manhattan = None
    db.commit()
    return {"ok": True, "sealed": False, **hall_state(hall)}


@router.patch("/{hall_id}")
def update_hall_config(hall_id: int, body: HallConfigUpdate, db: Session = Depends(get_db)):
    """改最小距：封场中只进待生效配置（不改快照、不出新方案）；解封才写生效值。"""
    hall = db.get(Hall, hall_id)
    if not hall:
        raise HTTPException(404, "考室不存在")
    if hall.sealed:
        hall.pending_min_manhattan = body.min_manhattan
        db.commit()
        return {"ok": True, "pending": True, **hall_state(hall)}
    hall.min_manhattan = body.min_manhattan
    db.commit()
    return {"ok": True, "pending": False, **hall_state(hall)}
