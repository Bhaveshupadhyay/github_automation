"""Interface for QA Contract validation service."""
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, Any, Union
from automation.domain.qa_contract import QAContract


class IQAContractValidatorService(ABC):
    """Contract validator interface enforcing qa-contract.schema.json and domain rules."""

    @abstractmethod
    def validate_contract_file(self, contract_path: Union[str, Path]) -> QAContract:
        """Parses and validates a qa-contract.json file."""
        pass

    @abstractmethod
    def validate_contract_dict(self, data: Dict[str, Any]) -> QAContract:
        """Validates an in-memory dictionary representation of a qa contract."""
        pass
