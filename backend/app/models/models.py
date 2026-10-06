from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
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
    # 写入口闸：封场=True 时禁止一切新方案生成；与「解封才可写」互斥
    sealed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # 待生效配置：封场期间的最小距修改只进这里，解封时才生效
    pending_min_manhattan: Mapped[int | None] = mapped_column(Integer, nullable=True)

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

class SealSnapshot(Base):
    """封场快照仓：封场当时的图/违规/统计整体写入，之后只读。

    只插不改不删——解封、再排、改配置都不得回写本表；
    再次封场追加新行，历史快照保持封场当时的字。
    """
    __tablename__ = "seal_snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    hall_id: Mapped[int] = mapped_column(ForeignKey("halls.id"))
    sealed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    min_manhattan: Mapped[int] = mapped_column(Integer)
    snapshot_json: Mapped[str] = mapped_column(Text, default="{}")
