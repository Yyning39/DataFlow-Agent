"""Offline smoke test for the public multi-database evaluation fixtures."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--manifest", required=True)
    args = parser.parse_args()
    root = Path(args.data_root)
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    checked = 0
    databases = set()
    for case in manifest["cases"]:
        db_id = case["db_id"]
        path = root / "dev_databases" / db_id / f"{db_id}.sqlite"
        with sqlite3.connect(path) as connection:
            connection.execute(case["SQL"]).fetchall()
        databases.add(db_id)
        checked += 1
    print(f"databases={len(databases)} cases={checked} multisource_smoke=ok")


if __name__ == "__main__":
    main()
