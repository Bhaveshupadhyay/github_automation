"""Domain models for QA Automation Contract (qa-contract.json)."""
from enum import Enum
from typing import Optional, Any
from pydantic import BaseModel, Field, model_validator, field_validator, ConfigDict


class ServiceType(str, Enum):
    """Category of service participating in QA Automation."""
    BACKEND = "backend"
    FRONTEND = "frontend"
    MOBILE = "mobile"


class MobilePlatform(str, Enum):
    """Target mobile OS platform."""
    ANDROID = "android"
    IOS = "ios"
    BOTH = "both"


class MobileConfig(BaseModel):
    """Configuration specific to mobile applications."""
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    platform: MobilePlatform
    bundle_id: str = Field(..., alias="bundleId", description="Application bundle identifier")
    build_output_path: str = Field(..., alias="buildOutputPath", description="Relative path to debug binary")


class LifecycleHooks(BaseModel):
    """Command hooks for lifecycle management."""
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    prepare: Optional[str] = Field(None, description="Command to prepare dependencies / migrations")
    start: str = Field(..., description="Command to launch the service")

    @field_validator("start")
    @classmethod
    def validate_start_non_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Lifecycle command hook 'start' cannot be empty or whitespace.")
        return v.strip()

    @field_validator("prepare")
    @classmethod
    def validate_prepare_non_empty(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v_stripped = v.strip()
            return v_stripped if v_stripped else None
        return None


class QAContract(BaseModel):
    """Declarative operational contract defining service lifecycle, readiness probe, and environment links."""
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    schema_uri: Optional[str] = Field(None, alias="$schema")
    service_type: ServiceType = Field(..., alias="serviceType")
    port: int = Field(..., ge=1, le=65535, description="Localhost TCP port number")
    health_check_url: str = Field(..., alias="healthCheckUrl", description="Readiness probe URL or path")
    lifecycle: Optional[LifecycleHooks] = None
    prepare: Optional[str] = None
    start: Optional[str] = None
    api_base_url_env_var: Optional[str] = Field(None, alias="apiBaseUrlEnvVar")
    mobile_config: Optional[MobileConfig] = Field(None, alias="mobileConfig")

    @model_validator(mode="after")
    def validate_contract_integrity(self) -> "QAContract":
        # 1. Resolve and validate lifecycle command hooks
        if not self.lifecycle:
            if not self.start or not self.start.strip():
                raise ValueError("Lifecycle command hook 'start' must be provided and cannot be empty or whitespace.")
            self.start = self.start.strip()
            prep = self.prepare.strip() if self.prepare and self.prepare.strip() else None
            self.prepare = prep
            self.lifecycle = LifecycleHooks(prepare=prep, start=self.start)
        else:
            if not self.lifecycle.start or not self.lifecycle.start.strip():
                raise ValueError("Lifecycle command hook 'lifecycle.start' cannot be empty or whitespace.")
            self.lifecycle.start = self.lifecycle.start.strip()
            if self.lifecycle.prepare:
                self.lifecycle.prepare = self.lifecycle.prepare.strip() or None

            # Check for conflicting top-level start
            if self.start is not None:
                self.start = self.start.strip()
                if not self.start:
                    raise ValueError("Top-level 'start' cannot be empty or whitespace.")
                if self.start != self.lifecycle.start:
                    raise ValueError(
                        f"Conflicting start commands declared: top-level 'start' ('{self.start}') "
                        f"does not match 'lifecycle.start' ('{self.lifecycle.start}')."
                    )
            else:
                self.start = self.lifecycle.start

            # Check for conflicting top-level prepare
            if self.prepare is not None:
                self.prepare = self.prepare.strip() or None
                if self.prepare != self.lifecycle.prepare:
                    raise ValueError(
                        f"Conflicting prepare commands declared: top-level 'prepare' ('{self.prepare}') "
                        f"does not match 'lifecycle.prepare' ('{self.lifecycle.prepare}')."
                    )
            else:
                self.prepare = self.lifecycle.prepare

        # 2. Frontend contract rules
        if self.service_type == ServiceType.FRONTEND:
            if not self.api_base_url_env_var or not self.api_base_url_env_var.strip():
                raise ValueError(
                    "Attribute 'apiBaseUrlEnvVar' is required for frontend services "
                    "(e.g., 'NEXT_PUBLIC_API_URL', 'VITE_API_BASE_URL')."
                )

        # 3. Mobile contract rules
        if self.service_type == ServiceType.MOBILE:
            if not self.mobile_config:
                raise ValueError(
                    "Attribute 'mobileConfig' is required for mobile services with platform, bundleId, and buildOutputPath."
                )

        return self

    def get_effective_lifecycle(self) -> LifecycleHooks:
        """Returns normalized lifecycle hooks."""
        if self.lifecycle:
            return self.lifecycle
        return LifecycleHooks(prepare=self.prepare, start=self.start or "")

    def get_effective_health_url(self) -> str:
        """Resolves full HTTP localhost URL if health_check_url is relative."""
        url = self.health_check_url.strip()
        if url.startswith("http://") or url.startswith("https://"):
            return url
        if not url.startswith("/"):
            url = f"/{url}"
        return f"http://localhost:{self.port}{url}"
