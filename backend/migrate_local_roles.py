"""Apply the additional-role schema migration to the local development SQLite DB only."""

import argparse
import sqlite3
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parent
DATABASE_PATH = BACKEND_DIR / "stockup-local.db"
MIGRATION_PATH = BACKEND_DIR / "migrations" / "001_user_additional_roles.sql"
MIGRATION_VERSION = "001_user_additional_roles"
HISTORICAL_TABLES = (
    "users", "sales", "sale_items", "audit_log", "cash_sessions", "cash_incomes",
    "stock_movements", "products", "purchases", "purchase_items", "purchase_payments",
)


def open_verified_local_db():
    if not DATABASE_PATH.is_file():
        raise RuntimeError("No se encontró backend/stockup-local.db; no se creó ninguna base nueva.")
    with DATABASE_PATH.open("rb") as db_file:
        if db_file.read(16) != b"SQLite format 3\x00":
            raise RuntimeError("El destino no tiene cabecera SQLite; migración cancelada.")
    connection = sqlite3.connect(str(DATABASE_PATH), timeout=10)
    connection.execute("PRAGMA foreign_keys = ON")
    integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    if integrity != "ok":
        connection.close()
        raise RuntimeError("La comprobación de integridad SQLite falló; migración cancelada.")
    tables = {row[0] for row in connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    if "users" not in tables:
        connection.close()
        raise RuntimeError("La base no contiene la tabla users; migración cancelada.")
    return connection, tables


def row_counts(connection, tables):
    return {
        table: connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
        for table in HISTORICAL_TABLES if table in tables
    }


def upgrade(connection, tables):
    if "schema_migrations" in tables:
        applied = connection.execute(
            "SELECT 1 FROM schema_migrations WHERE version=?", (MIGRATION_VERSION,)
        ).fetchone()
    else:
        applied = None
    has_roles_table = "user_additional_roles" in tables
    if applied and has_roles_table:
        return "already-applied"
    if applied:
        raise RuntimeError("El esquema está incompleto o fue creado fuera de la migración; no se modificó.")
    adopt_empty_table = False
    if has_roles_table:
        role_rows = connection.execute("SELECT COUNT(*) FROM user_additional_roles").fetchone()[0]
        if role_rows:
            raise RuntimeError("La tabla existente contiene asignaciones sin registrar; no se modificó.")
        adopt_empty_table = True

    before = row_counts(connection, tables)
    connection.execute("BEGIN IMMEDIATE")
    try:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(version TEXT PRIMARY KEY, applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)"
        )
        if adopt_empty_table:
            connection.execute("DROP TABLE user_additional_roles")
        ddl = MIGRATION_PATH.read_text(encoding="utf-8").strip()
        connection.execute(ddl)
        connection.execute("INSERT INTO schema_migrations(version) VALUES (?)", (MIGRATION_VERSION,))
        current_tables = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        if row_counts(connection, current_tables) != before:
            raise RuntimeError("La migración cambió conteos históricos; se revertirá la transacción.")
        fk_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
        if fk_errors:
            raise RuntimeError("La migración produjo referencias inválidas; se revertirá la transacción.")
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    return "applied"


def downgrade(connection, tables):
    if "user_additional_roles" not in tables or "schema_migrations" not in tables:
        return "not-applied"
    applied = connection.execute(
        "SELECT 1 FROM schema_migrations WHERE version=?", (MIGRATION_VERSION,)
    ).fetchone()
    if not applied:
        raise RuntimeError("La tabla no está registrada como migrada; no se modificó.")
    assigned_count = connection.execute("SELECT COUNT(*) FROM user_additional_roles").fetchone()[0]
    if assigned_count:
        raise RuntimeError("Hay roles adicionales asignados; exporta esas asignaciones antes de revertir.")
    connection.execute("BEGIN IMMEDIATE")
    try:
        connection.execute("DROP TABLE user_additional_roles")
        connection.execute("DELETE FROM schema_migrations WHERE version=?", (MIGRATION_VERSION,))
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    return "reverted"


def main():
    parser = argparse.ArgumentParser(description="Migración local de roles adicionales (SQLite de desarrollo).")
    parser.add_argument("action", choices=("upgrade", "downgrade"))
    args = parser.parse_args()
    connection, tables = open_verified_local_db()
    try:
        result = upgrade(connection, tables) if args.action == "upgrade" else downgrade(connection, tables)
        print(f"{MIGRATION_VERSION}: {result} en backend/stockup-local.db")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
