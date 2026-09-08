"""Service for orchestrating backend and frontend service lifecycles with DB provisioning and health verification."""
import logging
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Dict, Optional

from automation.domain.lifecycle import (
    LifecycleResult,
    ServiceProcessInfo,
    ServiceStatus,
)
from automation.interfaces.database_strategy_interface import IDatabaseStrategy
from automation.interfaces.health_check_interface import IHealthCheckService
from automation.interfaces.lifecycle_interface import ILifecycleSupervisor
from automation.interfaces.process_tree_interface import IProcessTreeManager
from automation.interfaces.qa_contract_interface import IQAContractValidatorService
from automation.interfaces.sops_interface import ISOpsService
from automation.services.database_strategies import (
    DevCloudDatabaseStrategy,
    EphemeralRunnerDatabaseStrategy,
)
from automation.services.health_check_service import HealthCheckService
from automation.services.process_tree_manager import ProcessTreeManager
from automation.services.qa_contract_service import QAContractValidatorService
from automation.services.sops_service import SOpsService

logger = logging.getLogger(__name__)


def parse_dotenv_string(content: str) -> Dict[str, str]:
    """Parses a decrypted dotenv string into key-value pairs."""
    env: Dict[str, str] = {}
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$", line)
        if match:
            k = match.group(1)
            v = match.group(2).strip()
            if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
                v = v[1:-1]
            env[k] = v
    return env


class LifecycleSupervisorService(ILifecycleSupervisor):
    """Supervises end-to-end service execution: decryption, DB setup, background spawning, and readiness."""

    def __init__(
        self,
        sops_service: Optional[ISOpsService] = None,
        qa_contract_validator: Optional[IQAContractValidatorService] = None,
        health_check_service: Optional[IHealthCheckService] = None,
        process_tree_manager: Optional[IProcessTreeManager] = None,
    ) -> None:
        self._sops_service = sops_service or SOpsService()
        self._qa_contract_validator = qa_contract_validator or QAContractValidatorService()
        self._health_check_service = health_check_service or HealthCheckService()
        self._process_tree_manager = process_tree_manager or ProcessTreeManager()
        self._active_db_strategy: Optional[IDatabaseStrategy] = None
        self._backend_info: Optional[ServiceProcessInfo] = None
        self._frontend_info: Optional[ServiceProcessInfo] = None

    def start_services(
        self,
        backend_dir: Path,
        frontend_dir: Optional[Path] = None,
        db_strategy: Optional[IDatabaseStrategy] = None,
        sops_age_key: Optional[str] = None,
        backend_health_timeout: float = 60.0,
        frontend_health_timeout: float = 60.0,
    ) -> LifecycleResult:
        """Decrypts environment secrets, starts DB, spawns backend & frontend, and polls readiness."""
        start_time = time.monotonic()
        self._process_tree_manager.install_signal_traps()

        backend_path = Path(backend_dir).resolve()
        if not backend_path.is_dir():
            return LifecycleResult(
                success=False,
                error_message=f"Backend directory does not exist: {backend_path}",
                startup_duration_seconds=time.monotonic() - start_time,
            )

        # 1. Runtime SOPS Decryption
        decrypted_env: Dict[str, str] = {}
        enc_file = backend_path / ".env.qa.enc"
        if not enc_file.is_file() and (backend_path.parent / ".env.qa.enc").is_file():
            enc_file = backend_path.parent / ".env.qa.enc"

        if enc_file.is_file():
            logger.info(f"Decrypting runtime secrets from {enc_file}...")
            transient_env_path = backend_path / ".env.qa.transient"
            self._process_tree_manager.register_transient_file(transient_env_path)
            try:
                decrypted_content = self._sops_service.decrypt_file(
                    encrypted_path=enc_file,
                    output_path=transient_env_path,
                    age_private_key=sops_age_key,
                )
                decrypted_env = parse_dotenv_string(decrypted_content)
                logger.info(f"Decrypted {len(decrypted_env)} environment variables into transient file.")
            except Exception as e:
                err = f"SOPS Decryption Error: {e}"
                logger.error(err)
                self.terminate_all()
                return LifecycleResult(
                    success=False,
                    error_message=err,
                    startup_duration_seconds=time.monotonic() - start_time,
                )

        # 2. Validate Backend QA Contract
        contract_path = backend_path / "qa-contract.json"
        try:
            backend_contract = self._qa_contract_validator.validate_contract_file(contract_path)
        except Exception as e:
            err = f"Backend QA contract validation failed: {e}"
            logger.error(err)
            self.terminate_all()
            return LifecycleResult(
                success=False,
                error_message=err,
                startup_duration_seconds=time.monotonic() - start_time,
            )

        # 3. Provision Database Strategy
        if db_strategy is None:
            if "DATABASE_URL" in decrypted_env:
                db_strategy = DevCloudDatabaseStrategy(connection_string=decrypted_env["DATABASE_URL"])
            else:
                db_strategy = EphemeralRunnerDatabaseStrategy()
        self._active_db_strategy = db_strategy

        db_env = db_strategy.get_connection_env()

        # Run migrations if defined
        merged_migration_env = {**os.environ, **decrypted_env, **db_env}
        migration_cmd = backend_contract.lifecycle.prepare if backend_contract.lifecycle else backend_contract.prepare
        if migration_cmd:
            logger.info(f"Running database migrations/prepare hook: {migration_cmd}")
            migration_res = db_strategy.run_migrations(
                backend_path,
                merged_migration_env,
                migration_command=migration_cmd,
            )
            if not migration_res.success:
                err = f"Database migration/prepare command failed: {migration_res.output}"
                logger.error(err)
                self.terminate_all()
                return LifecycleResult(
                    success=False,
                    db_strategy=db_strategy.__class__.__name__,
                    error_message=err,
                    startup_duration_seconds=time.monotonic() - start_time,
                )

        # 4. Start Backend Service Process
        backend_proc_env = {
            **os.environ,
            **decrypted_env,
            **db_env,
            "PORT": str(backend_contract.port),
        }
        backend_log_file = backend_path / "backend_service.log"
        backend_cmd = backend_contract.lifecycle.start if backend_contract.lifecycle else backend_contract.start

        backend_proc = self._process_tree_manager.spawn_service_process(
            cmd=backend_cmd,
            cwd=backend_path,
            env=backend_proc_env,
            name="backend",
            log_file=backend_log_file,
        )

        self._backend_info = ServiceProcessInfo(
            name="backend",
            pid=backend_proc.pid,
            port=backend_contract.port,
            health_url=backend_contract.health_check_url,
            status=ServiceStatus.STARTING,
            start_command=backend_cmd,
            log_file_path=str(backend_log_file),
        )

        # 5. Poll Backend Health Readiness
        logger.info(f"Polling backend readiness at {backend_contract.health_check_url} (timeout={backend_health_timeout}s)...")
        backend_check = self._health_check_service.poll_health(
            backend_contract.health_check_url,
            timeout_seconds=backend_health_timeout,
        )
        backend_ready = backend_check.healthy if hasattr(backend_check, "healthy") else bool(backend_check)

        if not backend_ready:
            self._backend_info.status = ServiceStatus.UNHEALTHY
            log_tail = ""
            if backend_log_file.is_file():
                try:
                    log_tail = "\n" + "\n".join(backend_log_file.read_text().splitlines()[-20:])
                except Exception:
                    pass
            err = f"Backend health check timed out after {backend_health_timeout}s at {backend_contract.health_check_url}.{log_tail}"
            logger.error(err)
            self.terminate_all()
            return LifecycleResult(
                success=False,
                backend_info=self._backend_info,
                db_strategy=db_strategy.__class__.__name__,
                error_message=err,
                startup_duration_seconds=time.monotonic() - start_time,
            )

        self._backend_info.status = ServiceStatus.HEALTHY
        logger.info(f"Backend is ready and healthy at {backend_contract.health_check_url}!")

        # 6. Start Frontend Service (if provided)
        if frontend_dir is not None:
            frontend_path = Path(frontend_dir).resolve()
            if not frontend_path.is_dir():
                err = f"Frontend directory does not exist: {frontend_path}"
                logger.error(err)
                self.terminate_all()
                return LifecycleResult(
                    success=False,
                    backend_info=self._backend_info,
                    db_strategy=db_strategy.__class__.__name__,
                    error_message=err,
                    startup_duration_seconds=time.monotonic() - start_time,
                )

            fe_contract_path = frontend_path / "qa-contract.json"
            try:
                frontend_contract = self._qa_contract_validator.validate_contract_file(fe_contract_path)
            except Exception as e:
                err = f"Frontend QA contract validation failed: {e}"
                logger.error(err)
                self.terminate_all()
                return LifecycleResult(
                    success=False,
                    backend_info=self._backend_info,
                    db_strategy=db_strategy.__class__.__name__,
                    error_message=err,
                    startup_duration_seconds=time.monotonic() - start_time,
                )

            backend_base_url = f"http://localhost:{backend_contract.port}"
            frontend_proc_env = {
                **os.environ,
                **decrypted_env,
                "PORT": str(frontend_contract.port),
            }
            if frontend_contract.api_base_url_env_var:
                frontend_proc_env[frontend_contract.api_base_url_env_var] = backend_base_url

            # Execute frontend prepare command if present
            fe_prepare_cmd = frontend_contract.lifecycle.prepare if frontend_contract.lifecycle else frontend_contract.prepare
            if fe_prepare_cmd:
                logger.info(f"Running frontend prepare hook: {fe_prepare_cmd}")
                try:
                    fe_prep_res = subprocess.run(
                        fe_prepare_cmd,
                        shell=True,
                        cwd=str(frontend_path),
                        env=frontend_proc_env,
                        capture_output=True,
                        text=True,
                        timeout=120,
                    )
                    if fe_prep_res.returncode != 0:
                        err = f"Frontend prepare command failed: {fe_prep_res.stderr or fe_prep_res.stdout}"
                        logger.error(err)
                        self.terminate_all()
                        return LifecycleResult(
                            success=False,
                            backend_info=self._backend_info,
                            db_strategy=db_strategy.__class__.__name__,
                            error_message=err,
                            startup_duration_seconds=time.monotonic() - start_time,
                        )
                except subprocess.TimeoutExpired:
                    err = f"Frontend prepare command timed out after 120s: {fe_prepare_cmd}"
                    logger.error(err)
                    self.terminate_all()
                    return LifecycleResult(
                        success=False,
                        backend_info=self._backend_info,
                        db_strategy=db_strategy.__class__.__name__,
                        error_message=err,
                        startup_duration_seconds=time.monotonic() - start_time,
                    )
                except Exception as e:
                    err = f"Frontend prepare command error: {e}"
                    logger.error(err)
                    self.terminate_all()
                    return LifecycleResult(
                        success=False,
                        backend_info=self._backend_info,
                        db_strategy=db_strategy.__class__.__name__,
                        error_message=err,
                        startup_duration_seconds=time.monotonic() - start_time,
                    )

            fe_log_file = frontend_path / "frontend_service.log"
            fe_cmd = frontend_contract.lifecycle.start if frontend_contract.lifecycle else frontend_contract.start

            fe_proc = self._process_tree_manager.spawn_service_process(
                cmd=fe_cmd,
                cwd=frontend_path,
                env=frontend_proc_env,
                name="frontend",
                log_file=fe_log_file,
            )

            self._frontend_info = ServiceProcessInfo(
                name="frontend",
                pid=fe_proc.pid,
                port=frontend_contract.port,
                health_url=frontend_contract.health_check_url,
                status=ServiceStatus.STARTING,
                start_command=fe_cmd,
                log_file_path=str(fe_log_file),
            )

            logger.info(f"Polling frontend readiness at {frontend_contract.health_check_url} (timeout={frontend_health_timeout}s)...")
            frontend_check = self._health_check_service.poll_health(
                frontend_contract.health_check_url,
                timeout_seconds=frontend_health_timeout,
            )
            frontend_ready = frontend_check.healthy if hasattr(frontend_check, "healthy") else bool(frontend_check)

            if not frontend_ready:
                self._frontend_info.status = ServiceStatus.UNHEALTHY
                log_tail = ""
                if fe_log_file.is_file():
                    try:
                        log_tail = "\n" + "\n".join(fe_log_file.read_text().splitlines()[-20:])
                    except Exception:
                        pass
                err = f"Frontend health check timed out after {frontend_health_timeout}s at {frontend_contract.health_check_url}.{log_tail}"
                logger.error(err)
                self.terminate_all()
                return LifecycleResult(
                    success=False,
                    backend_info=self._backend_info,
                    frontend_info=self._frontend_info,
                    db_strategy=db_strategy.__class__.__name__,
                    error_message=err,
                    startup_duration_seconds=time.monotonic() - start_time,
                )

            self._frontend_info.status = ServiceStatus.HEALTHY
            logger.info(f"Frontend is ready and healthy at {frontend_contract.health_check_url}!")

        duration = time.monotonic() - start_time
        return LifecycleResult(
            success=True,
            backend_info=self._backend_info,
            frontend_info=self._frontend_info,
            db_strategy=db_strategy.__class__.__name__,
            transient_files_cleaned=False,
            startup_duration_seconds=duration,
        )

    def terminate_all(self) -> None:
        """Terminates all running processes, tears down database session, and shreds transient files."""
        logger.info("Terminating all supervised child services and cleaning transient secrets...")
        self._process_tree_manager.terminate_all(timeout=5.0)
        self._process_tree_manager.shred_transient_files()

        if self._active_db_strategy:
            try:
                self._active_db_strategy.teardown()
            except Exception as e:
                logger.warning(f"Error during database strategy teardown: {e}")

        if self._backend_info and self._backend_info.status not in (ServiceStatus.UNHEALTHY, ServiceStatus.FAILED):
            self._backend_info.status = ServiceStatus.TERMINATED
        if self._frontend_info and self._frontend_info.status not in (ServiceStatus.UNHEALTHY, ServiceStatus.FAILED):
            self._frontend_info.status = ServiceStatus.TERMINATED
