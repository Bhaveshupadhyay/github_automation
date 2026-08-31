from enum import Enum
import time
from typing import Optional, Dict
from pydantic import BaseModel, Field


class PipelineStage(str, Enum):
    INITIALIZING = "initializing"
    GRAPHIFY_AST = "graphify_ast"
    AGY_EXECUTION = "agy_execution"
    OUTPUT_VALIDATION = "output_validation"
    GIT_PR_CREATION = "git_pr_creation"
    COMPLETED = "completed"
    CLARIFICATION_NEEDED = "clarification_needed"
    FAILED = "failed"


class StageStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class TelemetryState(BaseModel):
    """Domain model capturing full pipeline telemetry state for real-time Slack reporting."""
    channel: Optional[str] = None
    thread_ts: Optional[str] = None
    message_ts: Optional[str] = None
    target_repo: str = ""
    user_prompt: str = ""
    model_name: str = "gemini-3.6-flash"
    effort_val: str = "high"
    is_update_run: bool = False
    existing_branch: Optional[str] = None
    current_stage: PipelineStage = PipelineStage.INITIALIZING
    stage_statuses: Dict[str, StageStatus] = Field(default_factory=dict)
    stage_details: Dict[str, str] = Field(default_factory=dict)
    stage_start_times: Dict[str, float] = Field(default_factory=dict)
    stage_durations: Dict[str, float] = Field(default_factory=dict)
    active_activity: str = ""
    pr_url: Optional[str] = None
    branch_name: Optional[str] = None
    clarification_question: Optional[str] = None
    error_message: Optional[str] = None
    start_time: float = Field(default_factory=time.time)
    last_update_time: float = 0.0
