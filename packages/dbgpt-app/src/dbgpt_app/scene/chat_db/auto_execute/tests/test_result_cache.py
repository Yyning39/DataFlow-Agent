import unittest

from dbgpt_app.scene.chat_db.auto_execute.result_cache import SqlResultCache


class ResultCacheTest(unittest.TestCase):
    def test_ttl_lru_and_scope(self):
        cache = SqlResultCache(ttl_seconds=60, max_entries=1)
        cache.set("db", "select 1", [{"value": 1}], scope="alice")
        self.assertEqual(cache.get("db", "select 1", scope="alice"), [{"value": 1}])
        self.assertIsNone(cache.get("db", "select 1", scope="bob"))
        cache.set("db", "select 2", [{"value": 2}], scope="alice")
        self.assertIsNone(cache.get("db", "select 1", scope="alice"))

    def test_disabled_cache_is_a_noop(self):
        cache = SqlResultCache(ttl_seconds=0, max_entries=1)
        cache.set("db", "select 1", [{"value": 1}])
        self.assertIsNone(cache.get("db", "select 1"))


if __name__ == "__main__":
    unittest.main()
