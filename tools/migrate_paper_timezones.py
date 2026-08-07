"""One-off migration: convert Beijing-time naive timestamps in SQLite to UTC.

Background: the old paper_repository stored aware datetimes directly and
SQLAlchemy stripped the timezone when writing to SQLite. Quote event times
(Asia/Shanghai) from mark_to_market were mixed with UTC timestamps from
set_cash_balance, breaking string ordering of as_of and making on_quotes skip
every new quote so holdings never refreshed.

Rule: naive values inside the A-share session (09:00-15:30 Beijing) with zero
microseconds come from mark_to_market (Eastmoney created_at is whole-second);
datetime.now(UTC) values carry microseconds. Idempotent: converted rows no
longer match the session-time rule.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

_STATE_DB = Path(__file__).resolve().parents[1] / ".astraquant" / "state" / "astraquant.sqlite3"

_TABLES = (
    ("paper_positions", "marked_at"),
    ("paper_equity_snapshots", "as_of"),
    ("paper_orders", "submitted_at"),
    ("paper_orders", "updated_at"),
    ("paper_fills", "occurred_at"),
)


def migrate(database: Path) -> int:
    con = sqlite3.connect(database)
    try:
        con.execute("PRAGMA foreign_keys = ON")
        updated = 0
        for table, column in _TABLES:
            rows = con.execute(
                f"SELECT rowid, {column} FROM {table} WHERE {column} IS NOT NULL"
            ).fetchall()
            for rowid, value in rows:
                text = str(value)
                if "." not in text:
                    continue
                time_part, micros = text.split(" ", 1)[1], text.rsplit(".", 1)[1]
                if micros != "000000":
                    continue
                if not ("09:00" <= time_part[:5] <= "15:30"):
                    continue
                con.execute(
                    f"UPDATE {table} SET {column} = datetime({column}, '-8 hours') WHERE rowid = ?",
                    (rowid,),
                )
                updated += 1
                print(f"converted {table}.{column} {text!r} -> -8h")
        con.commit()
        return updated
    finally:
        con.close()


if __name__ == "__main__":
    database = Path(sys.argv[1]) if len(sys.argv) > 1 else _STATE_DB
    if not database.exists():
        print(f"database not found: {database}")
        raise SystemExit(1)
    count = migrate(database)
    print(f"migrated {count} row(s)")
