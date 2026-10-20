import sys
from db import *

# "py seed.py --reset" borra las tablas anteriores y las crea de nuevo
if "--reset" in sys.argv:
    Base.metadata.drop_all(engine)
    print("Tablas anteriores eliminadas.")

Base.metadata.create_all(engine)
db = SessionLocal()

if db.query(User).count() == 0:
    usuarios = [
        ("admin", "Administrador General", "admin", "Admin123!"),
        ("cajero", "Carla Cajera", "cajero", "Cajero123!"),
        ("almacen", "Alex Almacén", "almacen", "Almacen123!"),
        ("supervisor", "Sofía Supervisora", "supervisor", "Super123!"),
        ("contador", "Carlos Contador", "contador", "Conta123!"),
    ]
    for u, n, r, p in usuarios:
        db.add(User(username=u, full_name=n, role=r, password_hash=hash_password(p)))
    db.flush()

if db.query(Product).count() == 0:
    # código, código de barras (None si no tiene), nombre, categoría, unidad, costo, precio, stock, mínimo
    # Los códigos de barras son de EJEMPLO: cámbialos por los reales de tus productos.
    productos = [
        ("P001", "7750000000011", "Arroz extra 1 kg", "Abarrotes", "paquete", 3.2, 4.5, 80, 15),
        ("P002", "7750000000028", "Aceite vegetal 1 L", "Abarrotes", "botella", 7.5, 9.9, 40, 10),
        ("P003", "7750000000035", "Azúcar rubia 1 kg", "Abarrotes", "paquete", 3.0, 4.2, 60, 15),
        ("P004", "7750000000042", "Leche evaporada 400 g", "Lácteos", "und", 3.4, 4.5, 100, 20),
        ("P005", "7750000000059", "Atún en aceite 170 g", "Conservas", "und", 4.8, 6.5, 8, 12),
        ("P006", "7750000000066", "Fideos spaghetti 500 g", "Abarrotes", "paquete", 2.2, 3.3, 70, 15),
        ("P007", "7750000000073", "Gaseosa 1.5 L", "Bebidas", "botella", 4.9, 6.9, 45, 12),
        ("P008", "7750000000080", "Agua mineral 625 ml", "Bebidas", "botella", 1.1, 2.0, 120, 24),
        ("P009", "7750000000097", "Detergente 800 g", "Limpieza", "bolsa", 8.5, 11.5, 25, 8),
        ("P010", "7750000000103", "Papel higiénico x4", "Limpieza", "paquete", 5.2, 7.5, 5, 10),
        ("P011", "7750000000110", "Galletas de soda", "Snacks", "und", 0.9, 1.5, 150, 30),
        ("P012", None, "Huevos", "Frescos", "und", 0.70, 0.90, 360, 60),
        ("P013", None, "Arroz a granel", "Abarrotes", "kg", 3.0, 4.2, 50, 10),
        ("P014", None, "Lentejas a granel", "Abarrotes", "kg", 5.0, 7.5, 30, 8),
        ("P015", "7750000000127", "Jabón de tocador", "Limpieza", "und", 1.8, 3.0, 0, 12),
    ]
    for c, bc, n, cat, un, co, pr, st, mn in productos:
        db.add(Product(code=c, barcode=bc, name=n, category=cat, unit=un, cost=co, price=pr, stock=st, min_stock=mn))
    db.flush()

    # código del producto, nombre de la presentación, unidades que trae, precio
    presentaciones = [
        ("P012", "Docena", 12, 10.00),
        ("P012", "Jaba x30", 30, 24.00),
        ("P013", "Saco 50 kg", 50, 195.00),
        ("P007", "Caja x6", 6, 39.00),
        ("P008", "Paquete x12", 12, 21.60),
    ]
    for code, nombre, factor, precio in presentaciones:
        prod = db.query(Product).filter(Product.code == code).first()
        db.add(Presentation(product_id=prod.id, name=nombre, factor=factor, price=precio))

    # Movimientos iniciales de inventario (para que el historial no empiece vacío)
    admin = db.query(User).filter(User.username == "admin").first()
    for prod in db.query(Product).all():
        if prod.stock > 0:
            db.add(StockMovement(product_id=prod.id, kind="entrada", motive="compra", qty=prod.stock,
                                 prev_stock=0, new_stock=prod.stock,
                                 reason="Stock inicial de demostración", user_id=admin.id))

if db.query(Promotion).count() == 0:
    huevos = db.query(Product).filter(Product.code == "P012").first()
    db.add(Promotion(name="10% de descuento en compras desde S/ 50", kind="percent", value=10, scope="sale", min_total=50))
    db.add(Promotion(name="S/ 5 de descuento en compras desde S/ 80", kind="amount", value=5, scope="sale", min_total=80))
    db.add(Promotion(name="Huevos: 10% de descuento", kind="percent", value=10, scope="product", product_id=huevos.id))

if not db.get(Setting, "blind_close"):
    db.add(Setting(key="blind_close", value="1"))  # 1 = cierre a ciegas, 0 = muestra el monto esperado

db.commit()
print("Base de datos lista. Usuarios: admin, cajero, almacen, supervisor, contador")