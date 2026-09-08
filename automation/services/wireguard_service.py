"""Concrete WireGuard VPN connection manager and network connectivity prober."""
import logging
import os
import shutil
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional

from automation.domain.database_strategy import NetworkProbeResult, WireGuardConfig
from automation.interfaces.wireguard_interface import IWireGuardService

logger = logging.getLogger(__name__)


class WireGuardService(IWireGuardService):
    """Manages WireGuard tunnel lifecycle and performs TCP reachability checks."""

    def __init__(self, wg_quick_binary: Optional[str] = None) -> None:
        self.wg_quick_binary = wg_quick_binary or shutil.which("wg-quick") or "wg-quick"
        self._active_interface: Optional[str] = None
        self._active_target: Optional[str] = None
        self._transient_config_path: Optional[Path] = None

    def is_available(self) -> bool:
        """Returns True if wg-quick is installed and executable."""
        return shutil.which(self.wg_quick_binary) is not None

    def probe_host(self, host: str, port: int, timeout_seconds: float = 2.0) -> NetworkProbeResult:
        """Performs a lightweight TCP handshake against host:port to test reachability."""
        start = time.monotonic()
        try:
            with socket.create_connection((host, port), timeout=timeout_seconds):
                latency_ms = (time.monotonic() - start) * 1000.0
                logger.info("TCP probe succeeded to %s:%d (%.2fms)", host, port, latency_ms)
                return NetworkProbeResult(
                    reachable=True,
                    host=host,
                    port=port,
                    latency_ms=latency_ms,
                )
        except (socket.timeout, TimeoutError) as e:
            latency_ms = (time.monotonic() - start) * 1000.0
            logger.warning("TCP probe timed out to %s:%d after %.2fs", host, port, timeout_seconds)
            return NetworkProbeResult(
                reachable=False,
                host=host,
                port=port,
                latency_ms=latency_ms,
                error_message=f"Connection timed out after {timeout_seconds}s",
            )
        except OSError as e:
            latency_ms = (time.monotonic() - start) * 1000.0
            logger.warning("TCP probe failed to %s:%d: %s", host, port, e)
            return NetworkProbeResult(
                reachable=False,
                host=host,
                port=port,
                latency_ms=latency_ms,
                error_message=str(e),
            )

    def connect(self, config: WireGuardConfig) -> bool:
        """Writes config safely, invokes wg-quick up, and registers interface."""
        if not self.is_available():
            logger.warning("WireGuard CLI (%s) not found on PATH.", self.wg_quick_binary)
            return False

        conf_path: Path
        if config.config_file_path and Path(config.config_file_path).is_file():
            conf_path = Path(config.config_file_path)
        elif config.raw_config and config.raw_config.strip():
            # Write to a secure temporary file with restrictive permissions (0600)
            tmp_fd, tmp_name = tempfile.mkstemp(
                prefix=f"{config.interface_name}_",
                suffix=".conf",
            )
            os.close(tmp_fd)
            conf_path = Path(tmp_name)
            conf_path.write_text(config.raw_config.strip() + "\n", encoding="utf-8")
            os.chmod(conf_path, 0o600)
            self._transient_config_path = conf_path
        else:
            logger.warning("WireGuardConfig contains neither config_file_path nor raw_config.")
            return False

        try:
            logger.info("Bringing up WireGuard tunnel via %s for %s", self.wg_quick_binary, conf_path)
            cmd = [self.wg_quick_binary, "up", str(conf_path)]
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if res.returncode == 0:
                self._active_target = str(conf_path)
                self._active_interface = config.interface_name
                logger.info("WireGuard tunnel for %s brought up successfully.", conf_path)
                return True
            else:
                logger.error("Failed to bring up WireGuard: %s\n%s", res.stdout, res.stderr)
                self._cleanup_transient_config()
                return False
        except Exception as e:
            logger.error("Exception occurred while bringing up WireGuard: %s", e)
            self._cleanup_transient_config()
            return False

    def disconnect(self, interface_name: str = "wg0") -> bool:
        """Tears down the active WireGuard interface and securely shreds transient config."""
        target = self._active_target or self._active_interface or interface_name
        success = True
        try:
            if self.is_available() and target:
                try:
                    logger.info("Tearing down WireGuard target %s", target)
                    cmd = [self.wg_quick_binary, "down", str(target)]
                    res = subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        timeout=15,
                    )
                    if res.returncode != 0:
                        logger.warning("wg-quick down exited with %d: %s", res.returncode, res.stderr)
                        success = False
                except Exception as e:
                    logger.warning("Error running wg-quick down: %s", e)
                    success = False
        finally:
            self._active_target = None
            self._active_interface = None
            self._cleanup_transient_config()
        return success

    def _cleanup_transient_config(self) -> None:
        """Overwrites and deletes transient WireGuard config file."""
        if self._transient_config_path and self._transient_config_path.exists():
            try:
                # Overwrite bytes before unlinking for security
                self._transient_config_path.write_bytes(b"\x00" * 256)
                self._transient_config_path.unlink()
                logger.debug("Shredded transient WireGuard config: %s", self._transient_config_path)
            except OSError as e:
                logger.warning("Failed to shred WireGuard config file %s: %s", self._transient_config_path, e)
            finally:
                self._transient_config_path = None
