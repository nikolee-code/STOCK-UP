from fastapi import APIRouter
from common import *

router = APIRouter(prefix="/api")


# ======================================================================
#  REGISTRO DE PRODUCTOS (datos del producto y sus presentaciones)
# ======================================================================
class PresIn(BaseModel):
    id: Optional[int] = None
    name: str
    factor: float
    price: float
    barcode: str = ""


class ProductIn(BaseModel):
    code: str = ""
    barcode: str = ""
    name: str
    category: str = "General"
    unit: str = "und"
    cost: float = 0
    price: float
    min_stock: float = 5
    presentations: list[PresIn] = []


def barcode_taken(db, code, product_id=None, pres_id=None):
    q = db.query(Product).filter(Product.barcode == code)
    if product_id:
        q = q.filter(Product.id != product_id)
    if q.first():
        return True
    q = db.query(Presentation).filter(Presentation.barcode == code)
    if pres_id:
        q = q.filter(Presentation.id != pres_id)
    return q.first() is not None


def clean_product(d, db, pid=None):
    name = d.name.strip()
    if not name:
        raise HTTPException(400, "El nombre es obligatorio")
    if d.unit not in UNITS:
        raise HTTPException(400, "Unidad de medida no válida")
    if d.price < 0 or d.cost < 0 or d.min_stock < 0:
        raise HTTPException(400, "Los valores no pueden ser negativos")
    if d.unit not in DECIMAL_UNITS and d.min_stock != int(d.min_stock):
        raise HTTPException(400, "El stock mínimo debe ser un número entero para esta unidad")
    barcode = d.barcode.strip() or None
    if barcode and barcode_taken(db, barcode, product_id=pid):
        raise HTTPException(400, "Ese código de barras ya está registrado")
    names, codes = set(), {barcode} if barcode else set()
    for x in d.presentations:
        n = x.name.strip()
        if not n:
            raise HTTPException(400, "Cada presentación necesita un nombre")
        if n.lower() in names:
            raise HTTPException(400, f"La presentación «{n}» está repetida")
        names.add(n.lower())
        if x.factor <= 0 or x.price < 0:
            raise HTTPException(400, f"Revisa la cantidad y el precio de «{n}»")
        b = x.barcode.strip()
        if b:
            if b in codes or barcode_taken(db, b, pres_id=x.id):
                raise HTTPException(400, f"El código de barras de «{n}» ya está registrado")
            codes.add(b)
    return name, barcode


@router.get("/products")
def products(u=Depends(need("products.read")), db=Depends(get_db)):
    pm = pres_map(db)
    return [product_out(p, u, pm) for p in db.query(Product).filter(Product.active == True).order_by(Product.name)]


@router.post("/products")
def add_product(d: ProductIn, u=Depends(need("products.write")), db=Depends(get_db)):
    name, barcode = clean_product(d, db)
    code = d.code.strip()
    if not code:  # código interno automático
        n = (db.query(func.max(Product.id)).scalar() or 0) + 1
        code = f"P{n:03d}"
        while db.query(Product).filter(Product.code == code).first():
            n += 1
            code = f"P{n:03d}"
    elif db.query(Product).filter(Product.code == code).first():
        raise HTTPException(400, "Ya existe un producto con ese código interno")
    p = Product(code=code, barcode=barcode, name=name, category=d.category.strip() or "General",
                unit=d.unit, cost=d.cost if allowed(u, "costs.read") else 0, price=d.price,
                min_stock=r3(d.min_stock), stock=0)
    db.add(p)
    db.flush()
    for x in d.presentations:
        db.add(Presentation(product_id=p.id, name=x.name.strip(), factor=x.factor, price=x.price,
                            barcode=x.barcode.strip() or None))
    log(db, u, "PRODUCTO_CREADO", f"{code} - {name} ({d.unit}), {len(d.presentations)} presentación(es)")
    db.commit()
    return {"ok": True, "id": p.id}


@router.put("/products/{pid}")
def update_product(pid: int, d: ProductIn, u=Depends(need("products.write")), db=Depends(get_db)):
    p = db.get(Product, pid)
    if not p or not p.active:
        raise HTTPException(404, "Producto no encontrado")
    name, barcode = clean_product(d, db, pid)
    if d.unit != p.unit and p.stock != 0:
        raise HTTPException(400, "No se puede cambiar la unidad de un producto con stock. Deja el stock en 0 primero.")
    code = d.code.strip() or p.code
    if code != p.code and db.query(Product).filter(Product.code == code, Product.id != pid).first():
        raise HTTPException(400, "Ya existe un producto con ese código interno")
    if d.price != p.price:
        log(db, u, "PRECIO_CAMBIADO", f"{p.name}: S/ {p.price:.2f} -> S/ {d.price:.2f}")
    p.code, p.barcode, p.name = code, barcode, name
    p.category = d.category.strip() or "General"
    p.unit, p.price, p.min_stock = d.unit, d.price, r3(d.min_stock)
    if allowed(u, "costs.read"):
        p.cost = d.cost
    current = {x.id: x for x in db.query(Presentation).filter(
        Presentation.product_id == pid, Presentation.active == True)}
    keep = set()
    for x in d.presentations:
        if x.id and x.id in current:
            pr = current[x.id]
            pr.name, pr.factor, pr.price = x.name.strip(), x.factor, x.price
            pr.barcode = x.barcode.strip() or None
            keep.add(x.id)
        else:
            db.add(Presentation(product_id=pid, name=x.name.strip(), factor=x.factor, price=x.price,
                                barcode=x.barcode.strip() or None))
    for k, pr in current.items():
        if k not in keep:
            pr.active = False
            pr.barcode = None
    log(db, u, "PRODUCTO_EDITADO", f"{code} - {name}")
    db.commit()
    return {"ok": True}


@router.delete("/products/{pid}")
def archive_product(pid: int, u=Depends(need("products.write")), db=Depends(get_db)):
    p = db.get(Product, pid)
    if not p or not p.active:
        raise HTTPException(404, "Producto no encontrado")
    if p.stock != 0:
        raise HTTPException(400, "Primero deja el stock en 0 con un movimiento de inventario")
    p.active = False
    p.barcode = None
    for x in db.query(Presentation).filter(Presentation.product_id == pid):
        x.active = False
        x.barcode = None
    log(db, u, "PRODUCTO_ARCHIVADO", f"{p.code} - {p.name}")
    db.commit()
    return {"ok": True}


# ======================================================================
#  INVENTARIO (cantidades, entradas, salidas y su motivo)
# ======================================================================
class MoveIn(BaseModel):
    product_id: int
    motive: str
    qty: float
    presentation_id: Optional[int] = None
    note: str = ""


def motive_label(m):
    if m.motive in MOTIVES:
        return MOTIVES[m.motive][0]
    return {"venta": "Venta", "anulacion": "Anulación de venta"}.get(m.kind, m.kind or "")


@router.post("/inventory/move")
def move(d: MoveIn, u=Depends(need("stock.adjust")), db=Depends(get_db)):
    p = db.get(Product, d.product_id)
    if not p or not p.active:
        raise HTTPException(404, "Producto no encontrado")
    if d.motive not in MOTIVES:
        raise HTTPException(400, "Elige el motivo del movimiento")
    label, direction = MOTIVES[d.motive]
    if d.qty <= 0:
        raise HTTPException(400, "La cantidad debe ser mayor que 0")
    factor = 1.0
    if d.presentation_id:
        pr = db.get(Presentation, d.presentation_id)
        if not pr or pr.product_id != p.id or not pr.active:
            raise HTTPException(400, "Presentación no válida")
        if d.qty != int(d.qty):
            raise HTTPException(400, "Las presentaciones se cuentan en cantidades enteras")
        factor = pr.factor
    elif p.unit not in DECIMAL_UNITS and d.qty != int(d.qty):
        raise HTTPException(400, f"{p.name} solo admite cantidades enteras")
    note = d.note.strip()[:200]
    if d.motive in ("otro_ingreso", "otra_salida") and not note:
        raise HTTPException(400, "Explica el motivo en la nota")
    units = r3(d.qty * factor)
    delta = units if direction == "in" else -units
    new = r3(p.stock + delta)
    if new < 0:
        raise HTTPException(400, f"No hay stock suficiente (disponible: {p.stock} {p.unit})")
    db.add(StockMovement(product_id=p.id, kind="entrada" if direction == "in" else "salida",
                         motive=d.motive, note=note, qty=delta, prev_stock=p.stock, new_stock=new,
                         reason=label + (f" — {note}" if note else ""), user_id=u.id))
    log(db, u, "INVENTARIO", f"{p.name}: {p.stock} -> {new} {p.unit} ({label})")
    p.stock = new
    db.commit()
    return {"ok": True, "stock": new}


@router.get("/inventory/movements")
def movements(product_id: Optional[int] = None, date_from: Optional[str] = None, date_to: Optional[str] = None,
              limit: int = 200, u=Depends(need_any("stock.read", "stock.adjust")), db=Depends(get_db)):
    q = db.query(StockMovement, Product, User) \
        .join(Product, Product.id == StockMovement.product_id) \
        .outerjoin(User, User.id == StockMovement.user_id)
    if product_id:
        q = q.filter(StockMovement.product_id == product_id)
    if date_from or date_to:
        a, b = day_range(date_from, date_to)
        q = q.filter(StockMovement.created_at >= a, StockMovement.created_at < b)
    rows = q.order_by(StockMovement.id.desc()).limit(min(limit, 500)).all()
    return [{"id": m.id, "date": iso(m.created_at), "product": p.name, "unit": p.unit, "kind": m.kind,
             "motive": motive_label(m), "qty": m.qty, "prev": m.prev_stock, "new": m.new_stock,
             "note": m.note or "", "user": usr.full_name if usr else "—"} for m, p, usr in rows]


# ======================================================================
#  PROMOCIONES Y DESCUENTOS (las define el administrador)
# ======================================================================
class PromoIn(BaseModel):
    name: str
    kind: str                      # percent (%) o amount (S/)
    value: float
    scope: str = "sale"            # sale (toda la venta) o product
    product_id: Optional[int] = None
    min_total: float = 0
    starts: str = ""
    ends: str = ""
    active: bool = True


def promo_active_now(x):
    t = today_str()
    return bool(x.active) and (not x.starts or x.starts <= t) and (not x.ends or x.ends >= t)


def check_promo(d, db):
    if not d.name.strip():
        raise HTTPException(400, "La promoción necesita un nombre")
    if d.kind not in ("percent", "amount"):
        raise HTTPException(400, "Tipo de descuento no válido")
    if d.value <= 0 or (d.kind == "percent" and d.value > 100):
        raise HTTPException(400, "El valor del descuento no es válido")
    if d.scope not in ("sale", "product"):
        raise HTTPException(400, "Alcance no válido")
    if d.scope == "product":
        if d.kind != "percent":
            raise HTTPException(400, "Las promociones por producto solo pueden ser en porcentaje")
        if not d.product_id or not db.get(Product, d.product_id):
            raise HTTPException(400, "Elige el producto de la promoción")
    if d.min_total < 0:
        raise HTTPException(400, "La compra mínima no puede ser negativa")
    for s in (d.starts, d.ends):
        if s:
            day_start_utc(s)
    if d.starts and d.ends and d.ends < d.starts:
        raise HTTPException(400, "La fecha final no puede ser anterior a la inicial")


def promo_out(x, pname=None):
    return {"id": x.id, "name": x.name, "kind": x.kind, "value": x.value, "scope": x.scope,
            "product_id": x.product_id, "product": pname or "", "min_total": x.min_total or 0,
            "starts": x.starts or "", "ends": x.ends or "", "active": bool(x.active),
            "valid_now": promo_active_now(x)}


@router.get("/promotions")
def promotions(u=Depends(need("promo.manage")), db=Depends(get_db)):
    names = {p.id: p.name for p in db.query(Product)}
    return [promo_out(x, names.get(x.product_id)) for x in db.query(Promotion).order_by(Promotion.id.desc())]


@router.get("/promotions/active")
def promotions_active(u=Depends(need("sales.create")), db=Depends(get_db)):
    names = {p.id: p.name for p in db.query(Product)}
    return [promo_out(x, names.get(x.product_id)) for x in db.query(Promotion).order_by(Promotion.name)
            if promo_active_now(x)]


@router.post("/promotions")
def add_promotion(d: PromoIn, u=Depends(need("promo.manage")), db=Depends(get_db)):
    check_promo(d, db)
    db.add(Promotion(name=d.name.strip(), kind=d.kind, value=d.value, scope=d.scope,
                     product_id=d.product_id if d.scope == "product" else None, min_total=d.min_total,
                     starts=d.starts or None, ends=d.ends or None, active=d.active))
    log(db, u, "PROMOCION_CREADA", d.name.strip())
    db.commit()
    return {"ok": True}


@router.put("/promotions/{xid}")
def edit_promotion(xid: int, d: PromoIn, u=Depends(need("promo.manage")), db=Depends(get_db)):
    x = db.get(Promotion, xid)
    if not x:
        raise HTTPException(404, "Promoción no encontrada")
    check_promo(d, db)
    x.name, x.kind, x.value, x.scope = d.name.strip(), d.kind, d.value, d.scope
    x.product_id = d.product_id if d.scope == "product" else None
    x.min_total, x.starts, x.ends, x.active = d.min_total, d.starts or None, d.ends or None, d.active
    log(db, u, "PROMOCION_EDITADA", d.name.strip())
    db.commit()
    return {"ok": True}