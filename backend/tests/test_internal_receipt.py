import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest import mock
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


os.environ["DATABASE_URL"] = "sqlite://"
os.environ["APP_ENV"] = "test"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import db
import r_sales


class InternalReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self.temp_dir.name) / "internal-receipt.sqlite"
        self.engine = create_engine(f"sqlite:///{db_path.as_posix()}")
        db.Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, autoflush=False)
        self.session = self.Session()

        self.cashier = db.User(
            username="receipt-cashier", full_name="Caja de prueba", password_hash="unused",
            role="cajero", active=True,
        )
        self.supervisor = db.User(
            username="receipt-supervisor", full_name="Supervisor de prueba", password_hash="unused",
            role="supervisor", active=True,
        )
        self.admin = db.User(
            username="receipt-admin", full_name="Administrador de prueba", password_hash="unused",
            role="admin", active=True,
        )
        self.product = db.Product(
            code="RCPT001", name="Producto de prueba", category="General", unit="und",
            cost=2, price=10, stock=10, min_stock=0, active=True,
        )
        self.session.add_all([self.cashier, self.supervisor, self.admin, self.product])
        self.session.flush()
        self.cash = db.CashSession(user_id=self.cashier.id, opening_amount=50, status="abierta")
        self.admin_cash = db.CashSession(user_id=self.admin.id, opening_amount=50, status="abierta")
        self.session.add_all([self.cash, self.admin_cash])
        self.session.commit()

    def tearDown(self):
        self.session.close()
        self.engine.dispose()
        self.temp_dir.cleanup()

    def payload(self, **overrides):
        values = {
            "items": [r_sales.ItemIn(product_id=self.product.id, qty=2)],
            "payment_method": "efectivo",
            "doc_type": "comprobante_interno",
            "customer_doc": "12345678",
            "customer_name": "Cliente de prueba",
            "customer_address": "Dirección de prueba",
            "idempotency_key": "internal-receipt-key-0001",
        }
        values.update(overrides)
        return r_sales.SaleIn(**values)

    def test_sale_receipt_persists_and_retry_does_not_duplicate_inventory_or_sale(self):
        first = r_sales.create_sale(self.payload(), self.cashier, self.session)

        self.assertEqual(first["doc_type"], "comprobante_interno")
        self.assertEqual(first["number"], "INT-00000001")
        self.assertEqual(first["customer_doc_type"], "DNI")
        self.assertEqual(first["customer_doc"], "12345678")
        self.assertEqual(first["subtotal"], 20)
        self.assertEqual(first["total"], 20)
        self.assertEqual(first["payment"], "Efectivo")
        self.assertTrue(first["taxes_are_reference"])

        retry = r_sales.create_sale(self.payload(), self.cashier, self.session)
        self.assertEqual(retry["id"], first["id"])
        self.assertEqual(self.session.query(db.Sale).count(), 1)
        self.assertEqual(self.session.query(db.SaleItem).count(), 1)
        self.assertEqual(self.session.query(db.StockMovement).filter_by(kind="venta").count(), 1)
        self.assertEqual(self.session.get(db.Product, self.product.id).stock, 8)
        saved_cash = self.session.get(db.CashSession, self.cash.id)
        self.assertEqual(saved_cash.opening_amount, 50)
        self.assertEqual(saved_cash.status, "abierta")

        saved = r_sales.get_sale(first["id"], self.cashier, self.session)
        self.assertEqual(saved["number"], first["number"])
        self.assertEqual(saved["items"][0]["description"], "Producto de prueba")

    def test_internal_receipt_accepts_ruc_and_optional_customer_details(self):
        result = r_sales.create_sale(
            self.payload(customer_doc="20123456789", customer_name="Empresa de prueba"),
            self.cashier,
            self.session,
        )
        self.assertEqual(result["customer_doc_type"], "RUC")
        self.assertEqual(result["customer_doc"], "20123456789")

    def test_generic_customer_can_buy_without_document(self):
        result = r_sales.create_sale(
            self.payload(customer_doc="", customer_name="Cliente genérico", customer_address=""),
            self.cashier,
            self.session,
        )
        self.assertEqual(result["customer_name"], "Cliente genérico")
        self.assertEqual(result["customer_doc_type"], "")
        self.assertEqual(result["customer_doc"], "")

    def test_note_sale_needs_no_customer_and_uses_int_even_above_five(self):
        result = r_sales.create_sale(
            self.payload(
                doc_type="nota_interna", customer_doc="no es un documento", customer_name="Dato anterior",
                customer_address="Dirección anterior", idempotency_key="note-no-customer-request-001",
            ),
            self.cashier,
            self.session,
        )
        self.assertEqual(result["doc_type"], "nota_interna")
        self.assertEqual(result["doc_name"], "Nota de venta")
        self.assertEqual(result["series"], "INT")
        self.assertEqual(result["number"], "INT-00000001")
        self.assertEqual(result["customer_doc_type"], "")
        self.assertEqual(result["customer_doc"], "")
        self.assertEqual(result["customer_name"], "")
        self.assertEqual(result["customer_address"], "")
        self.assertEqual(result["total"], 20)
        self.assertEqual(self.session.get(db.Product, self.product.id).stock, 8)

    def test_all_available_payment_methods_register_as_sales(self):
        for index, method in enumerate(r_sales.PAYMENTS, start=1):
            result = r_sales.create_sale(
                self.payload(
                    payment_method=method,
                    payment_ref="op-123" if method != "efectivo" else "",
                    idempotency_key=f"internal-payment-key-{index:04d}",
                    items=[r_sales.ItemIn(product_id=self.product.id, qty=1)],
                    customer_doc="",
                ),
                self.cashier,
                self.session,
            )
            self.assertEqual(result["payment"], r_sales.PAYMENTS[method])
            self.assertEqual(result["doc_type"], "comprobante_interno")
        self.assertEqual(self.session.query(db.Sale).count(), len(r_sales.PAYMENTS))
        self.assertEqual(self.session.query(db.StockMovement).filter_by(kind="venta").count(), len(r_sales.PAYMENTS))
        self.assertEqual(
            self.session.query(db.Sale).filter_by(cash_session_id=self.cash.id).count(), len(r_sales.PAYMENTS)
        )
        self.assertEqual(self.session.get(db.Product, self.product.id).stock, 10 - len(r_sales.PAYMENTS))

    def test_authorized_discount_is_applied_once_and_audited(self):
        approval = db.DiscountApproval(
            token_id="discount-approval-for-test-0001",
            cashier_id=self.cashier.id,
            supervisor_id=self.supervisor.id,
            amount=2,
            expires_at=datetime.utcnow() + timedelta(minutes=5),
        )
        self.session.add(approval)
        self.session.commit()

        result = r_sales.create_sale(
            self.payload(discount_amount=2, authorization_id=approval.token_id),
            self.cashier,
            self.session,
        )

        self.assertEqual(result["subtotal"], 20)
        self.assertEqual(result["discount"], 2)
        self.assertEqual(result["total"], 18)
        self.assertEqual(self.session.query(db.DiscountApproval).one().sale_id, result["id"])
        self.assertEqual(self.session.query(db.AuditLog).filter_by(action="DESCUENTO_APLICADO").count(), 1)
        self.assertEqual(self.session.get(db.Product, self.product.id).stock, 8)

    def test_invalid_customer_document_rolls_back_without_sale_or_stock_change(self):
        with self.assertRaises(HTTPException) as caught:
            r_sales.create_sale(self.payload(customer_doc="1234"), self.cashier, self.session)
        self.assertEqual(caught.exception.status_code, 400)
        self.session.rollback()
        self.assertEqual(self.session.query(db.Sale).count(), 0)
        self.assertEqual(self.session.query(db.StockMovement).count(), 0)
        self.assertEqual(self.session.get(db.Product, self.product.id).stock, 10)

    def test_cashier_can_register_boleta_and_factura_without_cpe(self):
        with mock.patch.object(r_sales, "CPE_ENABLED", False):
            boleta = r_sales.create_sale(
                self.payload(doc_type="boleta", customer_doc="12345678"), self.cashier, self.session
            )
            factura = r_sales.create_sale(
                self.payload(
                    doc_type="factura", customer_doc="20123456789", customer_name="Empresa de prueba",
                    idempotency_key="legacy-invoice-request-0001",
                ),
                self.cashier,
                self.session,
            )
        self.assertEqual(boleta["doc_type"], "boleta")
        self.assertEqual(boleta["series"], "BI01")
        self.assertEqual(boleta["number"], "BI01-00000001")
        self.assertEqual(boleta["doc_name"], "Boleta de venta electrónica")
        self.assertTrue(boleta["taxes_are_reference"])
        self.assertEqual(factura["doc_type"], "factura")
        self.assertEqual(factura["series"], "FI01")
        self.assertEqual(factura["number"], "FI01-00000001")
        self.assertEqual(factura["doc_name"], "Factura electrónica")
        self.assertTrue(factura["taxes_are_reference"])
        self.assertEqual(self.session.query(db.Sale).count(), 2)
        self.assertEqual(self.session.query(db.StockMovement).filter_by(kind="venta").count(), 2)
        self.assertEqual(self.session.get(db.Product, self.product.id).stock, 6)

    def test_admin_can_register_all_three_document_types(self):
        self.assertTrue(r_sales.allowed(self.admin, "sales.create"))
        requests = [
            self.payload(doc_type="boleta", customer_doc="", customer_name=""),
            self.payload(
                doc_type="factura", customer_doc="20123456789", customer_name="Empresa de prueba",
                idempotency_key="admin-invoice-request-0001",
            ),
            self.payload(
                doc_type="nota_interna", customer_doc="", customer_name="",
                idempotency_key="admin-note-request-key-01",
            ),
        ]
        results = [r_sales.create_sale(request, self.admin, self.session) for request in requests]
        self.assertEqual([item["doc_type"] for item in results], ["boleta", "factura", "nota_interna"])
        self.assertEqual([item["number"] for item in results], [
            "BI01-00000001", "FI01-00000001", "INT-00000001",
        ])
        self.assertEqual(self.session.query(db.Sale).filter_by(user_id=self.admin.id).count(), 3)

    def test_correlative_counters_are_independent_and_history_keeps_selected_type(self):
        sequence = ["boleta", "factura", "nota_interna", "comprobante_interno", "boleta", "factura", "nota_interna"]
        expected = [
            "BI01-00000001", "FI01-00000001", "INT-00000001", "INT-00000002",
            "BI01-00000002", "FI01-00000002", "INT-00000003",
        ]
        results = []
        for index, doc_type in enumerate(sequence, start=1):
            customer = {"customer_doc": "", "customer_name": ""}
            if doc_type == "boleta":
                customer = {"customer_doc": "12345678", "customer_name": "Cliente"}
            elif doc_type == "factura":
                customer = {"customer_doc": "20123456789", "customer_name": "Empresa de prueba"}
            result = r_sales.create_sale(
                self.payload(
                    doc_type=doc_type,
                    items=[r_sales.ItemIn(product_id=self.product.id, qty=1)],
                    idempotency_key=f"independent-counter-key-{index:04d}",
                    **customer,
                ),
                self.cashier,
                self.session,
            )
            results.append(result)
        self.assertEqual([item["number"] for item in results], expected)
        for item, doc_type in zip(results, sequence):
            historic = r_sales.get_sale(item["id"], self.cashier, self.session)
            self.assertEqual(historic["doc_type"], doc_type)
            self.assertEqual(historic["number"], item["number"])

    def test_identification_requested_for_boleta_is_enforced_by_backend(self):
        with self.assertRaises(HTTPException) as caught:
            r_sales.create_sale(
                self.payload(doc_type="boleta", customer_doc="", customer_name="", customer_identification_requested=True),
                self.cashier,
                self.session,
            )
        self.assertEqual(caught.exception.status_code, 400)
        self.session.rollback()
        self.assertEqual(self.session.query(db.Sale).count(), 0)
        self.assertEqual(self.session.get(db.Product, self.product.id).stock, 10)

    def test_boleta_over_limit_requires_identification_in_backend(self):
        self.product.stock = 100
        self.session.commit()
        with self.assertRaises(HTTPException) as caught:
            r_sales.create_sale(
                self.payload(
                    items=[r_sales.ItemIn(product_id=self.product.id, qty=71)],
                    doc_type="boleta", customer_doc="", customer_name="",
                ),
                self.cashier,
                self.session,
            )
        self.assertEqual(caught.exception.status_code, 400)
        self.session.rollback()
        self.assertEqual(self.session.query(db.Sale).count(), 0)
        self.assertEqual(self.session.get(db.Product, self.product.id).stock, 100)

    def test_sales_permission_with_additional_cashier_role_is_not_blocked_by_primary_role(self):
        warehouse = db.User(
            username="receipt-warehouse-cashier", full_name="Almacén y caja", password_hash="unused",
            role="almacen", active=True,
        )
        self.session.add(warehouse)
        self.session.flush()
        self.session.add(db.UserAdditionalRole(
            user_id=warehouse.id, role_code="cajero", assigned_by=self.admin.id,
        ))
        cash = db.CashSession(user_id=warehouse.id, opening_amount=0, status="abierta")
        self.session.add(cash)
        self.session.commit()
        self.session.refresh(warehouse)
        self.assertTrue(r_sales.allowed(warehouse, "sales.create"))
        result = r_sales.create_sale(self.payload(), warehouse, self.session)
        self.assertEqual(result["doc_type"], "comprobante_interno")


if __name__ == "__main__":
    unittest.main()
