from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base

class Hall(Base):
    __tablename__ = "halls"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    rows: Mapped[int] = mapped_column(Integer)
    cols: Mapped[int] = mapped_column(Integer)
    min_manhattan: Mapped[int] = mapped_column(Integer, default=2)
    # 封场状态：is_sealed 写入口闸；pending_min_manhattan 封场期间的待生效间距
    is_sealed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    pending_min_manhattan: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sealed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

class PaperSet(Base):
    __tablename__ = "paper_sets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    title: Mapped[str] = mapped_column(String(128))

class Candidate(Base):
    __tablename__ = "candidates"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    hall_id: Mapped[int] = mapped_column(ForeignKey("halls.id"))
    name: Mapped[str] = mapped_column(String(64))
    ticket_no: Mapped[str] = mapped_column(String(32))
    paper_id: Mapped[int] = mapped_column(ForeignKey("paper_sets.id"))

class SeatPlan(Base):
    __tablename__ = "seat_plans"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    hall_id: Mapped[int] = mapped_column(ForeignKey("halls.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    result_json: Mapped[str] = mapped_column(Text, default="{}")

class HallSnapshot(Base):
    """封场快照仓：封场当时的图/违规/统计原样落库，只追加、不修改不删除。"""
    __tablename__ = "hall_snapshots"
    __table_args__ = (Index("ix_hall_snapshots_hall_id", "hall_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    hall_id: Mapped[int] = mapped_column(ForeignKey("halls.id"), nullable=False)
    # 留存当时的方案 id，故意不加外键：方案行变动不影响快照只读
    seat_plan_id: Mapped[int] = mapped_column(Integer, nullable=False)
    sealed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    result_json: Mapped[str] = mapped_column(Text, nullable=False)
