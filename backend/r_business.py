from fastapi import APIRouter
from pydantic import BaseModel
from uuid import uuid4
from common import *

router = APIRouter(prefix="/api")


class SupplierIn(BaseModel):
    name: str
    tax_id: str = ""
    phone: str = ""
    email: str = ""


class PurchaseLineIn(BaseModel):
    product_id: int
    qty: float
    unit_cost: float


class PurchaseIn(BaseModel):
    supplier_id: int
    invoice_no: str
    total: float
    initial_payment: float = 0
    note: str = ""
    items: list[PurchaseLineIn] = []


class PaymentIn(BaseModel):
    amount: float
    note: str = ""


class DiscountAuthorizationIn(BaseModel):
    supervisor_username: str
    supervisor_password: str
    amount: float


@router.get("/notifications")
def notifications(u=Depends(need("notifications.read")), db=Depends(get_db)):
    since = datetime.utcnow() - timedelta(days=30)
    rows = db.query(AuditLog).filter(AuditLog.action == "PRECIO_CAMBIADO", AuditLog.created_at >= since) \
        .order_by(AuditLog.id.desc()).limit(12).all()
    out = []
    for event in rows:
        product_name = event.detail.split(":", 1)[0].split(" · ", 1)[0].strip()
        product = db.query(Product).filter(Product.name == product_name, Product.active == True).first()
        available = ""
        if product:
            packs = [f"{int(product.stock // x.factor)} {x.name}" for x in db.query(Presentation).filter(
                Presentation.product_id == product.id, Presentation.active == True).order_by(Presentation.factor)]
            available = f" · Disponible: {product.stock:g} {product.unit}" + (f" ({', '.join(packs)})" if packs else "")
        out.append({"kind": "price", "title": "Precio actualizado",
                    "detail": event.detail + available, "date": iso(event.created_at)})
    today = today_str()
    for offer in db.query(Promotion).filter(Promotion.active == True).order_by(Promotion.id.desc()).limit(12):
        if (not offer.starts or offer.starts <= today) and (not offer.ends or offer.ends >= today):
            product = db.get(Product, offer.product_id) if offer.scope == "product" and offer.product_id else None
            available = ""
            if product and product.active:
                packs = [f"{int(product.stock // x.factor)} {x.name}" for x in db.query(Presentation).filter(
                    Presentation.product_id == product.id, Presentation.active == True).order_by(Presentation.factor)]
                available = f" · Disponible: {product.stock:g} {product.unit}" + (f" ({', '.join(packs)})" if packs else "")
            elif not product:
                available = " · Consulta existencias en Productos."
            out.append({"kind": "offer", "title": "Oferta disponible", "detail": offer.name + available,
                        "date": "Vigente"})
    return out[:20]


@router.get("/finance/summary")
def finance_summary(date_from: Optional[str] = None, date_to: Optional[str] = None,
                    u=Depends(need("finance.read")), db=Depends(get_db)):
    a, b = day_range(date_from, date_to)
    done = [Sale.status == "completada", Sale.created_at >= a, Sale.created_at < b]
    income = float(db.query(func.coalesce(func.sum(Sale.total), 0)).filter(*done).scalar() or 0)
    extra_income = float(db.query(func.coalesce(func.sum(CashIncome.amount), 0)).filter(
        CashIncome.created_at >= a, CashIncome.created_at < b).scalar() or 0)
    income += extra_income
    cogs = float(db.query(func.coalesce(func.sum(SaleItem.cost), 0)).select_from(SaleItem)
                 .join(Sale, Sale.id == SaleItem.sale_id).filter(*done).scalar() or 0)
    expq = [Expense.status == "activo", Expense.created_at >= a, Expense.created_at < b]
    expenses = float(db.query(func.coalesce(func.sum(Expense.amount), 0)).filter(*expq).scalar() or 0)
    payments = float(db.query(func.coalesce(func.sum(PurchasePayment.amount), 0)).filter(
        PurchasePayment.created_at >= a, PurchasePayment.created_at < b).scalar() or 0)
    opening = float(db.query(func.coalesce(func.sum(CashSession.opening_amount), 0)).filter(
        CashSession.opened_at >= a, CashSession.opened_at < b).scalar() or 0)
    balance = float(db.query(func.coalesce(func.sum(Sale.total), 0)).filter(Sale.status == "completada").scalar() or 0)
    balance -= float(db.query(func.coalesce(func.sum(Expense.amount), 0)).filter(Expense.status == "activo").scalar() or 0)
    balance -= float(db.query(func.coalesce(func.sum(PurchasePayment.amount), 0)).scalar() or 0)
    balance += float(db.query(func.coalesce(func.sum(CashIncome.amount), 0)).scalar() or 0)
    balance += float(db.query(func.coalesce(func.sum(CashSession.opening_amount), 0)).filter(CashSession.status == "abierta").scalar() or 0)
    profit = income - cogs - expenses
    days = []
    cursor = a
    while cursor < b and len(days) < 31:
        end = cursor + timedelta(days=1)
        inc = db.query(func.coalesce(func.sum(Sale.total), 0)).filter(
            Sale.status == "completada", Sale.created_at >= cursor, Sale.created_at < end).scalar() or 0
        inc += db.query(func.coalesce(func.sum(CashIncome.amount), 0)).filter(
            CashIncome.created_at >= cursor, CashIncome.created_at < end).scalar() or 0
        exp = db.query(func.coalesce(func.sum(Expense.amount), 0)).filter(
            Expense.status == "activo", Expense.created_at >= cursor, Expense.created_at < end).scalar() or 0
        pay = db.query(func.coalesce(func.sum(PurchasePayment.amount), 0)).filter(
            PurchasePayment.created_at >= cursor, PurchasePayment.created_at < end).scalar() or 0
        days.append({"label": (cursor - timedelta(hours=5)).strftime("%d/%m"),
                     "income": round(float(inc), 2), "outflow": round(float(exp + pay), 2)})
        cursor = end
    recent = []
    for sale, usr in db.query(Sale, User).join(User, User.id == Sale.user_id).filter(*done).order_by(Sale.id.desc()).limit(10):
        recent.append({"date": iso(sale.created_at), "_sort": sale.created_at, "concept": f"Venta {doc_label(sale)}",
                       "kind": "Ingreso", "amount": round(sale.total or 0, 2)})
    for entry in db.query(CashIncome).filter(CashIncome.created_at >= a, CashIncome.created_at < b).order_by(CashIncome.id.desc()).limit(10):
        recent.append({"date": iso(entry.created_at), "_sort": entry.created_at, "concept": entry.concept,
                       "kind": "Ingreso de caja", "amount": round(entry.amount or 0, 2)})
    for expense, usr in db.query(Expense, User).join(User, User.id == Expense.user_id).filter(*expq).order_by(Expense.id.desc()).limit(10):
        recent.append({"date": iso(expense.created_at), "_sort": expense.created_at, "concept": expense.concept,
                       "kind": "Egreso", "amount": -round(expense.amount or 0, 2)})
    for payment, purchase in db.query(PurchasePayment, Purchase).join(Purchase, Purchase.id == PurchasePayment.purchase_id) \
            .filter(PurchasePayment.created_at >= a, PurchasePayment.created_at < b).order_by(PurchasePayment.id.desc()).limit(10):
        recent.append({"date": iso(payment.created_at), "_sort": payment.created_at, "concept": f"Pago factura {purchase.invoice_no}",
                       "kind": "Compra", "amount": -round(payment.amount or 0, 2)})
    recent.sort(key=lambda x: x["_sort"], reverse=True)
    for row in recent: row.pop("_sort", None)
    outflow = expenses + payments
    return {"income": round(income, 2), "expenses": round(expenses, 2), "purchase_payments": round(payments, 2),
            "profit": round(profit, 2), "balance": round(balance, 2),
            "income_share": round(income * 100 / (income + outflow), 1) if income + outflow else 0,
            "days": days, "recent": recent[:15]}


@router.get("/suppliers")
def suppliers(u=Depends(need("purchases.read")), db=Depends(get_db)):
    return [{"id": x.id, "name": x.name, "tax_id": x.tax_id or "", "phone": x.phone or "", "email": x.email or ""}
            for x in db.query(Supplier).filter(Supplier.active == True).order_by(Supplier.name)]


@router.post("/suppliers")
def add_supplier(d: SupplierIn, u=Depends(need("purchases.manage")), db=Depends(get_db)):
    name = d.name.strip()
    if len(name) < 2:
        raise HTTPException(400, "Escribe el nombre del proveedor")
    item = Supplier(name=name, tax_id=d.tax_id.strip()[:20], phone=d.phone.strip()[:40], email=d.email.strip()[:120])
    db.add(item)
    db.flush()
    log(db, u, "PROVEEDOR_CREADO", name)
    db.commit()
    return {"ok": True, "id": item.id}


@router.get("/purchases")
def purchases(u=Depends(need("purchases.read")), db=Depends(get_db)):
    rows = db.query(Purchase, Supplier).join(Supplier, Supplier.id == Purchase.supplier_id) \
        .order_by(Purchase.id.desc()).limit(500).all()
    return [{"id": p.id, "supplier_id": s.id, "supplier": s.name, "invoice_no": p.invoice_no,
             "total": round(p.total, 2), "paid": round(p.paid or 0, 2), "balance": round(p.total - (p.paid or 0), 2),
             "note": p.note or "", "date": iso(p.created_at)} for p, s in rows]


@router.post("/purchases")
def add_purchase(d: PurchaseIn, u=Depends(need("purchases.manage")), db=Depends(get_db)):
    supplier = db.get(Supplier, d.supplier_id)
    if not supplier or not supplier.active:
        raise HTTPException(400, "Elige un proveedor activo")
    invoice = d.invoice_no.strip()
    if not invoice or d.total <= 0 or d.initial_payment < 0 or d.initial_payment > d.total:
        raise HTTPException(400, "Revisa el número de factura, el total y el pago inicial")
    if not d.items:
        raise HTTPException(400, "Agrega al menos un producto para recibir en almacén")
    total_items = 0
    for line in d.items:
        p = db.get(Product, line.product_id)
        if not p or not p.active or line.qty <= 0 or line.unit_cost < 0:
            raise HTTPException(400, "Revisa los productos, cantidades y costos de la compra")
        total_items += line.qty * line.unit_cost
    if abs(total_items - d.total) > 0.02:
        raise HTTPException(400, "El total de las líneas no coincide con el total de la factura")
    purchase = Purchase(supplier_id=supplier.id, invoice_no=invoice[:80], total=round(d.total, 2),
                        paid=round(d.initial_payment, 2), note=d.note.strip()[:200], created_by=u.id)
    db.add(purchase)
    db.flush()
    for line in d.items:
        p = db.get(Product, line.product_id)
        prev = p.stock
        p.stock = r3(p.stock + line.qty)
        p.cost = round(((p.cost or 0) * prev + line.unit_cost * line.qty) / p.stock, 4) if p.stock else line.unit_cost
        db.add(PurchaseItem(purchase_id=purchase.id, product_id=p.id, qty=line.qty, unit_cost=line.unit_cost))
        db.add(StockMovement(product_id=p.id, kind="entrada", motive="compra", qty=line.qty,
                             prev_stock=prev, new_stock=p.stock, reason=f"Factura {invoice[:80]} · {supplier.name}", user_id=u.id))
    if d.initial_payment > 0:
        db.add(PurchasePayment(purchase_id=purchase.id, amount=round(d.initial_payment, 2),
                               note="Pago inicial", created_by=u.id))
    log(db, u, "COMPRA_REGISTRADA", f"Factura {invoice[:80]} · {supplier.name} · S/ {d.total:.2f}")
    db.commit()
    return {"ok": True, "id": purchase.id}


@router.post("/purchases/{purchase_id}/payments")
def pay_purchase(purchase_id: int, d: PaymentIn, u=Depends(need("purchases.manage")), db=Depends(get_db)):
    purchase = db.get(Purchase, purchase_id)
    if not purchase:
        raise HTTPException(404, "Factura de compra no encontrada")
    remaining = round(purchase.total - (purchase.paid or 0), 2)
    if d.amount <= 0 or d.amount > remaining + 0.009:
        raise HTTPException(400, f"El pago debe ser mayor que cero y no superar el saldo de S/ {remaining:.2f}")
    purchase.paid = round((purchase.paid or 0) + d.amount, 2)
    db.add(PurchasePayment(purchase_id=purchase.id, amount=round(d.amount, 2),
                           note=d.note.strip()[:160] or "Abono", created_by=u.id))
    log(db, u, "COMPRA_PAGADA", f"Factura {purchase.invoice_no}: S/ {d.amount:.2f}")
    db.commit()
    return {"ok": True, "paid": purchase.paid, "balance": round(purchase.total - purchase.paid, 2)}


@router.get("/documents")
def documents(u=Depends(need_any("sales.read", "purchases.read")), db=Depends(get_db)):
    rows = []
    if allowed(u, "sales.read"):
        for sale, usr in db.query(Sale, User).join(User, User.id == Sale.user_id).order_by(Sale.id.desc()).limit(300):
            rows.append({"date": iso(sale.created_at), "type": "Venta", "number": doc_label(sale),
                         "issuer": usr.full_name, "concept": DOC_NAMES.get(sale.doc_type, sale.doc_type),
                         "total": round(sale.total or 0, 2), "status": sale.status})
    if allowed(u, "purchases.read"):
        for purchase, supplier in db.query(Purchase, Supplier).join(Supplier, Supplier.id == Purchase.supplier_id).order_by(Purchase.id.desc()).limit(300):
            rows.append({"date": iso(purchase.created_at), "type": "Compra", "number": purchase.invoice_no,
                         "issuer": supplier.name, "concept": "Factura de compra", "total": round(purchase.total, 2),
                         "status": "Pagada" if purchase.paid >= purchase.total else "Pendiente"})
    return sorted(rows, key=lambda x: x["date"], reverse=True)[:500]


@router.post("/discount-authorizations")
def authorize_discount(d: DiscountAuthorizationIn, u=Depends(current_user), db=Depends(get_db)):
    if u.role != "cajero":
        raise HTTPException(403, "La solicitud de descuento está disponible para cajeros")
    if not (d.amount > 0 and d.amount < 100000):
        raise HTTPException(400, "El descuento debe ser mayor que cero")
    supervisor = db.query(User).filter(User.username == d.supervisor_username.strip().lower(),
                                       User.role == "supervisor", User.active == True).first()
    if not supervisor or not verify_password(d.supervisor_password, supervisor.password_hash):
        log(db, u, "DESCUENTO_RECHAZADO", "No se validó la clave del supervisor")
        db.commit()
        raise HTTPException(403, "La clave de supervisor no es válida")
    token_id = uuid4().hex
    approval = DiscountApproval(token_id=token_id, cashier_id=u.id, supervisor_id=supervisor.id,
                                amount=round(d.amount, 2), expires_at=datetime.utcnow() + timedelta(minutes=5))
    db.add(approval)
    log(db, supervisor, "DESCUENTO_AUTORIZADO", f"Descuento de S/ {approval.amount:.2f} para {u.full_name}")
    db.commit()
    return {"authorization_id": token_id, "amount": approval.amount, "expires_in": 300}
