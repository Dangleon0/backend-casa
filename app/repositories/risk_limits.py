from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ..models import RiskLimit

# Fase 2.1 — Repositorio CRUD para risk_limits (async)
class RiskLimitsRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, data: dict) -> RiskLimit:
        item = RiskLimit(**data)
        self.db.add(item)
        await self.db.flush()
        return item

    async def get(self, id_: str) -> Optional[RiskLimit]:
        return await self.db.get(RiskLimit, id_)

    async def list(self, client_id: Optional[str] = None, symbol: Optional[str] = None) -> list[RiskLimit]:
        stmt = select(RiskLimit)
        if client_id is not None:
            stmt = stmt.where(RiskLimit.client_id == client_id)
        if symbol is not None:
            stmt = stmt.where(RiskLimit.symbol == symbol)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def by_client_symbol(self, client_id: str, symbol: str) -> Optional[RiskLimit]:
        """Preferir un límite específico por símbolo; si no hay, usar el general (symbol IS NULL)."""
        stmt_specific = select(RiskLimit).where(
            RiskLimit.client_id == client_id,
            RiskLimit.symbol == symbol,
        )
        specific = (await self.db.execute(stmt_specific)).scalars().first()
        if specific:
            return specific
        stmt_general = select(RiskLimit).where(
            RiskLimit.client_id == client_id,
            RiskLimit.symbol.is_(None),
        )
        return (await self.db.execute(stmt_general)).scalars().first()
