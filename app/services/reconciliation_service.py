from collections import defaultdict
from typing import List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from ..models import Order, Execution
from ..repositories.positions import PositionsRepository
from ..utils.enums import OrderStatus

# Fase 2.4 — Reconciliación interna (async)

async def reconcile_internal(db: AsyncSession) -> dict:
    """
    Verifica:
      - order.cum_qty == sum(executions)
      - status es coherente con qty y cum_qty
      - positions coinciden con executions
    Retorna dict con inconsistencias.
    """
    orders_inconsistent: List[dict] = []

    stmt_exec_sums = (
        select(Execution.order_id, func.sum(Execution.exec_qty).label("sum_exec"))
        .group_by(Execution.order_id)
    )
    exec_rows = await db.execute(stmt_exec_sums)
    exec_sums = {row.order_id: float(row.sum_exec or 0.0) for row in exec_rows}

    orders_result = await db.execute(select(Order))
    orders = orders_result.scalars().all()
    for o in orders:
        s = float(exec_sums.get(o.id, 0.0))
        inco_reasons: List[str] = []
        if abs((o.cum_qty or 0.0) - s) > 1e-9:
            inco_reasons.append("CUM_QTY_MISMATCH")

        qty = float(o.qty or 0.0)
        cum = float(o.cum_qty or 0.0)
        st = OrderStatus(o.status)
        if st == OrderStatus.FILLED and abs(cum - qty) > 1e-9:
            inco_reasons.append("STATUS_FILLED_BUT_CUM_QTY_NE_QTY")
        if st == OrderStatus.PARTIALLY_FILLED and (cum <= 0 or cum >= qty):
            inco_reasons.append("STATUS_PARTIAL_INCONSISTENT")
        if st != OrderStatus.FILLED and abs(cum - qty) <= 1e-9 and qty > 0:
            inco_reasons.append("STATUS_NOT_FILLED_BUT_CUM_EQ_QTY")

        if inco_reasons:
            orders_inconsistent.append({
                "orderId": o.id,
                "status": o.status,
                "qty": qty,
                "cumQty": cum,
                "reasons": inco_reasons,
            })

    stmt_exec_detail = select(
        Order.client_id, Order.symbol, Order.side, Execution.exec_qty, Execution.exec_px
    ).join(Execution, Execution.order_id == Order.id)
    rows = (await db.execute(stmt_exec_detail)).all()

    agg = defaultdict(float)
    for r in rows:
        sign = 1.0 if r.side == "BUY" else -1.0
        agg[(r.client_id, r.symbol)] += sign * float(r.exec_qty)

    positions_inconsistent: List[dict] = []
    repo = PositionsRepository(db)
    clients = {cid for (cid, _sym) in agg.keys()}
    for cid in clients:
        calc = {(cid, sym): qty for (cid2, sym), qty in agg.items() if cid2 == cid}
        repolist = await repo.by_client(cid)
        repo_map = {(p["clientId"], p["symbol"]): float(p["netQty"]) for p in repolist}
        keys = set(calc.keys()) | set(repo_map.keys())
        for key in keys:
            a = float(calc.get(key, 0.0))
            b = float(repo_map.get(key, 0.0))
            if abs(a - b) > 1e-9:
                positions_inconsistent.append({
                    "clientId": key[0],
                    "symbol": key[1],
                    "calcNetQty": a,
                    "repoNetQty": b,
                })

    ok = not orders_inconsistent and not positions_inconsistent
    return {
        "ok": ok,
        "orders_inconsistent": orders_inconsistent,
        "positions_inconsistent": positions_inconsistent,
    }
