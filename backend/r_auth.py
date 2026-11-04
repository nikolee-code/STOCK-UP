from fastapi import APIRouter
from sqlalchemy.exc import IntegrityError
from common import *

router = APIRouter(prefix="/api")


# ---------- Datos generales ----------
@router.get("/meta")
def meta(db=Depends(get_db)):
    return {
        "units": UNITS,
        "decimal_units": sorted(DECIMAL_UNITS),
        "payments": PAYMENTS,
        "boleta_limit": BOLETA_LIMIT,
        "electronic_invoicing_enabled": CPE_ENABLED,
        "expense_cats": EXPENSE_CATS,
        "motives": [{"code": k, "label": v[0], "dir": v[1]} for k, v in MOTIVES.items()],
        "blind_close": get_setting(db, "blind_close", "1") == "1",
        "lookup_enabled": bool(PERU_API_TOKEN),
        "lookup_provider": PERU_API_PROVIDER,
    }


# ---------- Autenticación ----------
class LoginIn(BaseModel):
    username: str
    password: str


@router.post("/login")
def login(d: LoginIn, db=Depends(get_db)):
    u = db.query(User).filter(User.username == d.username.strip().lower()).first()
    if not u or not u.active or not verify_password(d.password, u.password_hash):
        log(db, None, "LOGIN_FALLIDO", d.username)
        db.commit()
        raise HTTPException(401, "Usuario o contraseña incorrectos")
    token = jwt.encode({"uid": u.id, "exp": datetime.utcnow() + timedelta(hours=8)}, SECRET, algorithm="HS256")
    log(db, u, "LOGIN", "Inicio de sesión")
    db.commit()
    return {"token": token, "user": user_out(u)}


@router.get("/me")
def me(u=Depends(current_user)):
    return user_out(u)


# ---------- Contraseñas (solo administrador) ----------
class PwdIn(BaseModel):
    current_password: str
    new_password: str


@router.post("/me/password")
def change_password(d: PwdIn, u=Depends(current_user), db=Depends(get_db)):
    if not verify_password(d.current_password, u.password_hash):
        raise HTTPException(400, "La contraseña actual no es correcta")
    if len(d.new_password) < 8:
        raise HTTPException(400, "La nueva contraseña debe tener al menos 8 caracteres")
    if d.new_password == d.current_password:
        raise HTTPException(400, "La nueva contraseña debe ser distinta a la actual")
    u.password_hash = hash_password(d.new_password)
    log(db, u, "CLAVE_CAMBIADA", "El usuario cambió su contraseña")
    db.commit()
    return {"ok": True}


class ResetIn(BaseModel):
    new_password: str


@router.post("/users/{uid}/reset-password")
def reset_password(uid: int, d: ResetIn, u=Depends(need("users.manage")), db=Depends(get_db)):
    target = db.get(User, uid)
    if not target:
        raise HTTPException(404, "Usuario no encontrado")
    if len(d.new_password) < 8:
        raise HTTPException(400, "La contraseña debe tener al menos 8 caracteres")
    target.password_hash = hash_password(d.new_password)
    log(db, u, "CLAVE_RESTABLECIDA", f"Se restableció la clave de {target.username}")
    db.commit()
    return {"ok": True}


# ---------- Usuarios ----------
class UserIn(BaseModel):
    username: str
    full_name: str
    password: str
    role: str


class ActiveIn(BaseModel):
    active: bool


@router.get("/backup")
def download_backup(u=Depends(need("users.manage")), db=Depends(get_db)):
    """Exportación manual. Incluye hashes de contraseñas; debe guardarse en un lugar privado."""
    from datetime import date
    models = [User, UserAdditionalRole, Product, Presentation, StockMovement, CashSession, CashIncome, Promotion, Sale, SaleItem, Expense, Supplier, Purchase, PurchaseItem, PurchasePayment, DiscountApproval, Setting, DocumentCounter, SaleRequest, AuditLog]
    tables = {}
    for model in models:
        rows = db.query(model).all()
        tables[model.__tablename__] = [
            {column.name: (value.isoformat() if isinstance(value, (datetime, date)) else value)
             for column in model.__table__.columns
             for value in [getattr(row, column.name)]}
            for row in rows
        ]
    log(db, u, "RESPALDO_DESCARGADO", "Exportación manual de datos")
    db.commit()
    return {"format": "stock-up-backup", "version": 1, "generated_at": datetime.utcnow().isoformat() + "Z", "tables": tables}


@router.get("/users")
def users(u=Depends(need("users.manage")), db=Depends(get_db)):
    return [{"id": x.id, "username": x.username, "full_name": x.full_name, "role": x.role,
             "additional_roles": get_additional_roles(x), "active": x.active}
            for x in db.query(User).order_by(User.id)]


@router.get("/users/basic")
def users_basic(u=Depends(need_any("sales.read", "users.manage")), db=Depends(get_db)):
    """Lista corta para los filtros por cajero."""
    return [{"id": x.id, "full_name": x.full_name, "role": x.role} for x in db.query(User).order_by(User.full_name)]


def ensure_role_manager(u):
    if not is_admin(u) or not allowed(u, "users.manage"):
        raise HTTPException(403, "Solo un administrador puede gestionar roles")


def get_role_target(uid, db, for_update=False):
    query = db.query(User).filter_by(id=uid)
    if for_update:
        query = query.with_for_update()
    target = query.first()
    if not target:
        raise HTTPException(404, "Usuario no encontrado")
    return target


def validate_additional_role_codes(role_codes, target):
    if len(role_codes) != len(set(str(code).strip().lower() for code in role_codes)):
        raise HTTPException(400, "No se pueden repetir roles adicionales")
    normalized = [str(code).strip().lower() for code in role_codes]
    for code in normalized:
        if not code:
            raise HTTPException(400, "El código del rol es obligatorio")
        if code == "admin":
            raise HTTPException(400, "Administrador no puede asignarse como rol adicional")
        if code not in PERMS:
            raise HTTPException(400, "Rol inexistente")
        if code == target.role:
            raise HTTPException(400, "El rol principal no puede repetirse como adicional")
    return sorted(normalized)


def replace_user_additional_roles(target, desired_codes, expected_codes, actor, db):
    if target.role == "admin":
        raise HTTPException(400, "El administrador no necesita roles adicionales")
    desired = validate_additional_role_codes(desired_codes, target)
    expected = validate_additional_role_codes(expected_codes, target)
    current = get_additional_roles(target)
    if expected != current:
        raise HTTPException(409, "Los roles cambiaron desde que abriste la ventana. Recarga y vuelve a intentarlo.")

    removed = sorted(set(current) - set(desired))
    added = sorted(set(desired) - set(current))
    for code in removed:
        db.query(UserAdditionalRole).filter_by(user_id=target.id, role_code=code).delete(synchronize_session=False)
        log(db, actor, "ROL_ADICIONAL_QUITADO", f"{target.username}: {code}")
    for code in added:
        db.add(UserAdditionalRole(user_id=target.id, role_code=code, assigned_by=actor.id))
        log(db, actor, "ROL_ADICIONAL_ASIGNADO", f"{target.username}: {code}")

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "No se pudieron guardar los roles; revisa las asignaciones actuales") from exc
    db.expire(target, ["additional_role_links"])
    return user_out(target)


class AdditionalRoleIn(BaseModel):
    role_code: str


class AdditionalRolesUpdateIn(BaseModel):
    role_codes: list[str]
    expected_role_codes: list[str]


@router.get("/roles")
def available_roles(u=Depends(current_user)):
    ensure_role_manager(u)
    return [{"code": code, "label": ROLE_LABELS[code]} for code in PERMS if code != "admin"]


@router.get("/users/{uid}/additional-roles")
def get_user_additional_roles(uid: int, u=Depends(current_user), db=Depends(get_db)):
    ensure_role_manager(u)
    target = get_role_target(uid, db)
    return {"id": target.id, "role": target.role, "additional_roles": get_additional_roles(target)}


@router.put("/users/{uid}/additional-roles")
def set_user_additional_roles(uid: int, d: AdditionalRolesUpdateIn, u=Depends(current_user), db=Depends(get_db)):
    ensure_role_manager(u)
    target = get_role_target(uid, db, for_update=True)
    return replace_user_additional_roles(target, d.role_codes, d.expected_role_codes, u, db)


@router.post("/users/{uid}/additional-roles")
def add_user_additional_role(uid: int, d: AdditionalRoleIn, u=Depends(current_user), db=Depends(get_db)):
    ensure_role_manager(u)
    target = get_role_target(uid, db, for_update=True)
    current = get_additional_roles(target)
    return replace_user_additional_roles(target, current + [d.role_code], current, u, db)


@router.delete("/users/{uid}/additional-roles/{role_code}")
def remove_user_additional_role(uid: int, role_code: str, u=Depends(current_user), db=Depends(get_db)):
    ensure_role_manager(u)
    target = get_role_target(uid, db, for_update=True)
    current = get_additional_roles(target)
    normalized = validate_additional_role_codes([role_code], target)[0]
    if normalized not in current:
        raise HTTPException(404, "El rol adicional no está asignado")
    remaining = [code for code in current if code != normalized]
    return replace_user_additional_roles(target, remaining, current, u, db)


@router.post("/users")
def add_user(d: UserIn, u=Depends(need("users.manage")), db=Depends(get_db)):
    if d.role not in PERMS:
        raise HTTPException(400, "Rol no válido")
    if len(d.password) < 8:
        raise HTTPException(400, "La contraseña debe tener al menos 8 caracteres")
    name = d.username.strip().lower()
    if not name or not d.full_name.strip():
        raise HTTPException(400, "El usuario y el nombre son obligatorios")
    if db.query(User).filter(User.username == name).first():
        raise HTTPException(400, "Ese usuario ya existe")
    db.add(User(username=name, full_name=d.full_name.strip(), role=d.role, password_hash=hash_password(d.password)))
    log(db, u, "USUARIO_CREADO", f"{name} ({d.role})")
    db.commit()
    return {"ok": True}


@router.put("/users/{uid}/active")
def set_active(uid: int, d: ActiveIn, u=Depends(need("users.manage")), db=Depends(get_db)):
    target = db.get(User, uid)
    if not target:
        raise HTTPException(404, "Usuario no encontrado")
    if target.id == u.id and not d.active:
        raise HTTPException(400, "No puedes desactivar tu propia cuenta")
    target.active = d.active
    log(db, u, "USUARIO_ACTIVADO" if d.active else "USUARIO_DESACTIVADO", target.username)
    db.commit()
    return {"ok": True}


# ---------- Configuración (solo administrador) ----------
class SettingsIn(BaseModel):
    blind_close: bool


@router.get("/settings")
def get_settings(u=Depends(need("settings.manage")), db=Depends(get_db)):
    return {"blind_close": get_setting(db, "blind_close", "1") == "1",
            "lookup_enabled": bool(PERU_API_TOKEN), "lookup_provider": PERU_API_PROVIDER}


@router.put("/settings")
def put_settings(d: SettingsIn, u=Depends(need("settings.manage")), db=Depends(get_db)):
    val = "1" if d.blind_close else "0"
    s = db.get(Setting, "blind_close")
    if s:
        s.value = val
    else:
        db.add(Setting(key="blind_close", value=val))
    log(db, u, "CONFIG_CAMBIADA", "Cierre de caja " + ("a ciegas" if d.blind_close else "con monto esperado visible"))
    db.commit()
    return {"ok": True}


# ---------- Consulta automática de DNI y RUC ----------
def _lookup_text(data, key):
    value = data.get(key)
    return value.strip() if isinstance(value, str) else ""


@router.get("/lookup/dni/{dni}")
def lookup_dni(dni: str, u=Depends(need_any("sales.create", "purchases.manage"))):
    if not (len(dni) == 8 and dni.isascii() and dni.isdigit()):
        raise HTTPException(400, "El DNI debe tener 8 dígitos")
    if not PERU_API_TOKEN:
        raise HTTPException(503, "La consulta automática de APISPERU no está configurada en el backend")
    r = http_json(f"https://dniruc.apisperu.com/api/v1/dni/{dni}")
    name = " ".join(v for v in (_lookup_text(r, "nombres"), _lookup_text(r, "apellidoPaterno"),
                                _lookup_text(r, "apellidoMaterno")) if v).strip()
    if not name:
        raise HTTPException(404, "No se encontró ese DNI")
    return {"dni": dni, "name": name}


@router.get("/lookup/ruc/{ruc}")
def lookup_ruc(ruc: str, u=Depends(need_any("sales.create", "purchases.manage"))):
    if not (len(ruc) == 11 and ruc.isascii() and ruc.isdigit()):
        raise HTTPException(400, "El RUC debe tener 11 dígitos")
    if not PERU_API_TOKEN:
        raise HTTPException(503, "La consulta automática de APISPERU no está configurada en el backend")
    r = http_json(f"https://dniruc.apisperu.com/api/v1/ruc/{ruc}")
    name = _lookup_text(r, "razonSocial")
    address = " ".join(v for v in (_lookup_text(r, "direccion"), _lookup_text(r, "distrito"),
                                   _lookup_text(r, "provincia"), _lookup_text(r, "departamento")) if v)
    status, cond = _lookup_text(r, "estado"), _lookup_text(r, "condicion")
    if not name:
        raise HTTPException(404, "No se encontró ese RUC")
    return {"ruc": ruc, "name": name, "address": address, "status": status, "condition": cond}
