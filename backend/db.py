import os, hashlib, secrets
from datetime import datetime
from dotenv import load_dotenv
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, ForeignKey, Text, Boolean, UniqueConstraint
from sqlalchemy.orm import declarative_base, sessionmaker

load_dotenv()  # lee backend/.env

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./stockup.db")

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False)
Base = declarative_base()


def hash_password(pw: str) -> str:
    salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 200_000).hex()
    return f"{salt}${h}"


def verify_password(pw: str, stored: str) -> bool:
    salt, h = stored.split("$")
    calc = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 200_000).hex()
    return secrets.compare_digest(calc, h)


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String(50), unique=True, nullable=False)
    full_name = Column(String(120), nullable=False)
    password_hash = Column(String(200), nullable=False)
    role = Column(String(30), nullable=False)
    active = Column(Boolean, default=True)


class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True)
    code = Column(String(50), unique=True, nullable=False)   # código interno
    barcode = Column(String(50), unique=True)                # código de barras (opcional)
    name = Column(String(150), nullable=False)
    category = Column(String(80), default="General")
    unit = Column(String(20), default="und")                 # unidad base: und, kg, g, lt, m...
    cost = Column(Float, default=0)                          # costo por unidad base
    price = Column(Float, default=0)                         # precio por unidad base
    stock = Column(Float, default=0)                         # en unidades base
    min_stock = Column(Float, default=5)
    active = Column(Boolean, default=True)


class Presentation(Base):
    """Otra forma de vender el mismo producto: docena, jaba, saco, caja..."""
    __tablename__ = "presentations"
    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    name = Column(String(40), nullable=False)
    factor = Column(Float, nullable=False)                   # cuántas unidades base trae
    price = Column(Float, nullable=False)
    barcode = Column(String(50), unique=True)
    active = Column(Boolean, default=True)


class StockMovement(Base):
    __tablename__ = "stock_movements"
    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("products.id"))
    kind = Column(String(30))          # entrada, salida, venta, anulacion
    motive = Column(String(30))        # compra, vencido, danado...
    note = Column(String(200))
    qty = Column(Float)                # + entra, - sale (en unidades base)
    prev_stock = Column(Float)
    new_stock = Column(Float)
    reason = Column(Text)
    user_id = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)


class CashSession(Base):
    __tablename__ = "cash_sessions"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    opened_at = Column(DateTime, default=datetime.utcnow)
    opening_amount = Column(Float, default=0)
    closed_at = Column(DateTime)
    counted_amount = Column(Float)
    expected_amount = Column(Float)
    difference = Column(Float)
    note = Column(Text)
    status = Column(String(15), default="abierta")


class Promotion(Base):
    """Promociones y descuentos que define el administrador."""
    __tablename__ = "promotions"
    id = Column(Integer, primary_key=True)
    name = Column(String(80), nullable=False)
    kind = Column(String(10), nullable=False)                # percent (%) o amount (S/)
    value = Column(Float, nullable=False)
    scope = Column(String(10), default="sale")               # sale (toda la venta) o product
    product_id = Column(Integer, ForeignKey("products.id"), nullable=True)
    min_total = Column(Float, default=0)                     # compra mínima
    starts = Column(String(10))                              # AAAA-MM-DD (opcional)
    ends = Column(String(10))
    active = Column(Boolean, default=True)


class Sale(Base):
    __tablename__ = "sales"
    __table_args__ = (UniqueConstraint("doc_series", "doc_number", name="uq_sale_doc"),)
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    cash_session_id = Column(Integer, ForeignKey("cash_sessions.id"))
    subtotal = Column(Float, default=0)
    discount = Column(Float, default=0)
    promo_id = Column(Integer)
    promo_name = Column(String(80))
    total = Column(Float, default=0)
    payment_method = Column(String(20), default="efectivo")
    payment_ref = Column(String(60))
    doc_type = Column(String(20), default="boleta")
    doc_series = Column(String(10))
    doc_number = Column(Integer)
    customer_doc_type = Column(String(10))
    customer_doc = Column(String(20))
    customer_name = Column(String(150))
    customer_address = Column(String(200))
    status = Column(String(15), default="completada")       # completada o anulada
    voided_at = Column(DateTime)
    voided_by = Column(Integer, ForeignKey("users.id"))
    void_reason = Column(String(200))
    created_at = Column(DateTime, default=datetime.utcnow)


class SaleRequest(Base):
    """Clave idempotente del cliente para no duplicar ventas al reintentar una solicitud."""
    __tablename__ = "sale_requests"
    request_id = Column(String(64), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    sale_id = Column(Integer, ForeignKey("sales.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class SaleItem(Base):
    __tablename__ = "sale_items"
    id = Column(Integer, primary_key=True)
    sale_id = Column(Integer, ForeignKey("sales.id"))
    product_id = Column(Integer, ForeignKey("products.id"))
    presentation_id = Column(Integer, ForeignKey("presentations.id"), nullable=True)
    description = Column(String(200))
    qty = Column(Float)
    price = Column(Float)
    unit_factor = Column(Float, default=1)
    cost = Column(Float, default=0)                          # costo total de la línea


class Expense(Base):
    """Egresos: pagos y salidas de dinero."""
    __tablename__ = "expenses"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    cash_session_id = Column(Integer, ForeignKey("cash_sessions.id"), nullable=True)
    concept = Column(String(150), nullable=False)
    category = Column(String(40), default="Otros")
    amount = Column(Float, nullable=False)
    from_cash = Column(Boolean, default=True)                # sale del efectivo de la caja
    status = Column(String(15), default="activo")            # activo o anulado
    created_at = Column(DateTime, default=datetime.utcnow)


class Setting(Base):
    __tablename__ = "settings"
    key = Column(String(50), primary_key=True)
    value = Column(String(200))


class DocumentCounter(Base):
    """Contador atómico por serie para evitar números duplicados con varios cajeros."""
    __tablename__ = "document_counters"
    series = Column(String(10), primary_key=True)
    next_number = Column(Integer, nullable=False, default=1)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    action = Column(String(50))
    detail = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)