"""Build generic, versioned schema/semantic documents from SQLite databases.

The command is read-only against source databases.  It writes JSON documents
and a manifest to a caller-selected cache directory (the documented default
is on D: for this project), so it is safe to rerun after a schema change.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


INDEX_VERSION = "v9"


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _load_semantic_documents(semantic_dir: Path | None, database: str) -> List[Dict[str, Any]]:
    """Load optional operator-maintained metric/field definitions by database."""

    if semantic_dir is None:
        return []
    path = semantic_dir / f"{database}.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return []
    documents: List[Dict[str, Any]] = []
    for metric in payload.get("metrics", []) or []:
        if isinstance(metric, dict):
            documents.append(
                {
                    "id": f"metric:{metric.get('name', '')}",
                    "doc_type": "metric",
                    "text": " ".join(str(metric.get(key, "")) for key in ("name", "description", "expression", "aliases", "notes")),
                    "metric": metric,
                }
            )
    for field in payload.get("fields", []) or []:
        if isinstance(field, dict):
            documents.append(
                {
                    "id": f"semantic_field:{field.get('table', '')}.{field.get('column', '')}",
                    "doc_type": "semantic_field",
                    "text": " ".join(str(field.get(key, "")) for key in ("table", "column", "description", "aliases", "value_mapping", "notes")),
                    "semantic_field": field,
                }
            )
    return documents


def build_documents(db_path: Path, semantic_dir: Path | None = None) -> Dict[str, Any]:
    """Read table/column/relationship/value metadata without modifying SQLite."""

    documents: List[Dict[str, Any]] = []
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as connection:
        table_rows = connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        table_names = [str(row[0]) for row in table_rows]
        for table_name in table_names:
            quoted = '"' + table_name.replace('"', '""') + '"'
            columns = connection.execute(f"PRAGMA table_info({quoted})").fetchall()
            foreign_keys = connection.execute(f"PRAGMA foreign_key_list({quoted})").fetchall()
            column_names = [str(row[1]) for row in columns]
            sample_rows = connection.execute(f"SELECT * FROM {quoted} LIMIT 3").fetchall()
            sample_values = [
                {column_names[index]: _json_value(value) for index, value in enumerate(row)}
                for row in sample_rows
            ]
            table_text = (
                f"Table {table_name}; columns: "
                + ", ".join(f"{row[1]} ({row[2] or 'unknown'})" for row in columns)
            )
            documents.append(
                {
                    "id": f"table:{table_name}",
                    "doc_type": "table_schema",
                    "text": table_text,
                    "table_name": table_name,
                    "columns": [
                        {
                            "name": str(row[1]),
                            "type": str(row[2] or ""),
                            "nullable": not bool(row[3]),
                            "primary_key": bool(row[5]),
                        }
                        for row in columns
                    ],
                    "sample_values": sample_values,
                }
            )
            for row in columns:
                documents.append(
                    {
                        "id": f"column:{table_name}.{row[1]}",
                        "doc_type": "column",
                        "text": f"Column {table_name}.{row[1]} type {row[2] or 'unknown'}",
                        "table_name": table_name,
                        "column_name": str(row[1]),
                        "data_type": str(row[2] or ""),
                        "primary_key": bool(row[5]),
                    }
                )
            for row in foreign_keys:
                documents.append(
                    {
                        "id": f"relationship:{table_name}.{row[3]}->{row[2]}.{row[4]}",
                        "doc_type": "relationship",
                        "text": f"Relationship {table_name}.{row[3]} references {row[2]}.{row[4]}",
                        "source_table": table_name,
                        "source_column": str(row[3]),
                        "target_table": str(row[2]),
                        "target_column": str(row[4]),
                    }
                )

    documents.extend(_load_semantic_documents(semantic_dir, db_path.stem))
    canonical = json.dumps(documents, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return {
        "index_version": INDEX_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "database": db_path.stem,
        "source_path": str(db_path),
        "schema_hash": hashlib.sha256(canonical).hexdigest(),
        "table_count": len(table_names),
        "document_count": len(documents),
        "documents": documents,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--db-root",
        default=r"D:\1ALL\DB-GPT\datasets\bird_mini_dev\data\dev_databases",
        help="Directory containing SQLite databases (searched recursively).",
    )
    parser.add_argument(
        "--output",
        default=r"D:\1ALL\DB-GPT\requirement\dbgpt-home\schema_documents\v9",
        help="D:\\ cache directory for generated documents.",
    )
    parser.add_argument(
        "--semantic-dir",
        default=str(Path(__file__).resolve().parents[1] / "configs" / "semantics"),
        help="Optional directory of per-database metric/field JSON files.",
    )
    args = parser.parse_args()
    db_root = Path(args.db_root)
    output = Path(args.output)
    databases = sorted({*db_root.rglob("*.sqlite"), *db_root.rglob("*.db")})
    output.mkdir(parents=True, exist_ok=True)
    manifest: List[Dict[str, Any]] = []
    for db_path in databases:
        payload = build_documents(db_path, Path(args.semantic_dir) if args.semantic_dir else None)
        out_path = output / f"{db_path.parent.name}.json"
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        manifest.append(
            {
                "database": payload["database"],
                "file": str(out_path),
                "source_path": str(db_path),
                "table_count": payload["table_count"],
                "document_count": payload["document_count"],
                "schema_hash": payload["schema_hash"],
            }
        )
        print(f"{db_path.parent.name}: {payload['table_count']} tables, {payload['document_count']} docs")
    manifest_path = output / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "index_version": INDEX_VERSION,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "source_root": str(db_root),
                "database_count": len(manifest),
                "databases": manifest,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Wrote {len(manifest)} database documents to {output}")


if __name__ == "__main__":
    main()
