import json
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import Candidate, Hall, SealSnapshot, SeatPlan
from app.services.seat_engine import find_violations, place_candidates, plan_to_dict
router = APIRouter(prefix="/seating", tags=["seating"])


def _get_hall(db: Session, hall_id: int) -> Hall:
    hall = db.get(Hall, hall_id)
    if not hall:
        raise HTTPException(404, "考室不存在")
    return hall


def _with_state(hall: Hall, data: dict) -> dict:
    """在方案/快照内容上叠加考室当前闸态，供前端区分快照只读与可写。"""
    hall_info = dict(data.get("hall") or {})
    hall_info.update({
        "id": hall.id,
        "name": hall.name,
        "sealed": hall.sealed,
        "pending_min_manhattan": hall.pending_min_manhattan,
    })
    return {**data, "hall": hall_info}


@router.post("/run")
def run_seating(hall_id: int = 1, db: Session = Depends(get_db)):
    hall = _get_hall(db, hall_id)
    if hall.sealed:
        # 写入口闸：封场禁写，不新增任何方案行
        raise HTTPException(409, "考室已封场，禁止生成新方案，请先解封")
    cands = [{"id": c.id, "name": c.name, "ticket_no": c.ticket_no, "paper_id": c.paper_id}
             for c in db.scalars(select(Candidate).where(Candidate.hall_id == hall_id)).all()]
    assigns, unplaced = place_candidates(hall.rows, hall.cols, hall.min_manhattan, cands)
    viols = find_violations(hall.rows, hall.cols, hall.min_manhattan, assigns)
    result = plan_to_dict(assigns, unplaced, viols, hall.rows, hall.cols)
    result["hall"] = {"id": hall.id, "name": hall.name, "min_manhattan": hall.min_manhattan}
    plan = SeatPlan(hall_id=hall_id, created_at=datetime.utcnow(), result_json=json.dumps(result, ensure_ascii=False))
    db.add(plan); db.commit(); db.refresh(plan)
    return {"id": plan.id, **_with_state(hall, result)}


@router.get("/latest")
def latest(hall_id: int = 1, db: Session = Depends(get_db)):
    hall = _get_hall(db, hall_id)
    if hall.sealed:
        # 封场期间图/违规/统计只读，唯一读源是快照仓
        snap = db.scalars(
            select(SealSnapshot).where(SealSnapshot.hall_id == hall_id)
            .order_by(SealSnapshot.id.desc())
        ).first()
        if not snap:
            raise HTTPException(409, "考室已封场但缺少封场快照")
        data = json.loads(snap.snapshot_json)
        return {"id": snap.id, "snapshot": True, "sealed_at": snap.sealed_at.isoformat(),
                **_with_state(hall, data)}
    plan = db.scalars(select(SeatPlan).where(SeatPlan.hall_id == hall_id).order_by(SeatPlan.id.desc())).first()
    if not plan:
        return run_seating(hall_id=hall_id, db=db)
    data = json.loads(plan.result_json)
    return {"id": plan.id, **_with_state(hall, data)}


@router.get("/violations")
def violations(hall_id: int = 1, db: Session = Depends(get_db)):
    data = latest(hall_id=hall_id, db=db)
    return {"hall_id": hall_id, "sealed": data["hall"]["sealed"],
            "violations": data.get("violations", []), "unplaced": data.get("unplaced", [])}


@router.get("/stats")
def stats(hall_id: int = 1, db: Session = Depends(get_db)):
    data = latest(hall_id=hall_id, db=db)
    return {"hall_id": hall_id, "sealed": data["hall"]["sealed"], **data.get("stats", {})}
