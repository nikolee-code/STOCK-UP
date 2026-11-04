import os
import inspect
import sys
import tempfile
import unittest
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


os.environ["DATABASE_URL"] = "sqlite://"
os.environ["APP_ENV"] = "test"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import db
import r_catalog
from common import allowed, need, need_any


class ProductPermissionsAndStockTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self.temp_dir.name) / "product-permissions.sqlite"
        self.engine = create_engine(f"sqlite:///{db_path.as_posix()}")
        db.Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, autoflush=False)
        self.session = self.Session()

        self.admin = db.User(
            username="product-admin",
            full_name="Product Admin",
            password_hash="test-hash",
            role="admin",
            active=True,
        )
        self.supervisor = db.User(
            username="product-supervisor",
            full_name="Product Supervisor",
            password_hash="test-hash",
            role="supervisor",
            active=True,
        )
        self.warehouse = db.User(
            username="product-warehouse",
            full_name="Product Warehouse",
            password_hash="test-hash",
            role="almacen",
            active=True,
        )
        self.product = db.Product(
            code="MIN001",
            name="Producto de prueba",
            category="General",
            unit="und",
            cost=2.5,
            price=4.0,
            stock=10,
            min_stock=5,
            active=True,
        )
        self.session.add_all([self.admin, self.supervisor, self.warehouse, self.product])
        self.session.flush()
        self.presentation = db.Presentation(
            product_id=self.product.id,
            name="Paquete",
            factor=2,
            price=7.5,
            barcode=None,
            active=True,
        )
        self.history = db.StockMovement(
            product_id=self.product.id,
            kind="entrada",
            motive="compra",
            qty=10,
            prev_stock=0,
            new_stock=10,
            reason="Ingreso histórico de prueba",
            user_id=self.admin.id,
        )
        self.session.add_all([self.presentation, self.history])
        self.session.commit()
        self.admin_id = self.admin.id
        self.supervisor_id = self.supervisor.id
        self.warehouse_id = self.warehouse.id
        self.product_id = self.product.id
        self.presentation_id = self.presentation.id
        self.history_id = self.history.id
        self.session.close()

    def tearDown(self):
        self.engine.dispose()
        self.temp_dir.cleanup()

    def payload(self, **overrides):
        values = {
            "code": "MIN001",
            "barcode": "",
            "name": "Producto de prueba",
            "category": "General",
            "unit": "und",
            "cost": 2.5,
            "price": 4.0,
            "min_stock": 5,
            "presentations": [r_catalog.PresIn(
                id=self.presentation_id, name="Paquete", factor=2, price=7.5, barcode=""
            )],
        }
        values.update(overrides)
        return r_catalog.ProductIn(**values)

    def test_supervisor_can_read_products_and_movements_but_cannot_write(self):
        with self.Session() as session:
            supervisor = session.get(db.User, self.supervisor_id)
            self.assertTrue(allowed(supervisor, "products.read"))
            self.assertTrue(allowed(supervisor, "stock.read"))
            self.assertFalse(allowed(supervisor, "products.write"))
            self.assertFalse(allowed(supervisor, "stock.adjust"))
            need("products.read")(supervisor)
            need_any("stock.read", "stock.adjust")(supervisor)
            self.assertEqual(len(r_catalog.products(supervisor, session)), 1)
            self.assertEqual(len(r_catalog.movements(u=supervisor, db=session)), 1)
            read_products = inspect.signature(r_catalog.products).parameters["u"].default.dependency
            read_movements = inspect.signature(r_catalog.movements).parameters["u"].default.dependency
            read_products(supervisor)
            read_movements(supervisor)
            write_endpoints = (
                r_catalog.add_product,
                r_catalog.update_product,
                r_catalog.archive_product,
            )
            for endpoint in write_endpoints:
                dependency = inspect.signature(endpoint).parameters["u"].default.dependency
                with self.subTest(endpoint=endpoint.__name__), self.assertRaises(HTTPException) as caught:
                    dependency(supervisor)
                self.assertEqual(caught.exception.status_code, 403)
            adjust_stock = inspect.signature(r_catalog.move).parameters["u"].default.dependency
            with self.assertRaises(HTTPException) as caught:
                adjust_stock(supervisor)
                self.assertEqual(caught.exception.status_code, 403)

    def test_additional_warehouse_role_legitimately_grants_write_and_stock_adjust(self):
        with self.Session() as session:
            session.add(db.UserAdditionalRole(
                user_id=self.supervisor_id,
                role_code="almacen",
                assigned_by=self.admin_id,
            ))
            session.commit()
            supervisor = session.get(db.User, self.supervisor_id)
            self.assertTrue(allowed(supervisor, "products.write"))
            self.assertTrue(allowed(supervisor, "stock.adjust"))
            need("products.write")(supervisor)
            need("stock.adjust")(supervisor)

    def test_admin_can_edit_product_and_stock_minimum_zero_without_losing_stock_history(self):
        with self.Session() as session:
            admin = session.get(db.User, self.admin_id)
            result = r_catalog.update_product(
                self.product_id,
                self.payload(name="Producto actualizado", price=6.25, min_stock=0),
                admin,
                session,
            )
            self.assertEqual(result, {"ok": True})

        with self.Session() as session:
            saved = session.get(db.Product, self.product_id)
            self.assertEqual(saved.name, "Producto actualizado")
            self.assertEqual(saved.price, 6.25)
            self.assertEqual(saved.min_stock, 0)
            self.assertEqual(saved.stock, 10)
            history = session.get(db.StockMovement, self.history_id)
            self.assertEqual((history.prev_stock, history.new_stock, history.qty), (0, 10, 10))
            self.assertEqual(session.query(db.StockMovement).filter_by(product_id=self.product_id).count(), 1)

    def test_admin_stock_edit_creates_an_auditable_movement_and_preserves_other_fields(self):
        with self.Session() as session:
            admin = session.get(db.User, self.admin_id)
            result = r_catalog.update_product(
                self.product_id,
                self.payload(current_stock=14),
                admin,
                session,
            )
            self.assertEqual(result, {"ok": True})

        with self.Session() as session:
            saved = session.get(db.Product, self.product_id)
            presentation = session.get(db.Presentation, self.presentation_id)
            self.assertEqual(saved.stock, 14)
            self.assertEqual(saved.min_stock, 5)
            self.assertEqual((saved.name, saved.price, saved.cost), ("Producto de prueba", 4, 2.5))
            self.assertEqual((presentation.name, presentation.factor, presentation.price, presentation.active),
                             ("Paquete", 2, 7.5, True))
            self.assertEqual(session.get(db.StockMovement, self.history_id).new_stock, 10)
            movements = session.query(db.StockMovement).filter(
                db.StockMovement.product_id == self.product_id,
                db.StockMovement.id != self.history_id,
            ).all()
            self.assertEqual(len(movements), 1)
            movement = movements[0]
            self.assertEqual(movement.kind, "ajuste_administrativo")
            self.assertEqual(movement.motive, "ajuste_administrativo")
            self.assertEqual((movement.prev_stock, movement.new_stock, movement.qty), (10, 14, 4))
            self.assertEqual(movement.user_id, self.admin_id)
            self.assertIn("edición administrativa", movement.reason)
            self.assertEqual(
                r_catalog.motive_label(movement),
                "Ajuste administrativo desde edición del producto",
            )
            self.assertEqual(
                session.query(db.AuditLog).filter_by(action="INVENTARIO_AJUSTE_ADMIN").count(), 1
            )

    def test_non_admin_cannot_directly_change_stock_even_with_warehouse_write_permission(self):
        with self.Session() as session:
            session.add(db.UserAdditionalRole(
                user_id=self.supervisor_id,
                role_code="almacen",
                assigned_by=self.admin_id,
            ))
            session.commit()
            warehouse = session.get(db.User, self.warehouse_id)
            supervisor_with_warehouse = session.get(db.User, self.supervisor_id)
            for actor in (warehouse, supervisor_with_warehouse):
                with self.subTest(role=actor.role, additional_roles=[x.role_code for x in actor.additional_role_links]):
                    self.assertTrue(allowed(actor, "products.write"))
                    with self.assertRaises(HTTPException) as caught:
                        r_catalog.update_product(
                            self.product_id,
                            self.payload(current_stock=3),
                            actor,
                            session,
                        )
                    self.assertEqual(caught.exception.status_code, 403)

        with self.Session() as session:
            self.assertEqual(session.get(db.Product, self.product_id).stock, 10)
            self.assertEqual(session.query(db.StockMovement).filter_by(product_id=self.product_id).count(), 1)

    def test_admin_cannot_set_negative_or_fractional_stock_for_integer_unit(self):
        with self.Session() as session:
            admin = session.get(db.User, self.admin_id)
            for value in (-1, 1.5):
                with self.subTest(current_stock=value), self.assertRaises(HTTPException) as caught:
                    r_catalog.update_product(
                        self.product_id,
                        self.payload(current_stock=value),
                        admin,
                        session,
                    )
                self.assertEqual(caught.exception.status_code, 400)

        with self.Session() as session:
            self.assertEqual(session.get(db.Product, self.product_id).stock, 10)
            self.assertEqual(session.query(db.StockMovement).filter_by(product_id=self.product_id).count(), 1)


if __name__ == "__main__":
    unittest.main()
