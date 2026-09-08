"""CLI tool for orchestrating service lifecycles with DB provisioning, decryption, and health probes."""
import argparse
import os
import sys
import time
from pathlib import Path

from automation.core.dependency import get_database_strategy, get_lifecycle_supervisor
from automation.domain.database_strategy import (
    DatabaseConfig,
    DatabaseStrategyType,
    WireGuardConfig,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Lifecycle Supervisor: Decrypts secrets, provisions database, boots backend/frontend, and monitors health."
    )
    parser.add_argument(
        "--backend-dir",
        default=".",
        help="Path to backend repository directory containing qa-contract.json (default: .)",
    )
    parser.add_argument(
        "--frontend-dir",
        default=None,
        help="Optional path to frontend repository directory containing qa-contract.json",
    )
    parser.add_argument(
        "--db-strategy",
        choices=["auto", "cloud_dev", "ephemeral_container"],
        default="auto",
        help="Database strategy (auto, cloud_dev, or ephemeral_container). In auto mode, attempts WireGuard/cloud DB probe first, then falls back to ephemeral local container (default: auto).",
    )
    parser.add_argument(
        "--wireguard-conf",
        default=None,
        help="Raw WireGuard configuration string or file path (defaults to WIREGUARD_CONF env var)",
    )
    parser.add_argument(
        "--sops-age-key",
        default=None,
        help="SOPS age private key (defaults to SOPS_AGE_KEY environment variable)",
    )
    parser.add_argument(
        "--backend-timeout",
        type=float,
        default=60.0,
        help="Backend health readiness timeout in seconds (default: 60.0)",
    )
    parser.add_argument(
        "--frontend-timeout",
        type=float,
        default=60.0,
        help="Frontend health readiness timeout in seconds (default: 60.0)",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Verify startup and readiness, then exit immediately (default behavior in CI test pipelines)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output LifecycleResult as JSON",
    )

    args = parser.parse_args()

    supervisor = get_lifecycle_supervisor()

    db_strategy = None
    if args.db_strategy:
        strat_type = DatabaseStrategyType(args.db_strategy)
        wg_raw = args.wireguard_conf or os.getenv("WIREGUARD_CONF")
        wg_cfg = WireGuardConfig(raw_config=wg_raw) if wg_raw else None
        cfg = DatabaseConfig(
            strategy_type=strat_type,
            wireguard_config=wg_cfg,
            connection_string=os.getenv("DATABASE_URL"),
        )
        db_strategy = get_database_strategy(cfg)

    backend_p = Path(args.backend_dir).resolve()
    frontend_p = Path(args.frontend_dir).resolve() if args.frontend_dir else None

    print(f"🚀 Starting Lifecycle Supervisor...")
    print(f"   - Backend Dir: {backend_p}")
    if frontend_p:
        print(f"   - Frontend Dir: {frontend_p}")
    if args.db_strategy:
        print(f"   - DB Strategy: {args.db_strategy}")

    result = supervisor.start_services(
        backend_dir=backend_p,
        frontend_dir=frontend_p,
        db_strategy=db_strategy,
        sops_age_key=args.sops_age_key,
        backend_health_timeout=args.backend_timeout,
        frontend_health_timeout=args.frontend_timeout,
    )

    if args.json:
        print(result.model_dump_json(indent=2))

    if not result.success:
        print(f"\n❌ Lifecycle Startup FAILED in {result.startup_duration_seconds:.2f}s:")
        print(f"   Error: {result.error_message}")
        sys.exit(1)

    print(f"\n✅ All services successfully booted and verified healthy in {result.startup_duration_seconds:.2f}s!")
    if result.backend_info:
        print(f"   - Backend: PID={result.backend_info.pid} Port={result.backend_info.port} URL={result.backend_info.health_url} Status={result.backend_info.status.value}")
    if result.frontend_info:
        print(f"   - Frontend: PID={result.frontend_info.pid} Port={result.frontend_info.port} URL={result.frontend_info.health_url} Status={result.frontend_info.status.value}")

    if args.check_only:
        print("🧹 --check-only flag provided. Tearing down child services cleanly...")
        supervisor.terminate_all()
        print("Done.")
        sys.exit(0)

    # In interactive/daemon mode: wait for signal
    print("\n⏳ Services running in background. Press Ctrl+C to terminate...")
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("\nInterrupt received. Terminating all services...")
    finally:
        supervisor.terminate_all()
        print("All processes terminated and transient files cleaned.")


if __name__ == "__main__":
    main()
