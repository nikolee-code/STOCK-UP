from fastapi import APIRouter
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
def change_password(d: PwdIn, u=Depends(need("users.manage")), db=Depends(get_db)):
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


@router.get("/users")
def users(u=Depends(need("users.manage")), db=Depends(get_db)):
    return [{"id": x.id, "username": x.username, "full_name": x.full_name, "role": x.role, "active": x.active}
            for x in db.query(User).order_by(User.id)]


@router.get("/users/basic")
def users_basic(u=Depends(need_any("sales.read", "users.manage")), db=Depends(get_db)):
    """Lista corta para los filtros por cajero."""
    return [{"id": x.id, "full_name": x.full_name, "role": x.role} for x in db.query(User).order_by(User.full_name)]


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
@router.get("/lookup/dni/{dni}")
def lookup_dni(dni: str, u=Depends(need("sales.create"))):
    dni = dni.strip()
    if not (dni.isdigit() and len(dni) == 8):
        raise HTTPException(400, "El DNI debe tener 8 dígitos")
    if not PERU_API_TOKEN:
        raise HTTPException(503, "La consulta automática de APISPERU no está configurada. Un administrador debe guardar PERU_API_TOKEN en Render.")
    r = http_json(f"https://dniruc.apisperu.com/api/v1/dni/{dni}")
    name = " ".join(v for v in [r.get("nombres"), r.get("apellidoPaterno"), r.get("apellidoMaterno")] if v)
    name = (name or "").strip()
    if not name:
        raise HTTPException(404, "No se encontró ese DNI")
    return {"dni": dni, "name": name}


@router.get("/lookup/ruc/{ruc}")
def lookup_ruc(ruc: str, u=Depends(need("sales.create"))):
    ruc = ruc.strip()
    if not (ruc.isdigit() and len(ruc) == 11):
        raise HTTPException(400, "El RUC debe tener 11 dígitos")
    if not PERU_API_TOKEN:
        raise HTTPException(503, "La consulta automática de APISPERU no está configurada. Un administrador debe guardar PERU_API_TOKEN en Render.")
    r = http_json(f"https://dniruc.apisperu.com/api/v1/ruc/{ruc}")
    name = r.get("razonSocial")
    address = " ".join(v for v in [r.get("direccion"), r.get("distrito"), r.get("provincia"),
                                   r.get("departamento")] if v)
    status, cond = r.get("estado"), r.get("condicion")
    if not name:
        raise HTTPException(404, "No se encontró ese RUC")
    return {"ruc": ruc, "name": name.strip(), "address": (address or "").strip(),
            "status": status or "", "condition": cond or ""}
