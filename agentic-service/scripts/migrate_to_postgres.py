"""SQLite to PostgreSQL migration script (#28).

Usage:
    python scripts/migrate_to_postgres.py --source dev.db --target "postgresql+asyncpg://user:pass@localhost/tevet7"

Copies all tables from SQLite to PostgreSQL. Run once when upgrading from
dev (SQLite) to production (PostgreSQL).
"""
import argparse
import asyncio
import sqlite3
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

async def migrate(source_db: str, target_url: str):
    sqlite_conn = sqlite3.connect(source_db)
    sqlite_conn.row_factory = sqlite3.Row
    pg_engine = create_async_engine(target_url)
    tables = [r[0] for r in sqlite_conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%%' AND name NOT LIKE '%%_fts'"
    )]
    print(f"Found {len(tables)} tables: {', '.join(tables)}")
    async with pg_engine.begin() as pg_conn:
        for table in tables:
            rows = sqlite_conn.execute(f"SELECT * FROM {table}").fetchall()
            if not rows:
                print(f"  {table}: 0 rows (skipped)")
                continue
            columns = rows[0].keys()
            col_str = ", ".join(columns)
            param_str = ", ".join(f":{c}" for c in columns)
            for row in rows:
                data = {c: row[c] for c in columns}
                try:
                    await pg_conn.execute(
                        text(f'INSERT INTO {table} ({col_str}) VALUES ({param_str}) ON CONFLICT DO NOTHING'),
                        data
                    )
                except Exception as e:
                    print(f"  {table}: error inserting row: {e}")
            print(f"  {table}: {len(rows)} rows migrated")
    sqlite_conn.close()
    await pg_engine.dispose()
    print("Migration complete!")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default="dev.db")
    parser.add_argument("--target", required=True)
    args = parser.parse_args()
    asyncio.run(migrate(args.source, args.target))
