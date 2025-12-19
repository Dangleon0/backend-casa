from fastapi import APIRouter, Depends, Header, Query
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from ..db import get_session
from ..models import WithdrawalRequest, DepositIntent
from .routers.deposits import router as deposits_router
from .routers.stripe import router as stripe_router
from .routers.withdrawals import router as withdrawals_router
from .routers.kyc import router as kyc_router

v1 = APIRouter(prefix="/v1")

# --------- Helpers ---------

def _resolve_client_id(clientId: str | None, x_client_id: str | None) -> str:
    return clientId or x_client_id or "demo-client-1"


# --------- Dashboard ---------

@v1.get("/dashboard")
async def dashboard(
    clientId: str | None = Query(default=None),
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    db: AsyncSession = Depends(get_session),
):
    client_id = _resolve_client_id(clientId, x_client_id)
    # Sum only completed deposit intents; use confirmed_amount if present else amount
    dep_sum_expr = func.coalesce(
        func.sum(func.coalesce(DepositIntent.confirmed_amount, DepositIntent.amount)),
        0.0,
    )
    dep_sum = (
        await db.execute(
            select(dep_sum_expr).where(
                DepositIntent.client_id == client_id,
                DepositIntent.status == "completed",
            )
        )
    ).scalar() or 0.0

    # Solo contar retiros completados, no los pendientes o rechazados
    wd_sum = (
        await db.execute(
            select(func.coalesce(func.sum(WithdrawalRequest.amount), 0.0)).where(
                WithdrawalRequest.client_id == client_id,
                WithdrawalRequest.status == "completed"
            )
        )
    ).scalar() or 0.0

    saldo = float(dep_sum) - float(wd_sum)
    return {"saldo_retirable": saldo, "estrategias": []}




# Include v1 routers for deposits, withdrawals, stripe, and kyc
v1.include_router(deposits_router)
v1.include_router(withdrawals_router)
v1.include_router(stripe_router)
v1.include_router(kyc_router)
