#!/usr/bin/env python3
"""Explicit, disposable SQLite teaching demo. This is never called by the scanner."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sqlite3


def setup(database: Path) -> dict:
    if database.exists():
        raise ValueError("Database already exists; choose a new --database path.")
    database.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database) as conn:
        conn.execute("CREATE TABLE raw_orders (order_id INTEGER PRIMARY KEY, amount_cents INTEGER NOT NULL)")
        conn.executemany("INSERT INTO raw_orders VALUES (?, ?)", [(1, 1000), (2, 2000), (3, -500)])
    return {"database": str(database), "stage": "setup", "raw_rows": 3, "synthetic": True}


def run(database: Path) -> dict:
    if not database.is_file():
        raise ValueError("Run setup first.")
    with sqlite3.connect(database) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS transformed_orders (order_id INTEGER PRIMARY KEY, amount REAL NOT NULL)")
        conn.execute("CREATE TABLE IF NOT EXISTS final_orders (order_count INTEGER NOT NULL, total_amount REAL NOT NULL)")
        conn.execute("DELETE FROM transformed_orders")
        conn.execute("INSERT INTO transformed_orders SELECT order_id, amount_cents / 100.0 FROM raw_orders WHERE amount_cents >= 0")
        conn.execute("DELETE FROM final_orders")
        conn.execute("INSERT INTO final_orders SELECT COUNT(*), COALESCE(SUM(amount), 0) FROM transformed_orders")
        count, total = conn.execute("SELECT order_count, total_amount FROM final_orders").fetchone()
    return {"database": str(database), "stage": "run", "final_order_count": count, "final_total_amount": total, "synthetic": True}


def inspect(database: Path, export: Path | None = None) -> dict:
    if not database.is_file():
        raise ValueError("Run setup first.")
    result = {"database": str(database), "synthetic": True, "tables": {}}
    uri = database.resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as conn:
        for table in ("raw_orders", "transformed_orders", "final_orders"):
            exists = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
            if not exists:
                result["tables"][table] = {"status": "not created"}
                continue
            cursor = conn.execute('SELECT * FROM "' + table + '"')
            columns = [column[0] for column in cursor.description]
            rows = cursor.fetchall()
            result["tables"][table] = {"columns": columns, "rows": rows}
            if export:
                export.mkdir(parents=True, exist_ok=True)
                with (export / (table + ".csv")).open("w", newline="", encoding="utf-8") as handle:
                    writer = csv.writer(handle)
                    writer.writerow(columns)
                    writer.writerows(rows)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("setup", "run", "inspect"))
    parser.add_argument("--database", type=Path, default=Path(".demo-data/orders.sqlite"))
    parser.add_argument("--export", type=Path, help="For inspect only: explicitly export synthetic rows as CSV")
    args = parser.parse_args()
    try:
        result = {"setup": setup, "run": run}.get(args.command, lambda path: inspect(path, args.export))(args.database)
    except (ValueError, sqlite3.Error, OSError) as error:
        parser.exit(2, str(error) + "\n")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
