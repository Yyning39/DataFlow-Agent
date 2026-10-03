import unittest

from dbgpt_app.scene.chat_db.auto_execute.access_policy import SqlAccessPolicy


class AccessPolicyTest(unittest.TestCase):
    def test_datasource_allowlist(self):
        policy = SqlAccessPolicy(allowed_datasources=frozenset({"orders"}))
        policy.check("orders", "SELECT total FROM orders")
        with self.assertRaises(PermissionError):
            policy.check("customers", "SELECT total FROM customers")

    def test_denied_column(self):
        policy = SqlAccessPolicy(denied_columns=frozenset({"salary"}))
        with self.assertRaises(PermissionError):
            policy.check("employees", "SELECT name, salary FROM employees")


if __name__ == "__main__":
    unittest.main()
