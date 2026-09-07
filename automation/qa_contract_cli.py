"""CLI tool to validate qa-contract.json against the QA Contract specification."""
import sys
import argparse
import json
from pathlib import Path

from automation.core.dependency import get_qa_contract_validator_service


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate qa-contract.json against the QA Contract standard.")
    parser.add_argument(
        "contract",
        nargs="?",
        default="qa-contract.json",
        help="Path to qa-contract.json file (default: qa-contract.json)",
    )
    parser.add_argument(
        "--schema",
        default="qa-contract.schema.json",
        help="Path to qa-contract.schema.json file (default: qa-contract.schema.json)",
    )
    args = parser.parse_args()

    validator = get_qa_contract_validator_service(schema_path=args.schema)
    contract_path = Path(args.contract)

    if not contract_path.exists():
        print(f"❌ Error: Contract file does not exist: {contract_path.resolve()}", file=sys.stderr)
        sys.exit(1)

    try:
        contract = validator.validate_contract_file(contract_path)
        print(f"✅ QA Contract '{contract_path}' is VALID!")
        print(f"   - Service Type: {contract.service_type.value}")
        print(f"   - Port: {contract.port}")
        print(f"   - Health Check URL: {contract.get_effective_health_url()}")
        lifecycle = contract.get_effective_lifecycle()
        if lifecycle.prepare:
            print(f"   - Lifecycle Prepare: {lifecycle.prepare}")
        print(f"   - Lifecycle Start: {lifecycle.start}")
        if contract.api_base_url_env_var:
            print(f"   - Frontend API Base URL Env Var: {contract.api_base_url_env_var}")
        if contract.mobile_config:
            print(f"   - Mobile Platform: {contract.mobile_config.platform.value}")
            print(f"   - Bundle ID: {contract.mobile_config.bundle_id}")
            print(f"   - Build Output: {contract.mobile_config.build_output_path}")
        sys.exit(0)
    except Exception as e:
        print(f"❌ Contract Validation Error in '{contract_path}':\n   {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
