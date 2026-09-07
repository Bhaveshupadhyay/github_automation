"""Domain models for Secret Key Drift Detection."""
from typing import List, Optional
from pydantic import BaseModel, Field


class DriftReport(BaseModel):
    """Result of comparing .env.example against .env.qa.enc."""
    is_valid: bool = Field(..., description="True if no required keys are missing from encrypted secrets")
    missing_keys: List[str] = Field(default_factory=list, description="Keys defined in .env.example missing from .env.qa.enc")
    extra_keys: List[str] = Field(default_factory=list, description="Keys present in .env.qa.enc not present in .env.example")
    example_keys: List[str] = Field(default_factory=list, description="All keys found in .env.example")
    qa_keys: List[str] = Field(default_factory=list, description="All keys found in .env.qa.enc")
    error_message: Optional[str] = Field(None, description="Detailed diagnostic error message for CI/CD")

    def format_diagnostic_summary(self) -> str:
        """Formats an actionable CLI/CI diagnostic message."""
        if self.is_valid:
            return (
                f"✅ [SECRET INTEGRITY VERIFIED] All {len(self.example_keys)} required environment keys "
                f"are present in .env.qa.enc."
            )

        missing_list = ", ".join(f"'{k}'" for k in sorted(self.missing_keys))
        return (
            f"❌ [KEY DRIFT GUARDRAIL FAILURE]\n"
            f"The following {len(self.missing_keys)} environment variable(s) defined in .env.example "
            f"are MISSING from .env.qa.enc:\n"
            f"  -> {missing_list}\n\n"
            f"Mandatory Action Required:\n"
            f"  1. Decrypt/edit secrets using: sops .env.qa.enc\n"
            f"  2. Add the missing variable(s) with appropriate QA test values.\n"
            f"  3. Save and stage: git add .env.qa.enc\n"
            f"  4. Re-commit your PR."
        )
