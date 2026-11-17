"""
Unit Tests for FastPathManager and Fast-Path Rules API
"""

import unittest
import tempfile
from pathlib import Path
from daemon.agent.fast_path_manager import FastPathManager, DEFAULT_SYSTEM_RULES


class TestFastPathManager(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.rules_file = Path(self.temp_dir.name) / "rules.json"
        self.mgr = FastPathManager(rules_path=self.rules_file)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_get_all_rules_defaults(self):
        rules = self.mgr.get_all_rules()
        self.assertGreater(len(rules), 0)
        # Verify system default rules exist
        sys_rules = [r for r in rules if r.get("is_system")]
        self.assertEqual(len(sys_rules), len(DEFAULT_SYSTEM_RULES))

    def test_add_and_delete_learned_rule(self):
        added = self.mgr.add_learned_rule(
            triggers=["test trigger phrase", "run test shortcut"],
            action_type="tool",
            tool="test_tool",
            args={"key": "val"},
            spoken_summary="Running test shortcut"
        )
        self.assertIsNotNone(added)
        self.assertIn("id", added)

        all_rules = self.mgr.get_all_rules()
        rule_ids = [r.get("id") for r in all_rules]
        self.assertIn(added["id"], rule_ids)

        # Delete rule
        deleted = self.mgr.delete_rule(added["id"])
        self.assertTrue(deleted)

        updated_rules = self.mgr.get_all_rules()
        updated_ids = [r.get("id") for r in updated_rules]
        self.assertNotIn(added["id"], updated_ids)


if __name__ == "__main__":
    unittest.main()
