import os
import unittest
from unittest.mock import patch

from dbgpt_app.scene.chat_db.auto_execute.model_router import choose_model


class ModelRouterTest(unittest.TestCase):
    def test_disabled_keeps_requested_model(self):
        with patch.dict(os.environ, {"DBGPT_MODEL_ROUTING": "false"}, clear=False):
            self.assertEqual(choose_model("How many rows?", "model-a"), ("model-a", "routing_disabled"))

    def test_simple_question_uses_fast_tier(self):
        env = {
            "DBGPT_MODEL_ROUTING": "true",
            "DBGPT_FAST_MODEL": "fast-model",
            "DBGPT_ACCURATE_MODEL": "accurate-model",
        }
        with patch.dict(os.environ, env, clear=False):
            self.assertEqual(choose_model("How many customers?", "accurate-model"), ("fast-model", "simple_query_fast_tier"))

    def test_join_question_uses_accurate_tier(self):
        env = {
            "DBGPT_MODEL_ROUTING": "true",
            "DBGPT_FAST_MODEL": "fast-model",
            "DBGPT_ACCURATE_MODEL": "accurate-model",
        }
        with patch.dict(os.environ, env, clear=False):
            self.assertEqual(choose_model("Compare sales JOIN customers GROUP BY region", "fast-model"), ("accurate-model", "complex_query_accurate_tier"))


if __name__ == "__main__":
    unittest.main()
