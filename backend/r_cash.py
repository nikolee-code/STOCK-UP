from fastapi import APIRouter
from common import *

router = APIRouter(prefix="/api")


class OpenIn(BaseModel):
    opening_amount: float


class CloseIn(BaseModel):
    counted_amount: float
    note: str = ""


def cash_sales_of(methods):
    return next((m["total"] for m in methods if m["method"] == "efectivo"), 0.0)


@router.get("/cash/current")
def cash_current(u=Depends(need("cash.own")), db=Depends(get_db)):
    blind = get_setting(db, "blind_close", "1") == "1"
    cs = db.query(CashSession).filter_by(user_id=u.id, status="abierta").first()
    if not cs:
        return {"session": None, "blind": blind}
    methods = by_method(db, cs.id)
    exp = cash_expenses_total(db, cs.id)
    out = {"id": cs.id, "opening_amount": cs.opening_amount, "opened_at": iso(cs.opened_at),
           "digital": [m for m in methods if m["method"] != "efectivo"], "cash_expenses": exp}
    if not blind:  # el administrador puede elegir que el monto esperado se vea durante el turno
        sales = cash_sales_of(methods)
        out["cash_sales"] = sales
        out["expected"] = round(cs.opening_amount + sales - exp, 2)
    return {"session": out, "blind": blind}


@router.post("/cash/open")
def cash_open(d: OpenIn, u=Depends(need("cash.own")), db=Depends(get_db)):
    if db.query(CashSession).filter_by(user_id=u.id, status="abierta").first():
        raise HTTPException(400, "Ya tienes una caja abierta")
    if d.opening_amount < 0:
        raise HTTPException(400, "Monto no válido")
    db.add(CashSession(user_id=u.id, opening_amount=d.opening_amount))
    log(db, u, "CAJA_ABIERTA", f"Saldo inicial S/ {d.opening_amount:.2f}")
    db.commit()
    return {"ok": True}


@router.post("/cash/close")
def cash_close(d: CloseIn, u=Depends(need("cash.own")), db=Depends(get_db)):
    cs = db.query(CashSession).filter_by(user_id=u.id, status="abierta").first()
    if not cs:
        raise HTTPException(400, "No tienes una caja abierta")
    if d.counted_amount < 0:
        raise HTTPException(400, "El efectivo contado no puede ser negativo")
    methods = by_method(db, cs.id)
    sales = cash_sales_of(methods)
    exp = cash_expenses_total(db, cs.id)
    expected = round(cs.opening_amount + sales - exp, 2)  # solo el efectivo cuenta en el arqueo
    cs.counted_amount = d.counted_amount
    cs.expected_amount = expected
    cs.difference = round(d.counted_amount - expected, 2)
    cs.note = d.note
    cs.closed_at = datetime.utcnow()
    cs.status = "cerrada"
    log(db, u, "CAJA_CERRADA", f"Contado {d.counted_amount:.2f} / Esperado {expected:.2f} / Dif {cs.difference:.2f}")
    db.commit()
    return {"counted": d.counted_amount, "expected": expected, "difference": cs.difference,
            "opening": cs.opening_amount, "cash_sales": sales, "cash_expenses": exp,
            "methods": methods, "total_sales": round(sum(m["total"] for m in methods), 2)}


@router.get("/cash/sessions")
def cash_sessions(u=Depends(need("cash.review")), db=Depends(get_db)):
    rows = db.query(CashSession, User).join(User, User.id == CashSession.user_id) \
        .order_by(CashSession.id.desc()).limit(50).all()
    ids = [c.id for c, _ in rows]
    agg, exp = {}, {}
    if ids:
        q = db.query(Sale.cash_session_id, Sale.payment_method, func.sum(Sale.total)) \
            .filter(Sale.cash_session_id.in_(ids), Sale.status == "completada") \
            .group_by(Sale.cash_session_id, Sale.payment_method)
        for sid, m, t in q:
            agg.setdefault(sid, {})[PAYMENTS.get(m, m)] = round(t or 0, 2)
        q2 = db.query(Expense.cash_session_id, func.sum(Expense.amount)) \
            .filter(Expense.cash_session_id.in_(ids), Expense.from_cash == True, Expense.status == "activo") \
            .group_by(Expense.cash_session_id)
        for sid, t in q2:
            exp[sid] = round(t or 0, 2)
    return [{"id": c.id, "user": usr.full_name, "opened": iso(c.opened_at), "closed": iso(c.closed_at),
             "opening": c.opening_amount, "counted": c.counted_amount, "expected": c.expected_amount,
             "difference": c.difference, "status": c.status, "methods": agg.get(c.id, {}),
             "cash_expenses": exp.get(c.id, 0)} for c, usr in rows]