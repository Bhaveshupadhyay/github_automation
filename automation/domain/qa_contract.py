"""Domain models for QA Automation Contract (qa-contract.json)."""
from enum import Enum
from typing import Optional, Any
from pydantic import BaseModel, Field, model_validator, ConfigDict


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


class QAContract(BaseModel):
    """Declarative operational contract defining service lifecycle, readiness probe, and environment links."""
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

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
        # 1. Resolve lifecycle command hooks
        if not self.lifecycle:
            if not self.start:
                raise ValueError("Lifecycle command hook 'start' must be provided either under 'lifecycle.start' or 'start'.")
            self.lifecycle = LifecycleHooks(prepare=self.prepare, start=self.start)
        else:
            # Sync top-level if missing
            if not self.start:
                self.start = self.lifecycle.start
            if not self.prepare and self.lifecycle.prepare:
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
