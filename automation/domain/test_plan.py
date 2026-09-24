"""Domain models for diff-aware test plan generation and caching."""
from datetime import datetime, timezone
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator


class ActionType(str, Enum):
    """Supported user interaction actions in test journeys."""
    NAVIGATE = "navigate"
    CLICK = "click"
    FILL = "fill"
    SCROLL = "scroll"
    SELECT = "select"
    WAIT = "wait"


class AssertionType(str, Enum):
    """Supported visible assertion types for test verification."""
    VISIBLE_TEXT = "visible_text"
    ELEMENT_EXISTS = "element_exists"
    ALERT_MESSAGE = "alert_message"
    STATE_UPDATE = "state_update"
    # Raw CSS selector for deterministic, internally built plans. Not offered to Gemini,
    # which must use accessible text/labels instead.
    CSS_SELECTOR = "css_selector"


class TestAssertion(BaseModel):
    """A single visible assertion to confirm test success."""
    __test__ = False
    type: AssertionType = Field(..., description="Type of visible assertion")
    target: str = Field(..., description="The text, label, or element to assert on")
    description: str = Field(..., description="Human-readable assertion description")


class TestAction(BaseModel):
    """A single user interaction step in a test journey."""
    __test__ = False
    action_type: ActionType = Field(..., description="Type of user interaction")
    target: str = Field(
        ...,
        description="Role-based selector, URL path, or element identifier. For WAIT: text to wait for, or empty",
    )
    value: Optional[str] = Field(default=None, description="Input value for fill/select actions")
    duration_ms: Optional[int] = Field(
        default=None,
        ge=0,
        description="For WAIT: how long to wait for target, or a fixed wait when target is empty",
    )
    description: str = Field(..., description="Human-readable step description")

    @model_validator(mode="after")
    def _validate_action_fields(self) -> "TestAction":
        if self.action_type in (ActionType.FILL, ActionType.SELECT) and self.value is None:
            raise ValueError(f"{self.action_type.value} action requires a value")
        # Older plans encoded WAIT durations as a numeric target, e.g. target="2000".
        if self.action_type == ActionType.WAIT and self.duration_ms is None and self.target.isdigit():
            self.duration_ms = int(self.target)
            self.target = ""
        return self


class TestJourney(BaseModel):
    """A complete user journey consisting of ordered actions and assertions."""
    __test__ = False
    name: str = Field(..., description="Test journey name, e.g. 'Verify updated login form'")
    entry_route: str = Field(..., description="Starting URL path, e.g. '/login'")
    actions: list[TestAction] = Field(default_factory=list, description="Ordered user interaction steps")
    assertions: list[TestAssertion] = Field(default_factory=list, description="Visible assertions to verify")


class TestPlan(BaseModel):
    """Machine-readable test plan generated from diff analysis, keyed by commit SHA for caching."""
    __test__ = False
    commit_sha: str = Field(..., description="Git commit SHA this plan was generated for")
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="UTC timestamp of generation")
    source: Literal["agy", "gemini", "fallback_baseline"] = Field(
        ..., description="Engine that wrote the plan (agy or the Gemini API), or the baseline fallback"
    )
    journeys: list[TestJourney] = Field(default_factory=list, description="Test journeys to execute")
    raw_diff_summary: str = Field(default="", description="Brief summary of what the diff changes")
    degraded: bool = Field(
        default=False,
        description="True when the plan is a fallback caused by an error rather than by the diff's content",
    )


class DiffAnalysisResult(BaseModel):
    """Intermediate result from analyzing a git diff for UI-facing impact."""
    has_ui_changes: bool = Field(..., description="Whether the diff contains UI-facing changes")
    modified_components: list[str] = Field(default_factory=list, description="List of modified UI component paths")
    modified_routes: list[str] = Field(default_factory=list, description="List of modified route paths")
    summary: str = Field(default="", description="Brief natural language summary of the diff impact")
