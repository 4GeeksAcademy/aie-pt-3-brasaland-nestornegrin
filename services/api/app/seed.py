import sys
from datetime import datetime, timezone

from tinydb import TinyDB

from .database import DATABASE_PATH
from .suppliers.seed import seed_suppliers


def main() -> int:
    try:
        database = TinyDB(DATABASE_PATH, indent=2)
        inserted = 0
        if len(database) == 0:
            suppliers = seed_suppliers()
            database.insert_multiple([
                {**supplier.model_dump(mode="json"), "updated_at": datetime.now(timezone.utc).isoformat()}
                for supplier in suppliers
            ])
            inserted = len(suppliers)
        database.close()
    except OSError as error:
        print(f"Error: no se pudo leer o escribir la base de datos de proveedores: {error}", file=sys.stderr)
        return 1
    print(f"Seeder completado: {inserted} proveedores insertados.")
    return 0