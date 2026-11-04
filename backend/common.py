import os, json, urllib.request, urllib.error
import jwt
from datetime import datetime, timedelta
from typing import Optional
from fastapi import Depends, HTTPException, Header
from pydantic import BaseModel
from sqlalchemy import func
from db import *

SECRET = os.getenv("STOCKUP_SECRET", "cambia-esta-clave-en-produccion")
PERU_API_TOKEN = os.getenv("PERU_API_TOKEN", "")            # token del servicio de consulta DNI/RUC
PERU_API_PROVIDER = os.getenv("PERU_API_PROVIDER", "apisperu").lower()

# ---------- RBAC: permisos por rol ----------
PERMS = {
    "admin": ["*"],
    "almacen": ["dashboard", "products.read", "products.write", "costs.read", "stock.read", "stock.adjust"],
    "cajero": ["dashboard", "products.read", "sales.create", "sales.own", "cash.own", "expenses.create", "notifications.read"],
    "supervisor": ["dashboard", "products.read", "sales.read", "cash.review", "audit.read",
                   "profit.read", "expenses.read", "expenses.manage", "stock.read", "finance.read",
                   "purchases.manage", "purchases.read", "notifications.read", "discount.approve"],
    "contador": ["dashboard", "products.read", "sales.read", "costs.read", "profit.read", "expenses.read"],
}

ROLE_LABELS = {
    "admin": "Administrador",
    "almacen": "Almacén",
    "cajero": "Cajero",
    "supervisor": "Supervisor",
    "contador": "Contador",
}

# ---------- Catálogos ----------
UNITS = ["und", "kg", "g", "lt", "m", "paquete", "caja", "bolsa", "botella", "docena"]
DECIMAL_UNITS = {"kg", "g", "lt", "m"}  # admiten decimales (1.5 kg)
PAYMENTS = {
    "efectivo": "Efectivo",
    "yape": "Yape",
    "plin": "Plin",
    "tarjeta": "Tarjeta",
    "transferencia": "Transferencia bancaria",
    "billetera": "Otra billetera digital",
}
SERIES = {
    "boleta": "BI01",                 # serie interna simulada, no tributaria
    "factura": "FI01",                # serie interna simulada, no tributaria
    "nota_interna": "INT",            # serie interna para notas de venta nuevas
    "comprobante_interno": "INT",
}
ESTABLISHMENT_NAME = os.getenv("STOCKUP_ESTABLISHMENT_NAME", "Stock Up").strip() or "Stock Up"
ESTABLISHMENT_RUC = os.getenv("STOCKUP_ESTABLISHMENT_RUC", "").strip()
ESTABLISHMENT_ADDRESS = os.getenv("STOCKUP_ESTABLISHMENT_ADDRESS", "").strip()
DOC_NAMES = {
    "boleta": "Boleta de venta electrónica",
    "factura": "Factura electrónica",
    "nota_interna": "Nota de venta",
    "comprobante_interno": "Comprobante interno de venta",
}
BOLETA_LIMIT = 700.0   # Umbral del proyecto para solicitar identificación en una boleta.
CPE_ENABLED = False    # Metadato de compatibilidad; no controla el registro de ventas simuladas.
IGV = 1.18             # se asume que los precios ya incluyen IGV (18%)
EXPENSE_CATS = ["Proveedores", "Servicios", "Sueldos", "Transporte", "Mantenimiento", "Otros"]

# Motivos de inventario: código -> (texto, dirección). "in" suma stock, "out" lo descuenta.
MOTIVES = {
    "compra": ("Ingreso de productos (compra)", "in"),
    "devolucion_cliente": ("Devolución de cliente", "in"),
    "sobrante": ("Corrección de conteo: sobrante", "in"),
    "otro_ingreso": ("Otro ingreso (explica en la nota)", "in"),
    "vencido": ("Producto vencido", "out"),
    "danado": ("Producto dañado", "out"),
    "faltante": ("Corrección de conteo: faltante", "out"),
    "consumo": ("Consumo interno", "out"),
    "otra_salida": ("Otra salida (explica en la nota)", "out"),
}


def r3(x):
    return round(float(x), 3)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def current_user(authorization: str = Header(None), db=Depends(get_db)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "No autenticado")
    try:
        data = jwt.decode(authorization[7:], SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "Sesión inválida o vencida")
    u = db.get(User, data["uid"])
    if not u or not u.active:
        raise HTTPException(401, "Usuario no válido")
    return u


def get_additional_roles(u):
    """Códigos válidos de los roles adicionales, sin duplicar el rol principal."""
    if getattr(u, "role", None) == "admin":
        return []
    links = getattr(u, "additional_role_links", ()) or ()
    codes = {
        str(link.role_code).strip().lower()
        for link in links
        if getattr(link, "role_code", None)
    }
    return sorted(code for code in codes if code in PERMS and code not in (u.role, "admin"))


def get_effective_roles(u):
    """Rol principal más los roles adicionales válidos de la cuenta."""
    primary = getattr(u, "role", None)
    if primary == "admin":
        return ["admin"]
    return ([primary] if primary in PERMS else []) + get_additional_roles(u)


def get_effective_permissions(u):
    """Unión sin duplicados de los permisos de todos los roles efectivos."""
    if getattr(u, "role", None) == "admin":
        return ["*"]
    permissions = set()
    for role_code in get_effective_roles(u):
        permissions.update(PERMS.get(role_code, ()))
    return sorted(permissions)


def has_role(u, role_code):
    return role_code in get_effective_roles(u)


def allowed(u, p):
    ps = get_effective_permissions(u)
    return "*" in ps or p in ps


def need(p):
    def dep(u=Depends(current_user)):
        if not allowed(u, p):
            raise HTTPException(403, "No tienes permiso para esta acción")
        return u
    return dep


def need_any(*perms):
    def dep(u=Depends(current_user)):
        if not any(allowed(u, p) for p in perms):
            raise HTTPException(403, "No tienes permiso para esta acción")
        return u
    return dep


def is_admin(u):
    return u.role == "admin"


def log(db, u, action, detail=""):
    db.add(AuditLog(user_id=u.id if u else None, action=action, detail=detail))


def user_out(u):
    return {"id": u.id, "username": u.username, "full_name": u.full_name,
            "role": u.role, "additional_roles": get_additional_roles(u),
            "perms": get_effective_permissions(u)}


# ---------- Fechas (hora de Lima, UTC-5) ----------
def lima_now():
    return datetime.utcnow() - timedelta(hours=5)


def today_str():
    return lima_now().strftime("%Y-%m-%d")


def iso(dt):
    return (dt - timedelta(hours=5)).strftime("%d/%m/%Y %H:%M") if dt else ""


def day_start_utc(s):
    try:
        d = datetime.strptime(s, "%Y-%m-%d")
    except (ValueError, TypeError):
        raise HTTPException(400, "Fecha no válida (usa AAAA-MM-DD)")
    return d + timedelta(hours=5)


def day_range(date_from, date_to):
    """Devuelve (inicio, fin) en UTC. Sin fechas = hoy. Solo 'desde' = ese día."""
    start = date_from or today_str()
    end = date_to or date_from or today_str()
    if start > end:
        raise HTTPException(400, "La fecha inicial no puede ser posterior a la fecha final")
    a = day_start_utc(start)
    b = day_start_utc(end) + timedelta(days=1)
    return a, b


# ---------- Utilidades de datos ----------
def doc_label(s):
    return f"{s.doc_series}-{s.doc_number:08d}" if s.doc_series else f"#{s.id}"


def get_setting(db, key, default=""):
    s = db.get(Setting, key)
    return s.value if s else default


def pres_map(db):
    m = {}
    for x in db.query(Presentation).filter(Presentation.active == True).order_by(Presentation.factor):
        m.setdefault(x.product_id, []).append(
            {"id": x.id, "name": x.name, "factor": x.factor, "price": x.price, "barcode": x.barcode})
    return m


def product_out(p, u, pm):
    d = {"id": p.id, "code": p.code, "barcode": p.barcode, "name": p.name, "category": p.category,
         "unit": p.unit, "decimal": p.unit in DECIMAL_UNITS, "price": p.price,
         "stock": p.stock, "min_stock": p.min_stock,
         "presentations": [{**x, "available": int(p.stock // x["factor"])} for x in pm.get(p.id, [])]}
    if allowed(u, "costs.read"):
        d["cost"] = p.cost  # los costos solo los ve quien tiene permiso
    return d


def by_method(db, session_id):
    rows = db.query(Sale.payment_method, func.sum(Sale.total), func.count(Sale.id)) \
        .filter(Sale.cash_session_id == session_id, Sale.status == "completada") \
        .group_by(Sale.payment_method).all()
    return [{"method": m, "label": PAYMENTS.get(m, m), "total": round(t or 0, 2), "count": c} for m, t, c in rows]


def cash_income_total(db, session_id):
    t = db.query(func.sum(CashIncome.amount)).filter(CashIncome.cash_session_id == session_id).scalar()
    return round(t or 0, 2)


def cash_expenses_total(db, session_id):
    t = db.query(func.sum(Expense.amount)).filter(
        Expense.cash_session_id == session_id, Expense.from_cash == True, Expense.status == "activo").scalar()
    return round(t or 0, 2)


def receipt_out(sale, items, cashier):
    total = round(sale.total or 0, 2)
    if sale.doc_type == "nota_interna":
        base, igv = total, 0.0
    else:
        base = round(total / IGV, 2)
        igv = round(total - base, 2)
    return {
        "id": sale.id, "status": sale.status, "void_reason": sale.void_reason or "",
        "doc_type": sale.doc_type, "doc_name": DOC_NAMES.get(sale.doc_type, sale.doc_type),
        "number": doc_label(sale), "date": iso(sale.created_at or datetime.utcnow()), "cashier": cashier,
        "series": sale.doc_series or "", "correlative": sale.doc_number or 0,
        "establishment": {"name": ESTABLISHMENT_NAME, "ruc": ESTABLISHMENT_RUC,
                          "address": ESTABLISHMENT_ADDRESS},
        "taxes_are_reference": sale.doc_type in ("boleta", "factura", "comprobante_interno"),
        "customer_doc_type": sale.customer_doc_type or "", "customer_doc": sale.customer_doc or "",
        "customer_name": sale.customer_name or "", "customer_address": sale.customer_address or "",
        "payment": PAYMENTS.get(sale.payment_method, sale.payment_method), "payment_ref": sale.payment_ref or "",
        "items": [{"description": i.description, "qty": i.qty, "price": i.price,
                   "subtotal": round(i.price * i.qty, 2)} for i in items],
        "subtotal": round(sale.subtotal or (total + (sale.discount or 0)), 2),
        "discount": round(sale.discount or 0, 2), "promo_name": sale.promo_name or "",
        "base": base, "igv": igv, "total": total,
    }


# ---------- Consulta externa de DNI / RUC ----------
def http_json(url, body=None):
    headers = {"Accept": "application/json", "Authorization": f"Bearer {PERU_API_TOKEN}",
               "Content-Type": "application/json"}
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            result = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code in (404, 422):
            raise HTTPException(404, "No se encontró ese documento")
        if e.code in (401, 403):
            raise HTTPException(503, "La credencial de APISPERU no es válida o no tiene acceso a consultas")
        if e.code == 429:
            raise HTTPException(503, "APISPERU alcanzó el límite de consultas; inténtalo más tarde")
        raise HTTPException(502, "El servicio de consulta no respondió bien")
    except urllib.error.URLError as e:
        if isinstance(e.reason, TimeoutError):
            raise HTTPException(504, "APISPERU tardó demasiado en responder")
        raise HTTPException(502, "No se pudo conectar con el servicio de consulta")
    except TimeoutError:
        raise HTTPException(504, "APISPERU tardó demasiado en responder")
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(502, "APISPERU devolvió una respuesta inesperada")
    except Exception:
        raise HTTPException(502, "No se pudo conectar con el servicio de consulta")
    if not isinstance(result, dict):
        raise HTTPException(502, "APISPERU devolvió una respuesta inesperada")
    return result
