import asyncio
import random
from typing import Optional
from ..db import AsyncSessionLocal
from ..models import Order as OrderModel, Execution
from ..utils.enums import OrderStatus
from .events import SendOrderEvent, CancelOrderEvent
# Fase 2.2 — EventBus y métricas
from .event_bus import event_bus
from .metrics import record


class FixGateway:
    def __init__(self):
        self.queue: asyncio.Queue = asyncio.Queue()
        self.worker_task: Optional[asyncio.Task] = None

    async def start(self):
        """Start the FIX worker task once FastAPI starts."""
        if self.worker_task is None or self.worker_task.done():
            print("Starting FIX worker task...")
            self.worker_task = asyncio.create_task(self._worker())

    async def enqueue_send(self, order_id: str):
        print(f"[FIX] Enqueued SEND {order_id}")
        await self.queue.put(SendOrderEvent(order_id))

    async def enqueue_cancel(self, order_id: str):
        print(f"[FIX] Enqueued CANCEL {order_id}")
        await self.queue.put(CancelOrderEvent(order_id))

    async def _worker(self):
        print("FIX worker STARTED")
        while True:
            evt = await self.queue.get()
            try:
                if isinstance(evt, SendOrderEvent):
                    await self._process_send(evt.order_id)
                elif isinstance(evt, CancelOrderEvent):
                    await self._process_cancel(evt.order_id)
            finally:
                self.queue.task_done()

    async def _process_send(self, order_id: str):
        async with AsyncSessionLocal() as db:
            order = await db.get(OrderModel, order_id)
            if not order:
                print(f"[FIX] Order NOT FOUND: {order_id}")
                return

            # Move to PENDING_SEND
            order.status = OrderStatus.PENDING_SEND
            db.add(order)
            await db.commit()
            print(f"[FIX] Order {order_id} → PENDING_SEND")
            self._publish_update(order)

            await asyncio.sleep(0.2)  # simulate delay
            order.status = OrderStatus.SENT
            db.add(order)
            await db.commit()
            print(f"[FIX] Order {order_id} → SENT")
            self._publish_update(order)

            # Process fills
            remaining = order.qty - order.cum_qty
            if remaining <= 0:
                return

            # 10% reject chance
            if random.random() < 0.1:
                order.status = OrderStatus.REJECTED
                db.add(order)
                await db.commit()
                print(f"[FIX] Order {order_id} → REJECTED")
                self._publish_update(order)
                return

            # Simulate fill or partial fill
            partial = random.random() < 0.5
            lot1 = remaining * (0.4 if partial else 1.0)
            px = order.price or self._mock_market_px(order.symbol)

            # First fill
            exec1 = Execution(order_id=order.id, exec_qty=lot1, exec_px=px)
            db.add(exec1)
            order.cum_qty += lot1
            order.avg_px = px if order.avg_px is None else (order.avg_px + px) / 2
            order.status = (
                OrderStatus.PARTIALLY_FILLED
                if order.cum_qty < order.qty
                else OrderStatus.FILLED
            )
            db.add(order)
            await db.commit()
            print(f"[FIX] Order {order_id} filled {lot1} @ {px}")
            self._publish_update(order)

            # If partial, finish later
            if order.cum_qty < order.qty:
                await asyncio.sleep(0.3)
                lot2 = order.qty - order.cum_qty
                exec2 = Execution(order_id=order.id, exec_qty=lot2, exec_px=px)
                db.add(exec2)
                order.cum_qty += lot2
                order.avg_px = px if order.avg_px is None else (order.avg_px + px) / 2
                order.status = OrderStatus.FILLED
                db.add(order)
                await db.commit()
                print(f"[FIX] Order {order_id} final fill {lot2} @ {px}")
                self._publish_update(order)

    async def _process_cancel(self, order_id: str):
        async with AsyncSessionLocal() as db:
            order = await db.get(OrderModel, order_id)
            if not order:
                print(f"[FIX] Cancel ignored: Order not found {order_id}")
                return

            if order.status in (
                OrderStatus.FILLED,
                OrderStatus.CANCELED,
                OrderStatus.REJECTED,
            ):
                print(f"[FIX] Cancel ignored: Order {order_id} already terminal")
                return

            await asyncio.sleep(0.2)
            order.status = OrderStatus.CANCELED
            db.add(order)
            await db.commit()
            print(f"[FIX] Order {order_id} → CANCELED")
            self._publish_update(order)

    def _mock_market_px(self, symbol: str) -> float:
        base = 2000.0 if symbol.upper().startswith("XAU") else 1.1000
        return round(base + random.uniform(-1, 1), 2)

    def _publish_update(self, order: OrderModel):
        event_bus.publish(
            f"orders.{order.client_id}",
            {
                "type": "ORDER_UPDATE",
                "orderId": order.id,
                "status": order.status,
                "cumQty": order.cum_qty,
                "avgPx": order.avg_px,
            },
        )
        record("fix_events_processed", 1)


# Global instance
fix_gateway = FixGateway()
