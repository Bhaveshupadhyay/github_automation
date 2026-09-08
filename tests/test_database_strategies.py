"""Unit tests for pluggable database strategies."""
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from automation.domain.database_strategy import (
    DatabaseConfig,
    DatabaseStrategyType,
)
from automation.services.database_strategies import (
    DevCloudDatabaseStrategy,
    EphemeralRunnerDatabaseStrategy,
    create_database_strategy,
)


class TestDatabaseStrategies(unittest.TestCase):
    """Verifies isolation, connection environment generation, and migration execution."""

    def test_dev_cloud_strategy_connection_env(self) -> None:
        """Dev cloud strategy injects isolated tenant and test user email."""
        strategy = DevCloudDatabaseStrategy(
            connection_string="postgres://cloud-user:secret@dev-db.internal:5432/app_dev",
            test_user_email="custom-runner@domain.com",
            isolated_tenant=True,
            extra_env={"CUSTOM_KEY": "CUSTOM_VAL"},
        )
        env = strategy.get_connection_env()

        self.assertEqual(env["QA_ISOLATED_TENANT"], "true")
        self.assertEqual(env["QA_TEST_USER_EMAIL"], "custom-runner@domain.com")
        self.assertEqual(
            env["DATABASE_URL"],
            "postgres://cloud-user:secret@dev-db.internal:5432/app_dev",
        )
        self.assertEqual(env["CUSTOM_KEY"], "CUSTOM_VAL")

    def test_dev_cloud_strategy_skips_destructive_migrations_by_default(self) -> None:
        """Destructive migrations are skipped by default in dev cloud mode to prevent data loss."""
        strategy = DevCloudDatabaseStrategy()
        result = strategy.run_migrations(repo_dir=Path.cwd(), env={})

        self.assertTrue(result.success)
        self.assertEqual(result.command, "noop")
        self.assertEqual(result.exit_code, 0)
        self.assertIn("skipping destructive migrations", result.output)
        self.assertEqual(result.duration_seconds, 0.0)

    def test_dev_cloud_strategy_executes_explicit_migration_command(self) -> None:
        """When an explicit migration command is specified, it executes with env injected."""
        strategy = DevCloudDatabaseStrategy()
        result = strategy.run_migrations(
            repo_dir=Path.cwd(),
            env={"MIGRATION_FLAG": "1"},
            migration_command="python -c 'import os; print(\"Flag: \" + os.environ.get(\"MIGRATION_FLAG\", \"\"))'",
        )

        self.assertTrue(result.success)
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Flag: 1", result.output)
        self.assertGreaterEqual(result.duration_seconds, 0.0)

    def test_dev_cloud_strategy_handles_migration_failure(self) -> None:
        """Failing migration commands return success=False and capture error output."""
        strategy = DevCloudDatabaseStrategy()
        result = strategy.run_migrations(
            repo_dir=Path.cwd(),
            env={},
            migration_command="python -c 'import sys; sys.stderr.write(\"Migration schema mismatch\\n\"); sys.exit(2)'",
        )

        self.assertFalse(result.success)
        self.assertEqual(result.exit_code, 2)
        self.assertIn("Migration schema mismatch", result.output)

    @patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="alembic upgrade", timeout=120))
    def test_dev_cloud_strategy_migration_timeout(self, mock_run) -> None:
        """Migration commands that exceed timeout are cleanly aborted."""
        strategy = DevCloudDatabaseStrategy()
        result = strategy.run_migrations(
            repo_dir=Path.cwd(),
            env={},
            migration_command="alembic upgrade head",
        )

        self.assertFalse(result.success)
        self.assertEqual(result.exit_code, -1)
        self.assertIn("timed out after 120 seconds", result.output)

    def test_ephemeral_runner_strategy_connection_env_with_password(self) -> None:
        """Ephemeral runner strategy constructs connection string and standard PG env variables."""
        strategy = EphemeralRunnerDatabaseStrategy(
            host="127.0.0.1",
            port=5433,
            database_name="qa_test_db",
            username="test_admin",
            password="test_password",
        )
        env = strategy.get_connection_env()

        self.assertEqual(
            env["DATABASE_URL"],
            "postgresql://test_admin:test_password@127.0.0.1:5433/qa_test_db",
        )
        self.assertEqual(env["PGHOST"], "127.0.0.1")
        self.assertEqual(env["PGPORT"], "5433")
        self.assertEqual(env["PGDATABASE"], "qa_test_db")
        self.assertEqual(env["PGUSER"], "test_admin")
        self.assertEqual(env["PGPASSWORD"], "test_password")

    def test_ephemeral_runner_strategy_connection_env_without_password(self) -> None:
        """Without password, connection string omits password colon."""
        strategy = EphemeralRunnerDatabaseStrategy(
            host="localhost",
            port=5432,
            database_name="postgres",
            username="postgres",
            password=None,
        )
        env = strategy.get_connection_env()

        self.assertEqual(
            env["DATABASE_URL"],
            "postgresql://postgres@localhost:5432/postgres",
        )
        self.assertNotIn("PGPASSWORD", env)

    def test_ephemeral_runner_strategy_run_migrations_noop_when_no_command(self) -> None:
        """When no migration command is specified or configured, it completes cleanly as noop."""
        strategy = EphemeralRunnerDatabaseStrategy()
        result = strategy.run_migrations(repo_dir=Path.cwd(), env={})

        self.assertTrue(result.success)
        self.assertEqual(result.command, "noop")
        self.assertEqual(result.exit_code, 0)

    def test_ephemeral_runner_strategy_runs_configured_default_migration(self) -> None:
        """Runs configured default migration command if none passed explicitly."""
        strategy = EphemeralRunnerDatabaseStrategy(
            default_migration_command="python -c 'print(\"Default migrations applied\")'",
        )
        result = strategy.run_migrations(repo_dir=Path.cwd(), env={})

        self.assertTrue(result.success)
        self.assertIn("Default migrations applied", result.output)

    def test_create_database_strategy_factory(self) -> None:
        """Factory creates correct strategy instance based on config."""
        cloud_cfg = DatabaseConfig(
            strategy_type=DatabaseStrategyType.CLOUD_DEV,
            connection_string="postgres://user:pass@host/db",
            test_user_email="agent@domain.com",
        )
        strat1 = create_database_strategy(cloud_cfg)
        self.assertIsInstance(strat1, DevCloudDatabaseStrategy)
        self.assertEqual(strat1.test_user_email, "agent@domain.com")

        ephemeral_cfg = DatabaseConfig(
            strategy_type=DatabaseStrategyType.EPHEMERAL_CONTAINER,
            host="localhost",
            port=5432,
            database_name="ephemeral",
            username="pg",
        )
        strat2 = create_database_strategy(ephemeral_cfg)
        self.assertIsInstance(strat2, EphemeralRunnerDatabaseStrategy)
        self.assertEqual(strat2.database_name, "ephemeral")

    def test_teardown_executes_without_error(self) -> None:
        """Teardown executes cleanly on both strategies."""
        s1 = DevCloudDatabaseStrategy()
        s1.teardown()

        s2 = EphemeralRunnerDatabaseStrategy()
        s2.teardown()


if __name__ == "__main__":
    unittest.main()
