"""Create the first Stock Up administrator from environment variables.

Run this once after configuring the production database. It never overwrites
an existing user and it does not contain a default username or password.
"""

import os
import sys

from db import Base, SessionLocal, User, engine, hash_password


def main() -> int:
    Base.metadata.create_all(engine)
    username = os.getenv("STOCKUP_ADMIN_USERNAME", "").strip()
    password = os.getenv("STOCKUP_ADMIN_PASSWORD", "")
    full_name = os.getenv("STOCKUP_ADMIN_FULL_NAME", "Administrador General").strip()

    if not username or not password:
        print("Configura STOCKUP_ADMIN_USERNAME y STOCKUP_ADMIN_PASSWORD en el servidor.", file=sys.stderr)
        return 2
    if len(password) < 12:
        print("STOCKUP_ADMIN_PASSWORD debe tener al menos 12 caracteres.", file=sys.stderr)
        return 2
    if not full_name:
        print("STOCKUP_ADMIN_FULL_NAME no puede estar vacío.", file=sys.stderr)
        return 2

    with SessionLocal() as db:
        if db.query(User.id).first() is not None:
            print("Ya existen usuarios; no se realizaron cambios.")
            return 0
        db.add(User(
            username=username,
            full_name=full_name,
            password_hash=hash_password(password),
            role="admin",
            active=True,
        ))
        db.commit()

    print("Administrador inicial creado. Elimina STOCKUP_ADMIN_PASSWORD de las variables de ejecución si tu proveedor lo permite.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
