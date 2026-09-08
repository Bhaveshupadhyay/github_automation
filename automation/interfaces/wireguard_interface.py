"""Abstract interface for WireGuard VPN connection lifecycle management."""
from abc import ABC, abstractmethod
from typing import Optional

from automation.domain.database_strategy import NetworkProbeResult, WireGuardConfig


class IWireGuardService(ABC):
    """Abstract contract for establishing, monitoring, and tearing down WireGuard VPN tunnels."""

    @abstractmethod
    def is_available(self) -> bool:
        """Checks if the wireguard CLI tooling (wg-quick or wg) is available on the system."""
        pass

    @abstractmethod
    def connect(self, config: WireGuardConfig) -> bool:
        """Brings up the WireGuard VPN interface using the provided configuration.

        Args:
            config: WireGuardConfig containing raw config string or config file path.

        Returns:
            bool: True if connection succeeded and interface is up, False otherwise.
        """
        pass

    @abstractmethod
    def disconnect(self, interface_name: str = "wg0") -> bool:
        """Tears down the WireGuard VPN interface.

        Args:
            interface_name: The network interface name (default: "wg0").

        Returns:
            bool: True if teardown succeeded, False otherwise.
        """
        pass

    @abstractmethod
    def probe_host(self, host: str, port: int, timeout_seconds: float = 2.0) -> NetworkProbeResult:
        """Probes a remote host and port using a TCP handshake to verify network connectivity.

        Args:
            host: Target hostname or IP address.
            port: Target TCP port number.
            timeout_seconds: Maximum time to wait for handshake (default: 2.0s).

        Returns:
            NetworkProbeResult indicating reachability, latency, or error.
        """
        pass
