import sqlite3
from pathlib import Path

DB = "Database_NEW_V2.db"
OUT = "schema.sql"

conn = sqlite3.connect(DB)
cur = conn.cursor()

rows = cur.execute("""
SELECT type, name, tbl_name, sql
FROM sqlite_master
WHERE sql IS NOT NULL
  AND name NOT LIKE 'sqlite_%'
ORDER BY
  CASE type
    WHEN 'table' THEN 1
    WHEN 'index' THEN 2
    WHEN 'trigger' THEN 3
    WHEN 'view' THEN 4
    ELSE 5
  END,
  name;
""").fetchall()

out = []
for t, name, tbl, sql in rows:
    out.append(f"-- {t.upper()} {name}")
    out.append(sql.strip() + ";")
    out.append("")

Path(OUT).write_text("\n".join(out), encoding="utf-8")

print(f"[OK] schema dumped to {OUT}")
