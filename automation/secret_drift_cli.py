"""CLI guardrail lint tool detecting key drift between .env.example and .env.qa.enc."""
import sys
import argparse
from pathlib import Path

from automation.core.dependency import get_secret_drift_detector_service


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify that all required environment variables in .env.example are present in .env.qa.enc."
    )
    parser.add_argument(
        "--example",
        default=".env.example",
        help="Path to .env.example template file (default: .env.example)",
    )
    parser.add_argument(
        "--encrypted",
        default=".env.qa.enc",
        help="Path to .env.qa.enc encrypted secrets file (default: .env.qa.enc)",
    )
    args = parser.parse_args()

    example_path = Path(args.example)
    encrypted_path = Path(args.encrypted)

    if not example_path.exists():
        print(f"❌ Error: Example template does not exist: {example_path.resolve()}", file=sys.stderr)
        sys.exit(1)

    if not encrypted_path.exists():
        print(
            f"❌ [KEY DRIFT GUARDRAIL FAILURE]\n"
            f"Encrypted QA secrets file '{encrypted_path}' does not exist!\n"
            f"Every participating repository must commit an encrypted .env.qa.enc file.",
            file=sys.stderr,
        )
        sys.exit(1)

    detector = get_secret_drift_detector_service()
    try:
        report = detector.check_drift(example_path, encrypted_path)
        if not report.is_valid:
            print(report.error_message, file=sys.stderr)
            sys.exit(1)

        print(report.format_diagnostic_summary())
        if report.extra_keys:
            print(f"ℹ️  [Informational] Additional QA-specific keys present: {', '.join(report.extra_keys)}")
        sys.exit(0)
    except Exception as e:
        print(f"❌ Unexpected error auditing secret drift:\n   {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
