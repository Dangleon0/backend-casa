
from types import SimpleNamespace

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from .db import get_session
from .models import Order as OrderModel
from .schemas import OrderCreateRequest, Order as OrderSchema, Position as PositionSchema
from .repositories.orders import OrderRepository
from .repositories.positions import PositionsRepository
# Fase 2 imports
from .repositories.risk_limits import RiskLimitsRepository
from .services.risk_service import validate_order
from .services.metrics import record, snapshot
from .services.reconciliation_service import reconcile_internal
from .utils.enums import OrderStatus
from .services.fix_gateway import fix_gateway

router = APIRouter()

get_db = get_session


@router.get("/health")
def health():
    return {"status": "OK"}


@router.post("/orders", response_model=OrderSchema, status_code=201)
async def create_order(payload: OrderCreateRequest, db: AsyncSession = Depends(get_db)):
    """Create an order after pre-trade risk validation, persist it, commit so FIX worker can see it,
    then enqueue FIX SEND event.
    """
    # Fase 2.1 — Validación de riesgo
    risk_repo = RiskLimitsRepository(db)
    client_limit = await risk_repo.by_client_symbol(payload.clientId, payload.symbol)
    # Si no hay límites definidos para el cliente, definir unos permisivos por defecto para no bloquear MVP
    if client_limit is None:
        # 24x7, sin bloqueo ni límites muy restrictivos
        client_limit = SimpleNamespace(
            client_id=payload.clientId,
            symbol=None,
            max_notional=1e12,
            max_order_size=1e9,
            trading_hours="00:00-23:59",
            blocked=False,
        )
    # Especificación del símbolo (estático)
    symbol_spec = {
        "ref_price": 2000.0 if payload.symbol.upper().startswith("XAU") else 1.10
    }

    ok, reason = validate_order(payload, client_limit, symbol_spec)
    if not ok:
        # Métricas
        record("orders_rejected", 1)
        record(f"risk_rejects:{reason}", 1)
        return JSONResponse(status_code=400, content={
            "error": "RISK_REJECT",
            "reason": reason,
        })

    # Fase 2.3 — métrica de orden aceptada
    record("orders_total", 1)

    repo = OrderRepository(db)

    order = await repo.create({
        "client_id": payload.clientId,
        "symbol": payload.symbol,
        "side": payload.side.value,
        "type": payload.type.value,
        "qty": payload.qty,
        "price": payload.price,
        "time_in_force": payload.timeInForce.value,
        "status": OrderStatus.NEW.value,
    })

    await db.commit()     # <<< CRITICAL FIX: allow worker thread to see the order

    await fix_gateway.enqueue_send(order.id)

    return to_schema(order)


@router.get("/orders", response_model=list[OrderSchema])
async def list_orders(
    clientId: str | None = Query(default=None),
    symbol: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    repo = OrderRepository(db)
    items = await repo.list(clientId, symbol)
    return [to_schema(o) for o in items]


@router.get("/orders/{orderId}", response_model=OrderSchema)
async def get_order(orderId: str, db: AsyncSession = Depends(get_db)):
    repo = OrderRepository(db)
    order = await repo.get(orderId)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return to_schema(order)


@router.post("/orders/{orderId}/cancel", response_model=OrderSchema)
async def cancel_order(orderId: str, db: AsyncSession = Depends(get_db)):
    """Commit DB before enqueueing FIX cancel event."""
    repo = OrderRepository(db)

    order = await repo.get(orderId)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    await db.commit()     # <<< CRITICAL FIX: persist order state before FIX cancel

    await fix_gateway.enqueue_cancel(order.id)

    return to_schema(order)


@router.get("/positions", response_model=list[PositionSchema])
async def positions(clientId: str = Query(...), db: AsyncSession = Depends(get_db)):
    repo = PositionsRepository(db)
    items = await repo.by_client(clientId)
    return [PositionSchema(**i) for i in items]


# Fase 2.3 — Métricas
@router.get("/metrics")
def metrics():
    return snapshot()

# Fase 2.4 — Admin reconcile
@router.get("/admin/reconcile/internal")
async def admin_reconcile(db: AsyncSession = Depends(get_db)):
    return await reconcile_internal(db)


# --------------------------
# Mapper DB → API Schema
# --------------------------

def to_schema(o: OrderModel) -> OrderSchema:
    return OrderSchema(
        id=o.id,
        clientId=o.client_id,
        symbol=o.symbol,
        side=o.side,
        type=o.type,
        qty=o.qty,
        price=o.price,
        status=o.status,
        cumQty=o.cum_qty,
        avgPx=o.avg_px,
        createdAt=o.created_at,
        updatedAt=o.updated_at,
    )
