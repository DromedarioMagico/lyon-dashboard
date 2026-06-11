"""
Export lyon.db to SQL INSERTs for Supabase migration.

Usage:
    python scripts/export_db.py > migration.sql

Then paste migration.sql into the Supabase SQL Editor and run it.
"""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "lyon.db"


def _q(s):
    """Escape single quotes for SQL literals."""
    return (s or "").replace("'", "''")


def main():
    if not DB_PATH.exists():
        print("-- data/lyon.db not found — nothing to migrate.")
        return

    con = sqlite3.connect(DB_PATH)
    print("-- Lyon AG — catalog export for Supabase")
    print("-- Paste this in the Supabase SQL Editor and click Run")
    print()

    # ── proveedores_clasificacion ─────────────────────────────────────────────
    rows = con.execute(
        "SELECT proveedor_exacto_sae, categoria, notas, origen "
        "FROM proveedores_clasificacion"
    ).fetchall()
    if rows:
        print(f"-- {len(rows)} proveedores clasificados")
        for prov, cat, notas, origen in rows:
            print(
                f"INSERT INTO proveedores_clasificacion "
                f"(proveedor_exacto_sae, categoria, notas, origen) "
                f"VALUES ('{_q(prov)}', '{_q(cat)}', '{_q(notas)}', '{_q(origen)}') "
                f"ON CONFLICT (proveedor_exacto_sae) DO UPDATE SET "
                f"categoria=EXCLUDED.categoria, notas=EXCLUDED.notas, "
                f"origen=EXCLUDED.origen;"
            )
        print()

    # ── vendedor_cliente ──────────────────────────────────────────────────────
    rows = con.execute(
        "SELECT cliente_exacto_sae, vendedor, origen FROM vendedor_cliente"
    ).fetchall()
    if rows:
        print(f"-- {len(rows)} asignaciones vendedor→cliente")
        for cli, vend, origen in rows:
            print(
                f"INSERT INTO vendedor_cliente "
                f"(cliente_exacto_sae, vendedor, origen) "
                f"VALUES ('{_q(cli)}', '{_q(vend)}', '{_q(origen)}') "
                f"ON CONFLICT (cliente_exacto_sae) DO UPDATE SET "
                f"vendedor=EXCLUDED.vendedor, origen=EXCLUDED.origen;"
            )
        print()

    con.close()
    print("-- Done")


if __name__ == "__main__":
    main()
