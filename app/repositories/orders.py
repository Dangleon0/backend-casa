from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ..models import Order as OrderModel
from ..utils.enums import OrderStatus

class OrderRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, data: dict) -> OrderModel:
        order = OrderModel(**data)
        self.db.add(order)
        await self.db.flush()  # assign id
        return order

    async def get(self, order_id: str) -> OrderModel | None:
        return await self.db.get(OrderModel, order_id)

    async def list(self, client_id: str | None, symbol: str | None) -> list[OrderModel]:
        stmt = select(OrderModel)
        if client_id:
            stmt = stmt.where(OrderModel.client_id == client_id)
        if symbol:
            stmt = stmt.where(OrderModel.symbol == symbol)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def save(self, order: OrderModel):
        self.db.add(order)

    async def set_status(self, order: OrderModel, status: OrderStatus):
        order.status = status
        self.db.add(order)
