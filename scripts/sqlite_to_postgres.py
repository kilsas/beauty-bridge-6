"""
Export a database built by `python -m beautybridge build-db` as a PostgreSQL
script (schema + INSERT statements).

  python scripts/sqlite_to_postgres.py db/beautybridge.sqlite > db/postgres_load.sql
  psql "$DATABASE_URL" -f db/postgres_load.sql
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TABLES = [  # parents before children (foreign keys)
    "products", "beauty_goals", "goal_criteria", "market_products",
    "price_observations", "rankings", "company_financials", "company_events", "judgments",
]


def literal(v) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, (int, float)):
        return repr(v)
    return "'" + str(v).replace("'", "''") + "'"


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__, file=sys.stderr)
        return 1
    conn = sqlite3.connect(argv[0])
    out = sys.stdout
    out.write("BEGIN;\n")
    out.write((ROOT / "db" / "schema.sql").read_text(encoding="utf-8"))
    out.write("\n")
    for table in TABLES:
        cur = conn.execute(f"SELECT * FROM {table}")
        cols = [d[0] for d in cur.description]
        for row in cur:
            out.write(f"INSERT INTO {table} ({', '.join(cols)}) VALUES "
                      f"({', '.join(literal(v) for v in row)});\n")
    out.write("COMMIT;\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
