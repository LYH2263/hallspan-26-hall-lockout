import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import Hall
from app.services import seating_service as svc

router = APIRouter(prefix="/seating", tags=["seating"])


@router.post("/run")
def run_seating(hall_id: int = 1, db: Session = Depends(get_db)):
    hall = svc._lock_hall(db, hall_id)
    if hall.is_sealed:
        raise HTTPException(409, "考室已封场，禁止重新排座")
    return svc.generate_plan(db, hall)


@router.get("/latest")
def latest(hall_id: int = 1, db: Session = Depends(get_db)):
    hall = svc._get_hall_or_404(db, hall_id)
    data = svc.read_active_plan(db, hall)
    if data is None:
        # 仅未封场且尚无方案时保留原有的懒生成兜底
        return svc.generate_plan(db, hall)
    return data


@router.get("/violations")
def violations(hall_id: int = 1, db: Session = Depends(get_db)):
    hall = svc._get_hall_or_404(db, hall_id)
    data = svc.read_active_plan(db, hall)
    if data is None:
        data = svc.generate_plan(db, hall)
    return {
        "hall_id": hall_id,
        "violations": data.get("violations", []),
        "unplaced": data.get("unplaced", []),
        "snapshot": bool(data.get("snapshot")),
    }


@router.get("/stats")
def stats(hall_id: int = 1, db: Session = Depends(get_db)):
    hall = svc._get_hall_or_404(db, hall_id)
    data = svc.read_active_plan(db, hall)
    if data is None:
        data = svc.generate_plan(db, hall)
    return {"hall_id": hall_id, **data.get("stats", {}), "snapshot": bool(data.get("snapshot"))}


@router.post("/seal")
def seal(hall_id: int = 1, db: Session = Depends(get_db)):
    return svc.seal_hall(db, hall_id)


@router.post("/unseal")
def unseal(hall_id: int = 1, db: Session = Depends(get_db)):
    return svc.unseal_hall(db, hall_id)


@router.post("/config")
def config(min_manhattan: int, hall_id: int = 1, db: Session = Depends(get_db)):
    return svc.stage_or_apply_distance(db, hall_id, min_manhattan)


@router.get("/snapshot/latest")
def latest_snapshot(hall_id: int = 1, db: Session = Depends(get_db)):
    hall = svc._get_hall_or_404(db, hall_id)
    snap = svc.latest_snapshot(db, hall.id)
    if snap is None:
        raise HTTPException(404, "该考室暂无封场快照")
    return {
        "id": snap.id,
        "hall_id": snap.hall_id,
        "seat_plan_id": snap.seat_plan_id,
        "sealed_at": snap.sealed_at.isoformat() if snap.sealed_at else None,
        **json.loads(snap.result_json),
    }
