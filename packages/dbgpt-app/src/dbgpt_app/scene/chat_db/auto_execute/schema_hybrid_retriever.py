"""Small, dependency-free schema retriever used by the DB chat path.

The built-in Chroma path depends on a working embedding endpoint.  In a
development or offline environment that endpoint can be unavailable even
though the database schema is available locally.  This module keeps a
versioned, deterministic index on disk and combines lexical overlap with a
hashing-vector cosine score.  It is deliberately independent of any
benchmark question or database name and acts as a safe fallback (and a
repeatable baseline for measuring a future embedding backend).
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


INDEX_VERSION = "v9"
DEFAULT_DIMENSION = 256
_TOKEN_RE = re.compile(r"[A-Za-z0-9_\u4e00-\u9fff]+")


def _tokens(text: str) -> List[str]:
    """Tokenize identifiers and Chinese/English text deterministically."""

    result: List[str] = []
    for raw in _TOKEN_RE.findall(str(text or "")):
        token = raw.casefold()
        if not token:
            continue
        result.append(token)
        # Make snake_case and dotted identifiers searchable by their parts.
        for part in re.split(r"[_\.\-]+", token):
            if part and part != token:
                result.append(part)
    return result


def _vector(tokens: Iterable[str], dimension: int = DEFAULT_DIMENSION) -> List[float]:
    values = [0.0] * dimension
    for token in tokens:
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        index = int.from_bytes(digest[:4], "big") % dimension
        sign = 1.0 if digest[4] & 1 else -1.0
        values[index] += sign
    norm = math.sqrt(sum(value * value for value in values))
    if norm:
        values = [value / norm for value in values]
    return values


def _cosine(left: List[float], right: List[float]) -> float:
    return max(0.0, min(1.0, sum(a * b for a, b in zip(left, right))))


def _table_name_and_columns(table_info: Any) -> Tuple[Optional[str], List[str]]:
    raw = table_info[0] if isinstance(table_info, (tuple, list)) and table_info else table_info
    text = str(raw)
    match = re.match(r"\s*[`\"\[]?([\w.-]+)[`\"\]]?\s*\((.*?)\)\s*;?\s*$", text)
    if not match:
        return None, []
    columns = [item.strip().strip('`"[]') for item in match.group(2).split(",")]
    return match.group(1), [item for item in columns if re.match(r"^[\w.-]+$", item)]


class SchemaHybridRetriever:
    """Persistent local schema index with lexical + hashing-vector retrieval."""

    def __init__(self, index_dir: Optional[str] = None, dimension: int = DEFAULT_DIMENSION):
        configured = index_dir or os.getenv("DBGPT_SCHEMA_INDEX_DIR")
        if configured:
            self.index_dir = Path(configured)
        else:
            # Keep generated state outside the source checkout when DBGPT_HOME
            # is configured, while remaining usable in a normal source run.
            home = os.getenv("DBGPT_HOME")
            self.index_dir = Path(home or ".") / "schema_index" / INDEX_VERSION
        self.dimension = max(32, int(dimension))

    @staticmethod
    def _safe_name(db_name: str) -> str:
        return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(db_name or "database"))[:180]

    @staticmethod
    def _normalise_infos(table_infos: Iterable[Any]) -> List[Dict[str, Any]]:
        documents: List[Dict[str, Any]] = []
        for index, info in enumerate(table_infos or []):
            table_name, columns = _table_name_and_columns(info)
            if not table_name:
                continue
            content = str(info[0] if isinstance(info, (tuple, list)) and info else info)
            documents.append(
                {
                    "id": str(table_name),
                    "table_name": str(table_name),
                    "columns": columns,
                    "content": content,
                    "source_order": index,
                }
            )
        return documents

    def _schema_hash(self, documents: List[Dict[str, Any]]) -> str:
        encoded = json.dumps(documents, ensure_ascii=False, sort_keys=True).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _load_or_build(self, db_name: str, table_infos: Iterable[Any]) -> Tuple[List[Dict[str, Any]], bool]:
        documents = self._normalise_infos(table_infos)
        digest = self._schema_hash(documents)
        path = self.index_dir / f"{self._safe_name(db_name)}.json"
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
            if (
                cached.get("index_version") == INDEX_VERSION
                and cached.get("schema_hash") == digest
                and isinstance(cached.get("documents"), list)
            ):
                return cached["documents"], True
        except (OSError, ValueError, TypeError):
            pass

        for document in documents:
            document["tokens"] = _tokens(
                " ".join([document["table_name"], *document["columns"], document["content"]])
            )
            document["vector"] = _vector(document["tokens"], self.dimension)
        payload = {
            "index_version": INDEX_VERSION,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "db_name": str(db_name),
            "schema_hash": digest,
            "dimension": self.dimension,
            "documents": documents,
        }
        try:
            self.index_dir.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(path.suffix + ".tmp")
            temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            os.replace(temporary, path)
        except OSError:
            # Retrieval remains available if the configured cache directory is
            # read-only; persistence is an optimisation, not a prerequisite.
            pass
        return documents, False

    def retrieve(self, db_name: str, question: str, table_infos: Iterable[Any], top_k: int = 4) -> Tuple[List[Any], Dict[str, Any]]:
        """Return table infos ranked by hybrid score and diagnostic metadata."""

        started = time.perf_counter()
        original = list(table_infos or [])
        documents, cache_hit = self._load_or_build(db_name, original)
        query_tokens = _tokens(question)
        query_set = set(query_tokens)
        query_vector = _vector(query_tokens, self.dimension)
        ranked: List[Tuple[float, float, float, int, Dict[str, Any]]] = []
        for document in documents:
            doc_tokens = set(document.get("tokens") or _tokens(document.get("content", "")))
            lexical = len(query_set & doc_tokens) / max(1, len(query_set))
            table_name = str(document.get("table_name", ""))
            if table_name.casefold() in query_set:
                lexical = min(1.0, lexical + 0.35)
            vector_score = _cosine(query_vector, list(document.get("vector") or []))
            score = 0.7 * lexical + 0.3 * vector_score
            ranked.append((score, lexical, vector_score, int(document.get("source_order", 0)), document))
        ranked.sort(key=lambda item: (-item[0], -item[1], item[3]))
        limit = max(1, int(top_k or len(original))) if original else 0
        by_name = {str(_table_name_and_columns(info)[0] or "").casefold(): info for info in original}
        selected = [by_name.get(str(item[4].get("table_name", "")).casefold()) for item in ranked[:limit]]
        selected = [item for item in selected if item is not None]
        best = ranked[0] if ranked else None
        diagnostics = {
            "schema_local_hybrid_used": float(bool(selected)),
            "schema_local_hybrid_cache_hit": float(cache_hit),
            "schema_local_hybrid_candidate_count": float(len(selected)),
            "schema_local_hybrid_top_score": round(float(best[0]), 4) if best else 0.0,
            "schema_local_hybrid_seconds": round(time.perf_counter() - started, 4),
            "schema_index_version": INDEX_VERSION,
            "schema_retrieval_source": "local_hybrid",
        }
        return selected, diagnostics

