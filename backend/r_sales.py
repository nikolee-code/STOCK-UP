from fastapi import APIRouter
from uuid import uuid4
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from common import *

router = APIRouter(prefix="/api")


# ======================================================================
#  VENTAS
# ======================================================================
class ItemIn(BaseModel):
    product_id: int
    qty: float
    presentation_id: Optional[int] = None


class SaleIn(BaseModel):
    items: list[ItemIn]
    payment_method: str = "efectivo"
    payment_ref: str = ""
    doc_type: str = "boleta"
    customer_doc: str = ""
    customer_name: str = ""
    customer_address: str = ""
    idempotency_key: str = ""


def reserve_sale_request(d, u, db):
    key=(d.idempotency_key or "").strip() or uuid4().hex
    if len(key)<16 or len(key)>64 or not all(ch.isalnum() or ch in "-_" for ch in key):
        raise HTTPException(400, "Clave de reintento no válida")
    d.idempotency_key=key
    dialect=db.bind.dialect.name
    values={"request_id":key,"user_id":u.id,"sale_id":None}
    if dialect=="postgresql":
        db.execute(pg_insert(SaleRequest).values(**values).on_conflict_do_nothing(index_elements=[SaleRequest.request_id]))
    elif dialect=="sqlite":
        db.execute(sqlite_insert(SaleRequest).values(**values).on_conflict_do_nothing(index_elements=[SaleRequest.request_id]))
    request=db.query(SaleRequest).filter_by(request_id=key).with_for_update().first()
    if request is None:
        request=SaleRequest(**values);db.add(request);db.flush()
    if request.user_id!=u.id:
        raise HTTPException(409, "La clave de venta ya pertenece a otra sesión")
    if request.sale_id:
        sale=db.get(Sale,request.sale_id)
        if not sale:raise HTTPException(409, "No se pudo recuperar la venta asociada al reintento")
        items=db.query(SaleItem).filter(SaleItem.sale_id==sale.id).order_by(SaleItem.id).all()
        cashier=db.get(User,sale.user_id)
        log(db,u,"VENTA_REINTENTO",f"Se devolvió el comprobante existente {doc_label(sale)}")
        db.commit()
        return request,receipt_out(sale,items,cashier.full_name if cashier else "")
    return request,None


def next_doc_number(db, series):
    """Reserva un correlativo transaccional; SELECT FOR UPDATE serializa cajeros concurrentes."""
    last = db.query(func.max(Sale.doc_number)).filter(Sale.doc_series == series).scalar() or 0
    first_number = int(last) + 1
    dialect = db.bind.dialect.name
    if dialect == "postgresql":
        stmt = pg_insert(DocumentCounter).values(series=series, next_number=first_number).on_conflict_do_nothing(index_elements=[DocumentCounter.series])
        db.execute(stmt)
    elif dialect == "sqlite":
        stmt = sqlite_insert(DocumentCounter).values(series=series, next_number=first_number).on_conflict_do_nothing(index_elements=[DocumentCounter.series])
        db.execute(stmt)
    counter = db.query(DocumentCounter).filter_by(series=series).with_for_update().first()
    if counter is None:
        counter = DocumentCounter(series=series, next_number=first_number)
        db.add(counter)
        db.flush()
    number = max(int(counter.next_number or 1), first_number)
    counter.next_number = number + 1
    return number


def check_customer(d, total):
    """Valida los datos del cliente según el comprobante."""
    doc = d.customer_doc.strip()
    name = d.customer_name.strip()
    addr = d.customer_address.strip()
    if d.doc_type == "nota_interna" and total > 5:
        raise HTTPException(400, "Para ventas mayores a S/ 5.00 debes emitir boleta o factura; la nota interna no es un comprobante de pago.")
    if d.doc_type == "factura":
        if not (doc.isdigit() and len(doc) == 11 and doc[:2] in ("10", "15", "16", "17", "20")):
            raise HTTPException(400, "Para factura se requiere un RUC válido de 11 dígitos (empieza con 10, 15, 16, 17 o 20)")
        if len(name) < 3:
            raise HTTPException(400, "Para factura se requiere la razón social del cliente")
        return "RUC", doc, name, addr
    if d.doc_type == "boleta":
        if doc and not (doc.isdigit() and len(doc) == 8):
            raise HTTPException(400, "El DNI debe tener 8 dígitos")
        if total > BOLETA_LIMIT and not (doc and name):
            raise HTTPException(400, f"Para boletas mayores a S/ {BOLETA_LIMIT:.0f} se requieren el DNI y el nombre del cliente")
        return ("DNI" if doc else ""), doc, name, addr
    return "", "", name, ""


@router.post("/sales")
def create_sale(d: SaleIn, u=Depends(need("sales.create")), db=Depends(get_db)):
    if u.role != "cajero":
        raise HTTPException(403, "El registro de ventas está habilitado solo para el rol Cajero")
    sale_request, prior_receipt = reserve_sale_request(d,u,db)
    if prior_receipt is not None:
        return prior_receipt
    if not d.items:
        raise HTTPException(400, "La venta no tiene productos")
    if d.payment_method not in PAYMENTS:
        raise HTTPException(400, "Forma de pago no válida")
    if d.doc_type not in SERIES:
        raise HTTPException(400, "Tipo de comprobante no válido")
    if d.doc_type in ("boleta", "factura") and not CPE_ENABLED:
        raise HTTPException(503, "La emisión electrónica aún no está conectada con SUNAT. No se registró la venta; configura el sistema de emisión y vuelve a intentarlo.")
    cs = db.query(CashSession).filter_by(user_id=u.id, status="abierta").first()
    if not cs:
        raise HTTPException(400, "Debes abrir tu caja antes de vender")

    # Bloquea todos los productos en orden estable para que varios cajeros no vendan el mismo stock.
    product_ids = sorted({it.product_id for it in d.items})
    product_query = db.query(Product).filter(Product.id.in_(product_ids)).order_by(Product.id)
    if db.bind.dialect.name in ("postgresql", "mysql"):
        product_query = product_query.with_for_update()
    locked_products = {p.id: p for p in product_query.all()}

    lines, need_units, subtotal = [], {}, 0.0
    for it in d.items:
        p = locked_products.get(it.product_id)
        if not p or not p.active or it.qty <= 0:
            raise HTTPException(400, "Producto o cantidad no válidos")
        pr = None
        factor, price, label = 1.0, p.price, p.name
        if it.presentation_id:
            pr = db.get(Presentation, it.presentation_id)
            if not pr or pr.product_id != p.id or not pr.active:
                raise HTTPException(400, "Presentación no válida")
            if it.qty != int(it.qty):
                raise HTTPException(400, f"{p.name} ({pr.name}) solo se vende en cantidades enteras")
            factor, price, label = pr.factor, pr.price, f"{p.name} ({pr.name})"
        elif p.unit not in DECIMAL_UNITS and it.qty != int(it.qty):
            raise HTTPException(400, f"{p.name} solo se vende en cantidades enteras")
        units = r3(it.qty * factor)
        need_units[p.id] = r3(need_units.get(p.id, 0) + units)
        if p.stock < need_units[p.id]:
            raise HTTPException(400, f"Stock insuficiente de {p.name} (disponible: {p.stock} {p.unit})")
        line_total = round(price * it.qty, 2)
        subtotal += line_total
        lines.append((p, pr, it.qty, price, factor, units, label, line_total))
    subtotal = round(subtotal, 2)

    discount = 0.0
    total = subtotal

    cust_type, cust_doc, cust_name, cust_addr = check_customer(d, total)

    series = SERIES[d.doc_type]
    doc_number = next_doc_number(db, series)
    sale = Sale(user_id=u.id, cash_session_id=cs.id, payment_method=d.payment_method,
                payment_ref=d.payment_ref.strip()[:60], doc_type=d.doc_type,
                doc_series=series, doc_number=doc_number, subtotal=subtotal, discount=discount,
                promo_id=None, promo_name=None,
                total=total, customer_doc_type=cust_type, customer_doc=cust_doc,
                customer_name=cust_name, customer_address=cust_addr)
    db.add(sale)
    db.flush()
    sale_request.sale_id=sale.id
    number = f"{series}-{sale.doc_number:08d}"
    sale_items = []
    for p, pr, qty, price, factor, units, label, line_total in lines:
        prev = p.stock
        p.stock = r3(p.stock - units)
        si = SaleItem(sale_id=sale.id, product_id=p.id, presentation_id=pr.id if pr else None,
                      description=label, qty=qty, price=price, unit_factor=factor,
                      cost=round((p.cost or 0) * units, 2))
        db.add(si)
        sale_items.append(si)
        db.add(StockMovement(product_id=p.id, kind="venta", qty=-units, prev_stock=prev,
                             new_stock=p.stock, reason=f"Venta {number}", user_id=u.id))
    log(db, u, "VENTA", f"{number} por S/ {total:.2f} ({PAYMENTS[d.payment_method]})")
    db.commit()  # todo o nada: si algo falla, no se guarda nada
    return receipt_out(sale, sale_items, u.full_name)


@router.get("/sales")
def list_sales(date_from: Optional[str] = None, date_to: Optional[str] = None,
               user_id: Optional[int] = None, status: Optional[str] = None, doc_type: Optional[str] = None,
               u=Depends(need_any("sales.read", "sales.own")), db=Depends(get_db)):
    a, b = day_range(date_from, date_to)
    conds = [Sale.created_at >= a, Sale.created_at < b]
    see_all = allowed(u, "sales.read")
    if not see_all:
        conds.append(Sale.user_id == u.id)
    elif user_id:
        conds.append(Sale.user_id == user_id)

    q = db.query(Sale, User).join(User, User.id == Sale.user_id).filter(*conds)
    if status in ("completada", "anulada"):
        q = q.filter(Sale.status == status)
    if doc_type in SERIES:
        q = q.filter(Sale.doc_type == doc_type)
    rows = q.order_by(Sale.id.desc()).limit(500).all()

    done = [Sale.status == "completada"] + conds
    count, total, discount = db.query(func.count(Sale.id), func.coalesce(func.sum(Sale.total), 0),
                                      func.coalesce(func.sum(Sale.discount), 0)).filter(*done).one()
    methods = db.query(Sale.payment_method, func.sum(Sale.total), func.count(Sale.id)) \
        .filter(*done).group_by(Sale.payment_method).all()
    totals = {
        "count": count, "total": round(total, 2), "discount": round(discount, 2),
        "voided": db.query(func.count(Sale.id)).filter(Sale.status == "anulada", *conds).scalar(),
        "methods": [{"method": m, "label": PAYMENTS.get(m, m), "total": round(t or 0, 2), "count": c}
                    for m, t, c in methods],
    }
    if see_all:
        by_user = db.query(User.full_name, func.sum(Sale.total), func.count(Sale.id)) \
            .select_from(Sale).join(User, User.id == Sale.user_id).filter(*done) \
            .group_by(User.full_name).order_by(func.sum(Sale.total).desc()).all()
        totals["by_user"] = [{"name": n, "total": round(t or 0, 2), "count": c} for n, t, c in by_user]
    if allowed(u, "profit.read"):
        cost = db.query(func.coalesce(func.sum(SaleItem.cost), 0)).select_from(SaleItem) \
            .join(Sale, Sale.id == SaleItem.sale_id).filter(*done).scalar()
        totals["cost"] = round(cost, 2)
        totals["gross_profit"] = round(total - cost, 2)
    return {
        "rows": [{"id": s.id, "number": doc_label(s), "date": iso(s.created_at), "cashier": usr.full_name,
                  "customer": s.customer_name or s.customer_doc or "—",
                  "payment": PAYMENTS.get(s.payment_method, s.payment_method),
                  "total": round(s.total or 0, 2), "discount": round(s.discount or 0, 2),
                  "status": s.status, "void_reason": s.void_reason or "", "doc_type": s.doc_type,
                  "can_void": is_admin(u) and s.status == "completada"} for s, usr in rows],
        "totals": totals,
    }


@router.get("/sales/{sid}")
def get_sale(sid: int, u=Depends(need_any("sales.read", "sales.own")), db=Depends(get_db)):
    s = db.get(Sale, sid)
    if not s:
        raise HTTPException(404, "Venta no encontrada")
    if not allowed(u, "sales.read") and s.user_id != u.id:
        raise HTTPException(403, "No tienes permiso para ver esta venta")
    items = db.query(SaleItem).filter(SaleItem.sale_id == s.id).order_by(SaleItem.id).all()
    cashier = db.get(User, s.user_id)
    return receipt_out(s, items, cashier.full_name if cashier else "")


class VoidIn(BaseModel):
    reason: str


@router.post("/sales/{sid}/void")
def void_sale(sid: int, d: VoidIn, u=Depends(need("sales.void")), db=Depends(get_db)):
    """Solo el administrador anula ventas. La venta no se borra: queda marcada y el stock se devuelve."""
    s = db.get(Sale, sid)
    if not s:
        raise HTTPException(404, "Venta no encontrada")
    if s.status != "completada":
        raise HTTPException(400, "Esta venta ya está anulada")
    reason = d.reason.strip()
    if len(reason) < 3:
        raise HTTPException(400, "Escribe el motivo de la anulación")
    number = doc_label(s)
    for it in db.query(SaleItem).filter(SaleItem.sale_id == s.id):
        p = db.get(Product, it.product_id)
        if not p:
            continue
        units = r3((it.qty or 0) * (it.unit_factor or 1))
        prev = p.stock
        p.stock = r3(p.stock + units)
        db.add(StockMovement(product_id=p.id, kind="anulacion", qty=units, prev_stock=prev,
                             new_stock=p.stock, reason=f"Anulación {number}: {reason}", user_id=u.id))
    s.status = "anulada"
    s.voided_at = datetime.utcnow()
    s.voided_by = u.id
    s.void_reason = reason[:200]
    log(db, u, "VENTA_ANULADA", f"{number} por S/ {s.total:.2f}: {reason}")
    db.commit()
    return {"ok": True}


# ======================================================================
#  EGRESOS (pagos y salidas de dinero)
# ======================================================================
class ExpenseIn(BaseModel):
    concept: str
    category: str = "Otros"
    amount: float
    from_cash: bool = True


@router.post("/expenses")
def add_expense(d: ExpenseIn, u=Depends(need("expenses.create")), db=Depends(get_db)):
    concept = d.concept.strip()
    if len(concept) < 3:
        raise HTTPException(400, "Escribe el concepto del egreso")
    if d.amount <= 0:
        raise HTTPException(400, "El monto debe ser mayor que 0")
    cat = d.category if d.category in EXPENSE_CATS else "Otros"
    from_cash = True if not is_admin(u) else d.from_cash  # el cajero solo registra salidas de su caja
    cs_id = None
    if from_cash:
        cs = db.query(CashSession).filter_by(user_id=u.id, status="abierta").first()
        if not cs:
            raise HTTPException(400, "Abre tu caja para registrar una salida de efectivo")
        cs_id = cs.id
    db.add(Expense(user_id=u.id, cash_session_id=cs_id, concept=concept, category=cat,
                   amount=round(d.amount, 2), from_cash=from_cash))
    log(db, u, "EGRESO", f"S/ {d.amount:.2f} - {cat}: {concept}" + (" (de la caja)" if from_cash else ""))
    db.commit()
    return {"ok": True}


@router.get("/expenses")
def list_expenses(date_from: Optional[str] = None, date_to: Optional[str] = None,
                  user_id: Optional[int] = None,
                  u=Depends(need_any("expenses.read", "expenses.create")), db=Depends(get_db)):
    a, b = day_range(date_from, date_to)
    conds = [Expense.created_at >= a, Expense.created_at < b]
    if not allowed(u, "expenses.read"):
        conds.append(Expense.user_id == u.id)
    elif user_id:
        conds.append(Expense.user_id == user_id)
    rows = db.query(Expense, User).join(User, User.id == Expense.user_id).filter(*conds) \
        .order_by(Expense.id.desc()).limit(500).all()
    total = db.query(func.coalesce(func.sum(Expense.amount), 0)).filter(Expense.status == "activo", *conds).scalar()
    return {
        "rows": [{"id": e.id, "date": iso(e.created_at), "user": usr.full_name, "concept": e.concept,
                  "category": e.category, "amount": round(e.amount, 2), "from_cash": bool(e.from_cash),
                  "status": e.status, "can_void": is_admin(u) and e.status == "activo"} for e, usr in rows],
        "total": round(total, 2),
    }


@router.post("/expenses/{eid}/void")
def void_expense(eid: int, u=Depends(need("expenses.void")), db=Depends(get_db)):
    e = db.get(Expense, eid)
    if not e:
        raise HTTPException(404, "Egreso no encontrado")
    if e.status != "activo":
        raise HTTPException(400, "Este egreso ya está anulado")
    e.status = "anulado"
    log(db, u, "EGRESO_ANULADO", f"S/ {e.amount:.2f}: {e.concept}")
    db.commit()
    return {"ok": True}
