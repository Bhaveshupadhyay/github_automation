"""Unit tests for HealthCheckService and readiness probe polling."""
import unittest
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from automation.services.health_check_service import HealthCheckService
from automation.core.dependency import get_health_check_service


class DummyMockServerHandler(BaseHTTPRequestHandler):
    """Mock handler simulating healthy or failing endpoints."""
    fail_health = False

    def log_message(self, format: str, *args) -> None:
        pass

    def do_GET(self) -> None:
        if self.path == "/health":
            if DummyMockServerHandler.fail_health:
                self.send_response(503)
                self.end_headers()
                self.wfile.write(b"Service Unavailable")
            else:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"status":"healthy"}')
        else:
            self.send_response(404)
            self.end_headers()


class TestHealthCheckService(unittest.TestCase):
    """Test suite verifying HTTP readiness probe polling and timeout mechanics."""

    @classmethod
    def setUpClass(cls) -> None:
        # Start a local mock server on dynamic high port
        cls.server = HTTPServer(("127.0.0.1", 0), DummyMockServerHandler)
        cls.port = cls.server.server_port
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self) -> None:
        DummyMockServerHandler.fail_health = False
        self.health_service = get_health_check_service(default_timeout=5.0, default_interval=0.1)

    def test_probe_healthy_endpoint(self) -> None:
        """Readiness probe returns HTTP 200 and healthy=True."""
        url = f"http://127.0.0.1:{self.port}/health"
        result = self.health_service.poll_health(url, timeout_seconds=3.0, interval_seconds=0.1)
        self.assertTrue(result.healthy)
        self.assertEqual(result.status_code, 200)
        self.assertGreaterEqual(result.attempts, 1)
        self.assertIn("responded HTTP 200", result.message)

    def test_probe_failing_status(self) -> None:
        """Endpoint returning 503 times out and marks healthy=False."""
        DummyMockServerHandler.fail_health = True
        url = f"http://127.0.0.1:{self.port}/health"
        result = self.health_service.poll_health(url, timeout_seconds=0.5, interval_seconds=0.1)
        self.assertFalse(result.healthy)
        self.assertEqual(result.status_code, 503)
        self.assertIn("timed out", result.message)

    def test_probe_unreachable_endpoint(self) -> None:
        """Unreachable port times out cleanly without crashing."""
        url = "http://127.0.0.1:59999/health"
        result = self.health_service.poll_health(url, timeout_seconds=0.5, interval_seconds=0.1)
        self.assertFalse(result.healthy)
        self.assertIsNone(result.status_code)
        self.assertIn("timed out", result.message)

    def test_probe_honors_short_timeout_without_overrun(self) -> None:
        """Poll health must honor short timeout and not hang on unreachable socket."""
        url = "http://127.0.0.1:59999/health"
        start = time.monotonic()
        result = self.health_service.poll_health(url, timeout_seconds=0.2, interval_seconds=0.05)
        elapsed = time.monotonic() - start
        self.assertFalse(result.healthy)
        self.assertLess(elapsed, 0.45, f"Probe overran deadline: took {elapsed:.3f}s")


if __name__ == "__main__":
    unittest.main()
