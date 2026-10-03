import json
import tempfile
import unittest
from pathlib import Path

from dbgpt_app.scene.chat_db.auto_execute.schema_hybrid_retriever import (
    INDEX_VERSION,
    SchemaHybridRetriever,
)


class SchemaHybridRetrieverTest(unittest.TestCase):
    def test_ranks_matching_table_and_persists_versioned_index(self):
        with tempfile.TemporaryDirectory() as directory:
            retriever = SchemaHybridRetriever(directory)
            infos = [
                ("orders(order_id,customer_id,total_amount)",),
                ("customers(customer_id,gender,region)",),
            ]
            selected, diagnostics = retriever.retrieve(
                "customers_db", "show customer gender by region", infos, top_k=1
            )
            self.assertEqual(selected, [infos[1]])
            self.assertEqual(diagnostics["schema_index_version"], INDEX_VERSION)
            self.assertEqual(diagnostics["schema_local_hybrid_cache_hit"], 0.0)
            index_path = Path(directory) / "customers_db.json"
            self.assertTrue(index_path.exists())
            self.assertEqual(json.loads(index_path.read_text(encoding="utf-8"))["index_version"], INDEX_VERSION)

            selected_again, diagnostics_again = retriever.retrieve(
                "customers_db", "show customer gender by region", infos, top_k=1
            )
            self.assertEqual(selected_again, [infos[1]])
            self.assertEqual(diagnostics_again["schema_local_hybrid_cache_hit"], 1.0)

    def test_empty_schema_is_safe(self):
        with tempfile.TemporaryDirectory() as directory:
            selected, diagnostics = SchemaHybridRetriever(directory).retrieve(
                "empty", "anything", [], top_k=4
            )
            self.assertEqual(selected, [])
            self.assertEqual(diagnostics["schema_local_hybrid_candidate_count"], 0.0)


if __name__ == "__main__":
    unittest.main()
