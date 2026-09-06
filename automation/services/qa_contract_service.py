"""Implementation of QA Contract validation service."""
import json
from pathlib import Path
from typing import Dict, Any, Union

from automation.domain.qa_contract import QAContract
from automation.interfaces.qa_contract_interface import IQAContractValidatorService


class QAContractValidatorService(IQAContractValidatorService):
    """Validates qa-contract.json against declarative schema standards and domain rules."""

    def __init__(self, schema_path: Union[str, Path, None] = None) -> None:
        self.schema_path = Path(schema_path) if schema_path else Path("qa-contract.schema.json")

    def validate_contract_file(self, contract_path: Union[str, Path]) -> QAContract:
        """Parses and validates a qa-contract.json file from disk."""
        path = Path(contract_path)
        if not path.is_file():
            raise FileNotFoundError(f"QA Contract file not found at: {path.resolve()}")

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as err:
            raise ValueError(f"Malformed JSON in QA contract {path}: {err}") from err

        return self.validate_contract_dict(data)

    def validate_contract_dict(self, data: Dict[str, Any]) -> QAContract:
        """Validates contract data dictionary against Pydantic schema and structural rules."""
        if not isinstance(data, dict):
            raise ValueError(f"QA Contract root must be a JSON object/dict, got {type(data).__name__}")

        # Pydantic QAContract enforces port range, lifecycle, serviceType-specific requirements
        contract = QAContract.model_validate(data)
        return contract
