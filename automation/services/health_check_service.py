"""Service for polling HTTP readiness probes and health check endpoints."""
import time
import urllib.request
import urllib.error
from typing import Optional

from automation.domain.health_check import HealthCheckResult
from automation.interfaces.health_check_interface import IHealthCheckService


class HealthCheckService(IHealthCheckService):
    """Polls HTTP readiness endpoints with configurable intervals and timeouts."""

    def __init__(self, default_timeout: float = 30.0, default_interval: float = 1.0) -> None:
        self._default_timeout = default_timeout
        self._default_interval = default_interval

    def poll_health(
        self,
        url: str,
        timeout_seconds: Optional[float] = None,
        interval_seconds: Optional[float] = None,
        expected_status: int = 200,
    ) -> HealthCheckResult:
        """Polls the given URL until it returns expected_status or times out.

        Args:
            url: Target URL to query (e.g. http://localhost:8000/health).
            timeout_seconds: Maximum seconds to wait before failing (default: 30.0s).
            interval_seconds: Delay between probe attempts (default: 1.0s).
            expected_status: Target HTTP status code (default: 200).
        """
        timeout = timeout_seconds if timeout_seconds is not None else self._default_timeout
        interval = interval_seconds if interval_seconds is not None else self._default_interval

        start_time = time.time()
        attempts = 0
        last_status: Optional[int] = None
        last_error: str = "Connection pending"

        req = urllib.request.Request(
            url,
            headers={"User-Agent": "QA-Readiness-Probe/1.0", "Accept": "*/*"},
            method="GET",
        )

        while (time.time() - start_time) < timeout:
            attempts += 1
            try:
                # Use a short socket timeout per probe attempt
                with urllib.request.urlopen(req, timeout=3.0) as response:
                    last_status = response.status
                    if response.status == expected_status:
                        elapsed = time.time() - start_time
                        return HealthCheckResult(
                            healthy=True,
                            url=url,
                            status_code=response.status,
                            duration_seconds=round(elapsed, 3),
                            attempts=attempts,
                            message=f"Service at {url} responded HTTP {response.status} within {elapsed:.2f}s",
                        )
                    last_error = f"Received HTTP {response.status} (expected {expected_status})"
            except urllib.error.HTTPError as err:
                last_status = err.code
                if err.code == expected_status:
                    elapsed = time.time() - start_time
                    return HealthCheckResult(
                        healthy=True,
                        url=url,
                        status_code=err.code,
                        duration_seconds=round(elapsed, 3),
                        attempts=attempts,
                        message=f"Service at {url} responded HTTP {err.code}",
                    )
                last_error = f"HTTP {err.code}: {err.reason}"
            except urllib.error.URLError as err:
                last_error = f"Network unreachable: {err.reason}"
            except Exception as ex:
                last_error = f"Probe connection error: {str(ex)}"

            time.sleep(interval)

        total_elapsed = time.time() - start_time
        return HealthCheckResult(
            healthy=False,
            url=url,
            status_code=last_status,
            duration_seconds=round(total_elapsed, 3),
            attempts=attempts,
            message=(
                f"Readiness probe timed out after {total_elapsed:.1f}s ({attempts} attempts). "
                f"Last state: {last_error}"
            ),
        )
