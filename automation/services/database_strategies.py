import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Dict, Optional, Tuple
from urllib.parse import urlparse

from automation.domain.database_strategy import (
    DatabaseConfig,
    DatabaseStrategyType,
    MigrationResult,
)
from automation.interfaces.database_strategy_interface import IDatabaseStrategy
from automation.interfaces.wireguard_interface import IWireGuardService

logger = logging.getLogger(__name__)


class DevCloudDatabaseStrategy(IDatabaseStrategy):
    """Database strategy connecting to a shared or dedicated Cloud Dev database.

    Injects an isolated test user identity (e.g. qa-runner@domain.com) and tenant flags
    to protect production and shared developer data from pollution. Destructive migrations
    are skipped by default unless an explicit migration command is provided.
    """

    def __init__(
        self,
        connection_string: Optional[str] = None,
        test_user_email: str = "qa-runner@domain.com",
        isolated_tenant: bool = True,
        extra_env: Optional[Dict[str, str]] = None,
        wireguard_service: Optional[IWireGuardService] = None,
    ) -> None:
        self.connection_string = connection_string
        self.test_user_email = test_user_email
        self.isolated_tenant = isolated_tenant
        self.extra_env = extra_env or {}
        self.wireguard_service = wireguard_service

    def get_connection_env(self) -> Dict[str, str]:
        """Returns isolated cloud dev connection environment variables."""
        env: Dict[str, str] = {
            "QA_ISOLATED_TENANT": "true" if self.isolated_tenant else "false",
            "QA_TEST_USER_EMAIL": self.test_user_email,
        }
        if self.connection_string:
            env["DATABASE_URL"] = self.connection_string
        env.update(self.extra_env)
        return env

    def run_migrations(
        self,
        repo_dir: Path,
        env: Dict[str, str],
        migration_command: Optional[str] = None,
    ) -> MigrationResult:
        """Runs migrations or safely skips destructive migrations in Cloud Dev mode."""
        if not migration_command:
            logger.info("Cloud Dev DB: skipping destructive migrations (isolated tenant mode active)")
            return MigrationResult(
                success=True,
                command="noop",
                exit_code=0,
                output="Cloud Dev DB: skipping destructive migrations (isolated tenant mode active)",
                duration_seconds=0.0,
            )

        start = time.monotonic()
        merged_env = os.environ.copy()
        merged_env.update(env)
        try:
            result = subprocess.run(
                migration_command,
                shell=True,
                cwd=str(repo_dir),
                env=merged_env,
                capture_output=True,
                text=True,
                timeout=120,
            )
            duration = time.monotonic() - start
            output = (result.stdout or "") + ("\n" + result.stderr if result.stderr else "")
            return MigrationResult(
                success=(result.returncode == 0),
                command=migration_command,
                exit_code=result.returncode,
                output=output.strip(),
                duration_seconds=duration,
            )
        except subprocess.TimeoutExpired:
            duration = time.monotonic() - start
            return MigrationResult(
                success=False,
                command=migration_command,
                exit_code=-1,
                output="Migration execution timed out after 120 seconds",
                duration_seconds=duration,
            )
        except Exception as e:
            duration = time.monotonic() - start
            return MigrationResult(
                success=False,
                command=migration_command,
                exit_code=-1,
                output=f"Migration failed with error: {e}",
                duration_seconds=duration,
            )

    def teardown(self) -> None:
        """Cleans up isolated session resources and tears down WireGuard tunnel if active."""
        if self.wireguard_service:
            self.wireguard_service.disconnect()
        logger.info("Cloud Dev DB teardown complete: isolated tenant session closed.")


class EphemeralRunnerDatabaseStrategy(IDatabaseStrategy):
    """Database strategy connecting to an ephemeral PostgreSQL service container on the runner.

    Binds to localhost:5432 and executes local schema migrations and seed scripts.
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 5432,
        database_name: str = "testdb",
        username: str = "postgres",
        password: Optional[str] = None,
        default_migration_command: Optional[str] = None,
        extra_env: Optional[Dict[str, str]] = None,
    ) -> None:
        self.host = host
        self.port = port
        self.database_name = database_name
        self.username = username
        self.password = password
        self.default_migration_command = default_migration_command
        self.extra_env = extra_env or {}

    def get_connection_env(self) -> Dict[str, str]:
        """Constructs connection variables for the local runner database container."""
        auth = f"{self.username}:{self.password}@" if self.password else f"{self.username}@"
        db_url = f"postgresql://{auth}{self.host}:{self.port}/{self.database_name}"

        env: Dict[str, str] = {
            "DATABASE_URL": db_url,
            "PGHOST": self.host,
            "PGPORT": str(self.port),
            "PGDATABASE": self.database_name,
            "PGUSER": self.username,
        }
        if self.password:
            env["PGPASSWORD"] = self.password
        env.update(self.extra_env)
        return env

    def run_migrations(
        self,
        repo_dir: Path,
        env: Dict[str, str],
        migration_command: Optional[str] = None,
    ) -> MigrationResult:
        """Executes migration and seed commands against local database container."""
        cmd = migration_command or self.default_migration_command
        if not cmd:
            return MigrationResult(
                success=True,
                command="noop",
                exit_code=0,
                output="No migration command specified for ephemeral runner database.",
                duration_seconds=0.0,
            )

        start = time.monotonic()
        merged_env = os.environ.copy()
        merged_env.update(env)
        try:
            result = subprocess.run(
                cmd,
                shell=True,
                cwd=str(repo_dir),
                env=merged_env,
                capture_output=True,
                text=True,
                timeout=120,
            )
            duration = time.monotonic() - start
            output = (result.stdout or "") + ("\n" + result.stderr if result.stderr else "")
            return MigrationResult(
                success=(result.returncode == 0),
                command=cmd,
                exit_code=result.returncode,
                output=output.strip(),
                duration_seconds=duration,
            )
        except subprocess.TimeoutExpired:
            duration = time.monotonic() - start
            return MigrationResult(
                success=False,
                command=cmd,
                exit_code=-1,
                output="Migration execution timed out after 120 seconds",
                duration_seconds=duration,
            )
        except Exception as e:
            duration = time.monotonic() - start
            return MigrationResult(
                success=False,
                command=cmd,
                exit_code=-1,
                output=f"Migration failed with error: {e}",
                duration_seconds=duration,
            )

    def teardown(self) -> None:
        """Cleans up ephemeral runner database resources."""
        logger.info("Ephemeral runner database teardown complete.")


def _extract_host_port(connection_string: Optional[str], default_host: str = "localhost", default_port: int = 5432) -> Tuple[str, int]:
    """Extracts target hostname and port from connection URI or defaults."""
    if not connection_string:
        return default_host, default_port
    try:
        parsed = urlparse(connection_string)
        host = parsed.hostname or default_host
        port = parsed.port or default_port
        return host, port
    except Exception:
        return default_host, default_port


def create_database_strategy(
    config: DatabaseConfig,
    wireguard_service: Optional[IWireGuardService] = None,
) -> IDatabaseStrategy:
    """Factory creating an IDatabaseStrategy from a DatabaseConfig domain model.

    Supports AUTO mode:
    1. If WireGuard config is provided, attempts to bring up the VPN tunnel.
    2. Probes the remote database host:port via lightweight TCP handshake.
    3. If reachable -> resolves to DevCloudDatabaseStrategy.
    4. If unreachable or no remote DB specified -> gracefully falls back to EphemeralRunnerDatabaseStrategy.
    """
    if config.strategy_type == DatabaseStrategyType.AUTO:
        # Step 1: Check if WireGuard VPN should be established
        wg_connected = False
        if config.wireguard_config and wireguard_service:
            logger.info("AUTO DB Strategy: WireGuard configuration detected. Attempting connection...")
            wg_connected = wireguard_service.connect(config.wireguard_config)
            if wg_connected:
                logger.info("AUTO DB Strategy: WireGuard tunnel established.")
            else:
                logger.warning("AUTO DB Strategy: WireGuard connection failed. Proceeding with probe/fallback.")

        # Step 2: Probe remote database connectivity
        target_host, target_port = _extract_host_port(config.connection_string, config.host, config.port)
        is_remote_host = target_host not in ("localhost", "127.0.0.1", "::1", "")

        if is_remote_host and wireguard_service:
            logger.info("AUTO DB Strategy: Probing remote database %s:%d...", target_host, target_port)
            probe = wireguard_service.probe_host(target_host, target_port, timeout_seconds=2.0)
            if probe.reachable:
                logger.info(
                    "AUTO DB Strategy: Remote database %s:%d is reachable (latency: %.2fms). Selecting CLOUD_DEV.",
                    target_host, target_port, probe.latency_ms,
                )
                return DevCloudDatabaseStrategy(
                    connection_string=config.connection_string,
                    test_user_email=config.test_user_email,
                    wireguard_service=wireguard_service if wg_connected else None,
                )
            else:
                logger.warning(
                    "AUTO DB Strategy: Remote database %s:%d is unreachable (%s). "
                    "Falling back to EPHEMERAL_CONTAINER.",
                    target_host, target_port, probe.error_message,
                )
                if wg_connected and wireguard_service:
                    wireguard_service.disconnect()
                    wg_connected = False
        elif is_remote_host and not wireguard_service:
            logger.info(
                "AUTO DB Strategy: Remote host configured but no WireGuard service provided. Defaulting to CLOUD_DEV."
            )
            return DevCloudDatabaseStrategy(
                connection_string=config.connection_string,
                test_user_email=config.test_user_email,
            )

        # Fallback to ephemeral runner container
        logger.info("AUTO DB Strategy: Selecting EPHEMERAL_CONTAINER mode.")
        if wg_connected and wireguard_service:
            wireguard_service.disconnect()
        return EphemeralRunnerDatabaseStrategy(
            host="localhost",
            port=5432,
            database_name=config.database_name,
            username=config.username,
            password=config.password,
        )

    elif config.strategy_type == DatabaseStrategyType.CLOUD_DEV:
        wg_svc = None
        if config.wireguard_config and wireguard_service:
            wireguard_service.connect(config.wireguard_config)
            wg_svc = wireguard_service
        return DevCloudDatabaseStrategy(
            connection_string=config.connection_string,
            test_user_email=config.test_user_email,
            wireguard_service=wg_svc,
        )

    elif config.strategy_type == DatabaseStrategyType.EPHEMERAL_CONTAINER:
        return EphemeralRunnerDatabaseStrategy(
            host=config.host,
            port=config.port,
            database_name=config.database_name,
            username=config.username,
            password=config.password,
        )

    raise ValueError(f"Unsupported database strategy type: {config.strategy_type}")

