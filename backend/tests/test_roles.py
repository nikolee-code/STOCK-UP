import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


os.environ["DATABASE_URL"] = "sqlite://"
os.environ["APP_ENV"] = "test"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import db
import migrate_local_roles
import r_auth
from common import (
    PERMS,
    allowed,
    get_effective_permissions,
    get_effective_roles,
    has_role,
    hash_password,
)
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError


class RolePermissionsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db.Base.metadata.create_all(db.engine)

    def setUp(self):
        db.Base.metadata.drop_all(db.engine)
        db.Base.metadata.create_all(db.engine)
        self.session = db.SessionLocal()
        self.admin = db.User(
            username="admin-test", full_name="Admin Test", password_hash=hash_password("safe-test-pass"),
            role="admin", active=True,
        )
        self.warehouse = db.User(
            username="warehouse-test", full_name="Warehouse Test", password_hash=hash_password("warehouse-pass"),
            role="almacen", active=True,
        )
        self.session.add_all([self.admin, self.warehouse])
        self.session.commit()
        self.session.refresh(self.admin)
        self.session.refresh(self.warehouse)

    def tearDown(self):
        self.session.close()

    def test_warehouse_without_additional_roles_keeps_original_permissions(self):
        self.assertEqual(get_effective_roles(self.warehouse), ["almacen"])
        self.assertEqual(set(get_effective_permissions(self.warehouse)), set(PERMS["almacen"]))
        self.assertFalse(allowed(self.warehouse, "sales.create"))

    def test_warehouse_and_cashier_permissions_accumulate_without_changing_account(self):
        before_hash = self.warehouse.password_hash
        result = r_auth.add_user_additional_role(
            self.warehouse.id, r_auth.AdditionalRoleIn(role_code="cajero"), self.admin, self.session
        )
        self.assertEqual(result["role"], "almacen")
        self.assertEqual(result["additional_roles"], ["cajero"])
        self.assertTrue(allowed(self.warehouse, "sales.create"))
        self.assertTrue(allowed(self.warehouse, "products.write"))
        self.assertEqual(self.warehouse.password_hash, before_hash)
        link = self.session.query(db.UserAdditionalRole).filter_by(user_id=self.warehouse.id).one()
        self.assertEqual(link.assigned_by, self.admin.id)
        self.assertIsNotNone(link.assigned_at)

    def test_three_roles_accumulate_as_a_set(self):
        r_auth.set_user_additional_roles(
            self.warehouse.id,
            r_auth.AdditionalRolesUpdateIn(role_codes=["cajero", "contador"], expected_role_codes=[]),
            self.admin,
            self.session,
        )
        self.assertEqual(get_effective_roles(self.warehouse), ["almacen", "cajero", "contador"])
        self.assertEqual(
            set(get_effective_permissions(self.warehouse)),
            set(PERMS["almacen"]) | set(PERMS["cajero"]) | set(PERMS["contador"]),
        )
        self.assertEqual(len(get_effective_permissions(self.warehouse)), len(set(get_effective_permissions(self.warehouse))))
        self.assertEqual(self.warehouse.role, "almacen")

    def test_repeated_role_is_rejected(self):
        r_auth.add_user_additional_role(
            self.warehouse.id, r_auth.AdditionalRoleIn(role_code="cajero"), self.admin, self.session
        )
        with self.assertRaises(HTTPException) as caught:
            r_auth.add_user_additional_role(
                self.warehouse.id, r_auth.AdditionalRoleIn(role_code="cajero"), self.admin, self.session
            )
        self.assertEqual(caught.exception.status_code, 400)
        with self.assertRaises(HTTPException):
            r_auth.set_user_additional_roles(
                self.warehouse.id,
                r_auth.AdditionalRolesUpdateIn(role_codes=["contador", "contador"], expected_role_codes=["cajero"]),
                self.admin,
                self.session,
            )

    def test_admin_unknown_and_primary_roles_are_rejected(self):
        for code in ("admin", "unknown-role", "almacen"):
            with self.subTest(role=code), self.assertRaises(HTTPException):
                r_auth.add_user_additional_role(
                    self.warehouse.id, r_auth.AdditionalRoleIn(role_code=code), self.admin, self.session
                )
        self.assertNotIn("admin", [item["code"] for item in r_auth.available_roles(self.admin)])
        with self.assertRaises(HTTPException):
            r_auth.add_user_additional_role(
                self.admin.id, r_auth.AdditionalRoleIn(role_code="cajero"), self.admin, self.session
            )

    def test_only_primary_admin_can_manage_additional_roles(self):
        with self.assertRaises(HTTPException) as caught:
            r_auth.available_roles(self.warehouse)
        self.assertEqual(caught.exception.status_code, 403)
        with self.assertRaises(HTTPException):
            r_auth.add_user_additional_role(
                self.warehouse.id, r_auth.AdditionalRoleIn(role_code="cajero"), self.warehouse, self.session
            )

    def test_admin_always_has_all_permissions_and_no_additional_roles(self):
        self.assertEqual(get_effective_roles(self.admin), ["admin"])
        self.assertEqual(get_effective_permissions(self.admin), ["*"])
        self.assertTrue(allowed(self.admin, "any.future.permission"))
        self.assertEqual(r_auth.get_user_additional_roles(self.admin.id, self.admin, self.session)["additional_roles"], [])

    def test_sqlite_enforces_user_and_assigner_foreign_keys(self):
        with db.engine.connect() as connection:
            self.assertEqual(connection.exec_driver_sql("PRAGMA foreign_keys").scalar(), 1)
        self.session.add(db.UserAdditionalRole(
            user_id=self.warehouse.id, role_code="contador", assigned_by=999999,
        ))
        with self.assertRaises(IntegrityError):
            self.session.commit()
        self.session.rollback()

    def test_me_and_users_reflect_role_changes_without_relogin(self):
        r_auth.add_user_additional_role(
            self.warehouse.id, r_auth.AdditionalRoleIn(role_code="cajero"), self.admin, self.session
        )
        self.session.expire(self.warehouse, ["additional_role_links"])
        me = r_auth.me(self.warehouse)
        self.assertEqual(me["additional_roles"], ["cajero"])
        self.assertIn("sales.create", me["perms"])
        row = next(user for user in r_auth.users(self.admin, self.session) if user["id"] == self.warehouse.id)
        self.assertEqual(row["role"], "almacen")
        self.assertEqual(row["additional_roles"], ["cajero"])

    def test_remove_role_validates_assignment_and_preserves_primary(self):
        r_auth.add_user_additional_role(
            self.warehouse.id, r_auth.AdditionalRoleIn(role_code="cajero"), self.admin, self.session
        )
        result = r_auth.remove_user_additional_role(self.warehouse.id, "cajero", self.admin, self.session)
        self.assertEqual(result["role"], "almacen")
        self.assertEqual(result["additional_roles"], [])
        for code in ("admin", "unknown-role", "almacen"):
            with self.subTest(role=code), self.assertRaises(HTTPException):
                r_auth.remove_user_additional_role(self.warehouse.id, code, self.admin, self.session)
        with self.assertRaises(HTTPException) as caught:
            r_auth.remove_user_additional_role(self.warehouse.id, "cajero", self.admin, self.session)
        self.assertEqual(caught.exception.status_code, 404)

    def test_login_returns_single_account_with_current_roles(self):
        r_auth.add_user_additional_role(
            self.warehouse.id, r_auth.AdditionalRoleIn(role_code="cajero"), self.admin, self.session
        )
        response = r_auth.login(
            r_auth.LoginIn(username="warehouse-test", password="warehouse-pass"), self.session
        )
        self.assertTrue(response["token"])
        self.assertEqual(response["user"]["id"], self.warehouse.id)
        self.assertEqual(response["user"]["role"], "almacen")
        self.assertEqual(response["user"]["additional_roles"], ["cajero"])

    def test_backup_export_includes_additional_role_table(self):
        r_auth.add_user_additional_role(
            self.warehouse.id, r_auth.AdditionalRoleIn(role_code="cajero"), self.admin, self.session
        )
        backup = r_auth.download_backup(self.admin, self.session)
        self.assertIn("user_additional_roles", backup["tables"])
        self.assertEqual(len(backup["tables"]["user_additional_roles"]), 1)


class RoleMigrationTests(unittest.TestCase):
    def create_minimal_db(self, path):
        connection = sqlite3.connect(path)
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, role TEXT NOT NULL)")
        connection.execute("INSERT INTO users(id, role) VALUES (1, 'admin'), (2, 'almacen')")
        connection.commit()
        return connection

    def test_migration_is_additive_constrained_and_reversible_when_empty(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "migration-test.db"
            connection = self.create_minimal_db(path)
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertEqual(migrate_local_roles.upgrade(connection, tables), "applied")
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM users").fetchone()[0], 2)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM user_additional_roles").fetchone()[0], 0)
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "INSERT INTO user_additional_roles(user_id, role_code, assigned_by) VALUES (2, 'admin', 1)"
                )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "INSERT INTO user_additional_roles(user_id, role_code, assigned_by) VALUES (2, 'cajero', 1)"
                )
                connection.execute(
                    "INSERT INTO user_additional_roles(user_id, role_code, assigned_by) VALUES (2, 'cajero', 1)"
                )
            connection.rollback()
            updated_tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertEqual(migrate_local_roles.downgrade(connection, updated_tables), "reverted")
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM users").fetchone()[0], 2)
            connection.close()

    def test_migration_adopts_an_empty_table_created_by_create_all(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "adopt-empty.db"
            connection = self.create_minimal_db(path)
            connection.execute(
                "CREATE TABLE user_additional_roles "
                "(id INTEGER PRIMARY KEY, user_id INTEGER, role_code TEXT, assigned_by INTEGER, assigned_at DATETIME)"
            )
            connection.commit()
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertEqual(migrate_local_roles.upgrade(connection, tables), "applied")
            default_value = connection.execute("PRAGMA table_info(user_additional_roles)").fetchall()[4][4]
            self.assertEqual(default_value, "CURRENT_TIMESTAMP")
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM users").fetchone()[0], 2)
            connection.close()

    def test_migration_refuses_to_replace_untracked_role_assignments(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "adopt-nonempty.db"
            connection = self.create_minimal_db(path)
            connection.execute(
                "CREATE TABLE user_additional_roles "
                "(id INTEGER PRIMARY KEY, user_id INTEGER, role_code TEXT, assigned_by INTEGER, assigned_at DATETIME)"
            )
            connection.execute(
                "INSERT INTO user_additional_roles(user_id, role_code, assigned_by) VALUES (2, 'cajero', 1)"
            )
            connection.commit()
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            with self.assertRaises(RuntimeError):
                migrate_local_roles.upgrade(connection, tables)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM user_additional_roles").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM users").fetchone()[0], 2)
            connection.close()


if __name__ == "__main__":
    unittest.main()
