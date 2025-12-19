import os
import logging
from fastapi import APIRouter, Depends, HTTPException, Query, Header, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_session
from ...utils.enums import WithdrawalStatus
from ..repositories.withdrawals import WithdrawalRequestRepository
from ..schemas.withdrawals import WithdrawalRequestCreate, WithdrawalRequestOut
from ...services.withdrawal_receipt import generate_withdrawal_receipt_pdf

logger = logging.getLogger(__name__)

# Using prefix "/withdrawals" because v1 router already has prefix "/v1"
router = APIRouter(prefix="/withdrawals", tags=["Withdrawals"])


def _resolve_client_id(clientId: str | None, x_client_id: str | None) -> str:
    return clientId or x_client_id or "demo-client-1"


def _auto_approve_enabled() -> bool:
    return os.getenv("AUTO_APPROVE_WITHDRAWALS", "0") == "1"


@router.post("", response_model=WithdrawalRequestOut, status_code=status.HTTP_201_CREATED)
async def create_withdrawal_request(
    payload: WithdrawalRequestCreate,
    clientId: str | None = Query(default=None),
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    db: AsyncSession = Depends(get_session),
):
    client_id = _resolve_client_id(clientId, x_client_id)

    repo = WithdrawalRequestRepository(db)
    req = await repo.create({
        "client_id": client_id,
        "investment_id": payload.investment_id,
        "amount": float(payload.amount),
        "currency": payload.currency,

        "bank_code": payload.bank_code,
        "bank_name": payload.bank_name,
        "account_type": payload.account_type,
        "clabe": payload.clabe,
        "account_holder": payload.account_holder,

        "email": payload.email,
        "phone": payload.phone,
        "concept": payload.concept,

        "status": WithdrawalStatus.PENDING_REVIEW.value,
        "preview_snapshot": payload.preview_snapshot,
        "metadata_": payload.metadata,
    })
    await db.commit()
    await db.refresh(req)

    # Auto-approve and complete in sandbox/demo
    if _auto_approve_enabled():
        req.status = WithdrawalStatus.COMPLETED.value

        # Agregar metadata de sandbox
        if req.metadata_ is None:
            req.metadata_ = {}
        req.metadata_['stripe_transfer_id'] = f"tr_mock_{req.id}"
        req.metadata_['auto_approved'] = True

        await db.commit()
        await db.refresh(req)
        
        logger.info(
            f"🤖 [AUTO-APPROVE] Withdrawal {req.id} auto-completed for sandbox "
            f"(amount: {req.amount} {req.currency})"
        )

    return WithdrawalRequestOut.from_orm_row(req)


@router.get("", response_model=list[WithdrawalRequestOut])
async def list_withdrawal_requests(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    clientId: str | None = Query(default=None),
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    db: AsyncSession = Depends(get_session),
):
    client_id = _resolve_client_id(clientId, x_client_id)
    repo = WithdrawalRequestRepository(db)
    items = await repo.list_for_client(client_id, limit, offset)
    return [WithdrawalRequestOut.from_orm_row(i) for i in items]


@router.get("/{request_id}", response_model=WithdrawalRequestOut)
async def get_withdrawal_request(
    request_id: str,
    clientId: str | None = Query(default=None),
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    db: AsyncSession = Depends(get_session),
):
    client_id = _resolve_client_id(clientId, x_client_id)
    repo = WithdrawalRequestRepository(db)
    req = await repo.get_by_id(request_id, client_id)
    if not req:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")
    return WithdrawalRequestOut.from_orm_row(req)


@router.get("/{request_id}/receipt", response_class=Response)
async def download_withdrawal_receipt(
    request_id: str,
    clientId: str | None = Query(default=None),
    x_client_id: str | None = Header(default=None, alias="X-Client-Id"),
    db: AsyncSession = Depends(get_session),
):
    client_id = _resolve_client_id(clientId, x_client_id)
    repo = WithdrawalRequestRepository(db)
    withdrawal = await repo.get_by_id(request_id, client_id)
    if not withdrawal:
        logger.warning(
            f"Unauthorized/NotFound receipt download client_id={client_id} withdrawal_id={request_id}"
        )
        raise HTTPException(status_code=404, detail="Retiro no encontrado")

    stripe_transfer_id = None
    processed_at = None
    if withdrawal.metadata_:
        stripe_transfer_id = withdrawal.metadata_.get("stripe_transfer_id")
        if withdrawal.status in [WithdrawalStatus.COMPLETED.value, WithdrawalStatus.PROCESSING.value]:
            if withdrawal.status == WithdrawalStatus.COMPLETED.value:
                processed_at = withdrawal.updated_at

    user_display_name = withdrawal.account_holder or "Usuario"

    try:
        pdf_bytes = generate_withdrawal_receipt_pdf(
            withdrawal_id=withdrawal.id,
            user_name=user_display_name,
            user_email=withdrawal.email or "-",
            amount=withdrawal.amount,
            currency=withdrawal.currency,
            bank_name=withdrawal.bank_name,
            clabe=withdrawal.clabe,
            account_holder=withdrawal.account_holder,
            account_type=withdrawal.account_type,
            phone=withdrawal.phone,
            status=withdrawal.status,
            stripe_transfer_id=stripe_transfer_id,
            created_at=withdrawal.created_at,
            processed_at=processed_at,
            company_name=os.getenv("COMPANY_NAME", "Invertox"),
        )
    except Exception as e:
        logger.error(
            f"Error generating withdrawal PDF client_id={client_id} withdrawal_id={withdrawal.id} err={e}",
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail="No se pudo generar el comprobante")

    filename = f"comprobante_retiro_{withdrawal.id}.pdf"
    logger.info(
        f"Receipt downloaded client_id={client_id} withdrawal_id={withdrawal.id} amount={withdrawal.amount} status={withdrawal.status}"
    )

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(pdf_bytes)),
        },
    )
