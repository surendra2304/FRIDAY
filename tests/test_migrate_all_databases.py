import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path
import json

from scripts.migrate_all_databases import (
    SCHEMAS,
    get_schema_ddl,
    migrate_databases,
)

EXPECTED_DBS = [
    "friday_db",
    "inference_db",
    "memora_db",
    "stratex_db",
    "forge_db",
    "cortex_db",
    "sentinel_db",
    "intelx_db",
    "futuris_db",
    "vyralx_db",
]

class TestMigrateAllDatabases(unittest.TestCase):
    def test_all_10_databases_present(self):
        """Verify all 10 databases are defined in the migration suite."""
        self.assertEqual(sorted(list(SCHEMAS.keys())), sorted(EXPECTED_DBS))

    def test_schema_ddl_validity(self):
        """Verify each database schema contains CREATE TABLE IF NOT EXISTS statements."""
        for db_name in EXPECTED_DBS:
            ddl = get_schema_ddl(db_name)
            self.assertIsInstance(ddl, str)
            self.assertIn("CREATE TABLE IF NOT EXISTS", ddl, f"{db_name} missing CREATE TABLE")

    def test_get_schema_ddl_unknown_db_raises(self):
        """Verify unknown database name raises KeyError."""
        with self.assertRaises(KeyError):
            get_schema_ddl("nonexistent_db")

    def test_specific_tables_exist_in_schemas(self):
        """Verify core tables exist in respective schemas."""
        self.assertIn("conversations", get_schema_ddl("friday_db"))
        self.assertIn("task_checkpoints", get_schema_ddl("friday_db"))
        
        self.assertIn("agents", get_schema_ddl("inference_db"))
        self.assertIn("runs", get_schema_ddl("inference_db"))
        
        self.assertIn("memory_records", get_schema_ddl("memora_db"))
        self.assertIn("namespaces", get_schema_ddl("memora_db"))
        self.assertIn("deletion_tombstones", get_schema_ddl("memora_db"))
        
        self.assertIn("order_intents", get_schema_ddl("stratex_db"))
        self.assertIn("portfolio_equity_state", get_schema_ddl("stratex_db"))
        
        self.assertIn("projects", get_schema_ddl("forge_db"))
        self.assertIn("task_graphs", get_schema_ddl("forge_db"))
        
        self.assertIn("sessions", get_schema_ddl("cortex_db"))
        self.assertIn("events", get_schema_ddl("cortex_db"))
        
        self.assertIn("sentinel_targets", get_schema_ddl("sentinel_db"))
        self.assertIn("sentinel_tasks", get_schema_ddl("sentinel_db"))
        
        self.assertIn("research_runs", get_schema_ddl("intelx_db"))
        self.assertIn("claims", get_schema_ddl("intelx_db"))
        
        self.assertIn("forecasts", get_schema_ddl("futuris_db"))
        self.assertIn("scenarios", get_schema_ddl("futuris_db"))
        
        self.assertIn("video_projects", get_schema_ddl("vyralx_db"))
        self.assertIn("agent_tasks", get_schema_ddl("vyralx_db"))

    @patch("scripts.migrate_all_databases.run_remote_python")
    def test_migrate_databases_calls_remote(self, mock_run_remote):
        """Verify migrate_databases executes remote script and returns output."""
        mock_run_remote.return_value = 'MIGRATION SUMMARY JSON:\n{"friday_db": {"status": "SUCCESS"}}'
        result = migrate_databases({"friday_db": "CREATE TABLE IF NOT EXISTS test (id INT);"})
        self.assertTrue(mock_run_remote.called)
        self.assertIn("MIGRATION SUMMARY", result)

if __name__ == "__main__":
    unittest.main()
