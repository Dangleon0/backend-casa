import uuid
from datetime import datetime
from sqlalchemy import String, Float, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .db import Base

# ------------------------------
# Fase 2 — Nuevos modelos
# ------------------------------

class Order(Base):
    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    client_id: Mapped[str] = mapped_column(String, index=True)
    symbol: Mapped[str] = mapped_column(String, index=True)
    side: Mapped[str] = mapped_column(String)
    type: Mapped[str] = mapped_column(String)
    qty: Mapped[float] = mapped_column(Float)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    time_in_force: Mapped[str] = mapped_column(String, default="GTC")

    status: Mapped[str] = mapped_column(String, default="NEW", index=True)
    cum_qty: Mapped[float] = mapped_column(Float, default=0.0)
    avg_px: Mapped[float | None] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    executions: Mapped[list["Execution"]] = relationship("Execution", back_populates="order", cascade="all, delete-orphan")

class Execution(Base):
    __tablename__ = "executions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    order_id: Mapped[str] = mapped_column(String, ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    exec_qty: Mapped[float] = mapped_column(Float)
    exec_px: Mapped[float] = mapped_column(Float)
    exec_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    order: Mapped[Order] = relationship("Order", back_populates="executions")

# Fase 2.1 — Tabla de límites de riesgo
class RiskLimit(Base):
    __tablename__ = "risk_limits"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    client_id: Mapped[str] = mapped_column(String, index=True)
    symbol: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    max_notional: Mapped[float] = mapped_column(Float)
    max_order_size: Mapped[float] = mapped_column(Float)
    trading_hours: Mapped[str] = mapped_column(String)  # formato "HH:MM-HH:MM"
    blocked: Mapped[bool] = mapped_column(Boolean, default=False)
