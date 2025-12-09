from sqlalchemy import select, func, case
from sqlalchemy.ext.asyncio import AsyncSession
from ..models import Order, Execution

class PositionsRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def by_client(self, client_id: str) -> list[dict]:
        signed_qty = case(
            (Order.side == "BUY", Execution.exec_qty),
            else_=-Execution.exec_qty,
        )
        sub = (
            select(
                Order.client_id.label("clientId"),
                Order.symbol.label("symbol"),
                func.sum(signed_qty).label("netQty"),
                (
                    func.sum(Execution.exec_qty * Execution.exec_px)
                    / func.nullif(func.sum(Execution.exec_qty), 0)
                ).label("avgPx"),
            )
            .join(Execution, Execution.order_id == Order.id)
            .where(Order.client_id == client_id)
            .group_by(Order.client_id, Order.symbol)
        )
        rows = (await self.db.execute(sub)).all()
        positions = []
        for r in rows:
            net_qty = float(r.netQty or 0)
            avg_px = float(r.avgPx or 0)
            positions.append({
                "clientId": r.clientId,
                "symbol": r.symbol,
                "netQty": net_qty,
                "avgPx": avg_px,
                "unrealizedPnl": 0.0,
            })
        return positions
