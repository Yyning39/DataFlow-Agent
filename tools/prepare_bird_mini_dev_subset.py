"""Create a deterministic, cross-domain BIRD Mini-Dev evaluation manifest.

The source JSON is public benchmark data. This script only selects records; it
does not rewrite questions, SQL, schema, or database contents.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--per-db", type=int, default=2)
    parser.add_argument("--db-ids", nargs="*", help="Optional public database IDs to include")
    args = parser.parse_args()

    root = Path(args.data_root)
    source = root / "mini_dev_sqlite.json"
    records = json.loads(source.read_text(encoding="utf-8"))
    by_db = {}
    for record in records:
        by_db.setdefault(record["db_id"], []).append(record)

    selected = []
    db_ids = sorted(args.db_ids) if args.db_ids else sorted(by_db)
    for db_id in db_ids:
        if db_id not in by_db:
            raise ValueError(f"Unknown database ID: {db_id}")
        rows = sorted(by_db[db_id], key=lambda item: int(item["question_id"]))
        # Keep the source ordering deterministic and prefer difficulty variety.
        chosen = []
        for difficulty in ("simple", "moderate", "challenging"):
            chosen.extend(row for row in rows if row.get("difficulty") == difficulty)
        chosen.extend(row for row in rows if row not in chosen)
        selected.extend(chosen[: args.per_db])

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "source": "BIRD-Mini-Dev SQLite",
        "source_file": str(source),
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "selection": {"per_db": args.per_db, "database_count": len(db_ids), "db_ids": db_ids},
        "cases": selected,
    }
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"cases={len(selected)} databases={len(by_db)}")
    print(f"manifest={output}")


if __name__ == "__main__":
    main()
