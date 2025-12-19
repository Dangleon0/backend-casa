import os
import logging
from fastapi import APIRouter, Depends, HTTPException, Query, Header, status
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_session
from ...utils.enums import DepositStatus
from ...models import DepositIntent
from ..repositories.deposits import DepositIntentRepository
from ..schemas.deposits import DepositIntentCreate, DepositIntentOut

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/deposits", tags=["Deposits"])

def _resolve_client_id(clientId: str | None, x_client_id: str | None) -> str:
    return clientId or x_client_id or "demo-client-1"

def _is_sandbox() -> bool:
    return os.getenv("DEBUG", "0") == "1" or os.getenv("TESTING", "0") == "1"

@router.post("", response_model=DepositIntentOut, status_code=status.HTTP_201_CREATED)
async def create_deposit_intent(
    payload: DepositIntentCreate,
    clientId: str | None = Query(default=None),
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    db: AsyncSession = Depends(get_session),
):
    client_id = _resolve_client_id(clientId, x_client_id)

    # LOG: Ver qué amount llega del frontend
    logger.info(
        f"📥 [CREATE DEPOSIT] Received from frontend: "
        f"amount={payload.amount}, provider={payload.provider}, client_id={client_id}"
    )

    repo = DepositIntentRepository(db)
    intent = await repo.create({
        "client_id": client_id,
        "amount": float(payload.amount),
        "currency": payload.currency,
        "payment_method": payload.payment_method,
        "provider": payload.provider,
        "status": DepositStatus.PENDING.value,
        "metadata_": payload.metadata,
    })

    await db.commit()
    await db.refresh(intent)

    # LOG: Ver qué amount se guardó en la DB
    logger.info(
        f"💾 [CREATE DEPOSIT] Saved to DB: "
        f"deposit_id={intent.id}, amount={intent.amount}, provider={intent.provider}, "
        f"payment_url={intent.payment_url}"
    )

    # AUDIT LOG: Record deposit creation with full details for debugging
    logger.info(
        f"📊 [DEPOSIT AUDIT] client_id={client_id}, "
        f"payload_amount={payload.amount}, saved_amount={intent.amount}, "
        f"deposit_id={intent.id}, provider={intent.provider}, status={intent.status}"
    )

    # Auto-completar SOLO si provider es mock_stripe (permite usar Stripe real en paralelo)
    if payload.provider == "mock_stripe" and _is_sandbox():
        intent.status = DepositStatus.COMPLETED.value
        intent.confirmed_amount = intent.amount
        await db.commit()
        await db.refresh(intent)
        
        logger.info(
            f"🤖 [AUTO-COMPLETE] Deposit {intent.id} auto-completed for sandbox "
            f"(amount: {intent.amount} {intent.currency}, client_id: {client_id})"
        )

    return DepositIntentOut.from_orm_row(intent)

@router.get("", response_model=list[DepositIntentOut])
async def list_deposit_intents(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    clientId: str | None = Query(default=None),
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    db: AsyncSession = Depends(get_session),
):
    client_id = _resolve_client_id(clientId, x_client_id)
    repo = DepositIntentRepository(db)
    items = await repo.list_for_client(client_id, limit, offset)
    return [DepositIntentOut.from_orm_row(i) for i in items]

@router.get("/{deposit_id}", response_model=DepositIntentOut)
async def get_deposit_intent(
    deposit_id: str,
    clientId: str | None = Query(default=None),
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    db: AsyncSession = Depends(get_session),
):
    client_id = _resolve_client_id(clientId, x_client_id)
    repo = DepositIntentRepository(db)
    intent = await repo.get_by_id(deposit_id, client_id)
    if not intent:
        raise HTTPException(status_code=404, detail="Depósito no encontrado")
    return DepositIntentOut.from_orm_row(intent)
