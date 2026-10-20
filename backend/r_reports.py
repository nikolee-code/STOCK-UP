from fastapi import APIRouter
from common import *

router = APIRouter(prefix="/api")

IMPORTANT = ("VENTA_ANULADA", "EGRESO_ANULADO", "INVENTARIO", "CAJA_CERRADA", "PRECIO_CAMBIADO", "LOGIN_FALLIDO")


@router.get("/dashboard")
def dashboard(u=Depends(need("dashboard")), db=Depends(get_db)):
    see_all = allowed(u, "sales.read")
    base = [Sale.status == "completada"]
    if not see_all:
        base.append(Sale.user_id == u.id)  # el cajero solo ve lo suyo
    start = day_start_utc(today_str())
    end = start + timedelta(days=1)
    today = [Sale.created_at >= start, Sale.created_at < end]

    sales_today = round(db.query(func.coalesce(func.sum(Sale.total), 0)).filter(*base, *today).scalar(), 2)
    count_today = db.query(func.count(Sale.id)).filter(*base, *today).scalar()

    days = []
    for i in range(6, -1, -1):
        a = start - timedelta(days=i)
        t = db.query(func.coalesce(func.sum(Sale.total), 0)).filter(
            *base, Sale.created_at >= a, Sale.created_at < a + timedelta(days=1)).scalar()
        days.append({"label": (a - timedelta(hours=5)).strftime("%d/%m"), "total": round(t, 2)})

    # Egresos y ganancia (según el permiso de cada rol)
    expenses_today = None
    if allowed(u, "expenses.read") or allowed(u, "expenses.create"):
        econds = [Expense.status == "activo", Expense.created_at >= start, Expense.created_at < end]
        if not allowed(u, "expenses.read"):
            econds.append(Expense.user_id == u.id)
        expenses_today = round(db.query(func.coalesce(func.sum(Expense.amount), 0)).filter(*econds).scalar(), 2)
    profit_today = None
    if allowed(u, "profit.read"):
        cost = db.query(func.coalesce(func.sum(SaleItem.cost), 0)).select_from(SaleItem) \
            .join(Sale, Sale.id == SaleItem.sale_id).filter(*base, *today).scalar()
        profit_today = round(sales_today - cost - (expenses_today or 0), 2)  # ganancia neta estimada

    # Productos que necesitan reposición
    lows = db.query(Product).filter(Product.active == True, Product.stock <= Product.min_stock).all()
    lows.sort(key=lambda p: (p.stock / p.min_stock) if p.min_stock else 0)
    low = [{"name": p.name, "stock": p.stock, "min_stock": p.min_stock, "unit": p.unit,
            "status": "agotado" if p.stock <= 0 else "bajo"} for p in lows[:10]]
    out_count = sum(1 for p in lows if p.stock <= 0)

    by_user = []
    if see_all:
        rows = db.query(User.full_name, func.sum(Sale.total), func.count(Sale.id)) \
            .select_from(Sale).join(User, User.id == Sale.user_id).filter(*base, *today) \
            .group_by(User.full_name).order_by(func.sum(Sale.total).desc()).all()
        by_user = [{"name": n, "total": round(t or 0, 2), "count": c} for n, t, c in rows]

    rows = db.query(Sale.payment_method, func.sum(Sale.total)).filter(*base, *today) \
        .group_by(Sale.payment_method).all()
    by_pay = [{"label": PAYMENTS.get(m, m), "total": round(t or 0, 2)} for m, t in rows]

    since = start - timedelta(days=29)
    top_rows = db.query(SaleItem.product_id, func.sum(SaleItem.qty * SaleItem.unit_factor),
                        func.sum(SaleItem.qty * SaleItem.price)) \
        .select_from(SaleItem).join(Sale, Sale.id == SaleItem.sale_id) \
        .filter(*base, Sale.created_at >= since, Sale.created_at < end) \
        .group_by(SaleItem.product_id).order_by(func.sum(SaleItem.qty * SaleItem.price).desc()).limit(5).all()
    names = {p.id: (p.name, p.unit) for p in db.query(Product)}
    top = [{"name": names.get(pid, ("—", ""))[0], "unit": names.get(pid, ("", ""))[1],
            "units": round(un or 0, 3), "amount": round(am or 0, 2)} for pid, un, am in top_rows]

    recent = db.query(Sale).filter(*base).order_by(Sale.id.desc()).limit(6).all()

    events = []
    if allowed(u, "audit.read"):
        ev = db.query(AuditLog, User).outerjoin(User, User.id == AuditLog.user_id) \
            .filter(AuditLog.action.in_(IMPORTANT)).order_by(AuditLog.id.desc()).limit(8).all()
        events = [{"date": iso(a.created_at), "user": usr.full_name if usr else "—",
                   "action": a.action, "detail": a.detail} for a, usr in ev]

    return {
        "sales_today": sales_today, "count_today": count_today,
        "expenses_today": expenses_today, "profit_today": profit_today,
        "products": db.query(func.count(Product.id)).filter(Product.active == True).scalar(),
        "low_count": len(lows), "out_count": out_count,
        "days": days, "low": low, "by_user": by_user, "by_pay": by_pay, "top": top, "events": events,
        "recent": [{"id": s.id, "total": s.total, "pay": PAYMENTS.get(s.payment_method, s.payment_method),
                    "doc": doc_label(s), "date": iso(s.created_at)} for s in recent],
    }


@router.get("/audit")
def audit(user_id: Optional[int] = None, action: Optional[str] = None,
          date_from: Optional[str] = None, date_to: Optional[str] = None, limit: int = 300,
          u=Depends(need("audit.read")), db=Depends(get_db)):
    q = db.query(AuditLog, User).outerjoin(User, User.id == AuditLog.user_id)
    if user_id:
        q = q.filter(AuditLog.user_id == user_id)
    if action and action.strip():
        q = q.filter(AuditLog.action.ilike(f"%{action.strip()}%"))
    if date_from or date_to:
        a, b = day_range(date_from, date_to)
        q = q.filter(AuditLog.created_at >= a, AuditLog.created_at < b)
    rows = q.order_by(AuditLog.id.desc()).limit(min(limit, 1000)).all()
    return [{"id": a.id, "user": usr.full_name if usr else "—", "action": a.action,
             "detail": a.detail, "date": iso(a.created_at)} for a, usr in rows]


@router.get("/audit/actions")
def audit_actions(u=Depends(need("audit.read")), db=Depends(get_db)):
    return sorted(r[0] for r in db.query(AuditLog.action).distinct() if r[0])
@router.get("/audit")
def audit(user_id: Optional[int] = None, action: Optional[str] = None,
          date_from: Optional[str] = None, date_to: Optional[str] = None, limit: int = 300,
          u=Depends(need("audit.read")), db=Depends(get_db)):
    q = db.query(AuditLog, User).outerjoin(User, User.id == AuditLog.user_id)
    if user_id:
        q = q.filter(AuditLog.user_id == user_id)
    if action and action.strip():
        q = q.filter(AuditLog.action.ilike(f"%{action.strip()}%"))
    if date_from or date_to:
        a, b = day_range(date_from, date_to)
        q = q.filter(AuditLog.created_at >= a, AuditLog.created_at < b)
    rows = q.order_by(AuditLog.id.desc()).limit(min(limit, 1000)).all()
    return [{"id": a.id, "user": usr.full_name if usr else "—", "action": a.action,
             "detail": a.detail, "date": iso(a.created_at)} for a, usr in rows]


@router.get("/audit/actions")
def audit_actions(u=Depends(need("audit.read")), db=Depends(get_db)):
    return sorted(r[0] for r in db.query(AuditLog.action).distinct() if r[0])