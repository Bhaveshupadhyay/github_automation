import json
import time
import logging
import threading
import urllib.request
import urllib.error
from typing import Optional, Dict, Any

from automation.domain import WorkflowEnvironment
from automation.domain.telemetry import PipelineStage, StageStatus, TelemetryState
from automation.interfaces.telemetry_interface import ITelemetryService

logger = logging.getLogger("automation.telemetry")


class SlackTelemetryService(ITelemetryService):
    """Service handling real-time Slack progress telemetry and in-place message mutation."""

    STAGE_ORDER = [
        PipelineStage.GRAPHIFY_AST,
        PipelineStage.AGY_EXECUTION,
        PipelineStage.OUTPUT_VALIDATION,
        PipelineStage.GIT_PR_CREATION,
    ]

    STAGE_LABELS = {
        PipelineStage.GRAPHIFY_AST: "Workspace & AST Knowledge Graph",
        PipelineStage.AGY_EXECUTION: "Antigravity AI Coding Engine",
        PipelineStage.OUTPUT_VALIDATION: "Output Intent & Quality Verification",
        PipelineStage.GIT_PR_CREATION: "Git Branch & Pull Request Generation",
    }

    def __init__(self, config: WorkflowEnvironment, min_update_interval: float = 2.5):
        self.config = config
        self.min_update_interval = min_update_interval
        self._lock = threading.Lock()
        self.state = TelemetryState(
            channel=config.slack_channel,
            thread_ts=config.slack_thread_ts,
            target_repo=config.target_repo,
            user_prompt=config.user_prompt,
            model_name=config.model_name or "gemini-3.6-flash",
            effort_val=config.effort_val or "high",
        )
        for stage in self.STAGE_ORDER:
            self.state.stage_statuses[stage.value] = StageStatus.PENDING

    def _format_duration(self, seconds: float) -> str:
        if seconds < 60:
            return f"{seconds:.1f}s"
        mins = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{mins}m {secs}s"

    def _render_progress_text(self) -> str:
        with self._lock:
            elapsed_total = time.time() - self.state.start_time
            lines = []

            # Header
            header_title = "*Antigravity Autonomous Developer*"
            if self.state.is_update_run:
                header_title = "*Antigravity Autonomous Developer (Thread Iteration)*"

            lines.append(header_title)
            if self.state.target_repo:
                lines.append(f"• *Repository:* `{self.state.target_repo}`")
            lines.append(f"• *Model:* `{self.state.model_name}` (Effort: `{self.state.effort_val}`)")
            if self.state.existing_branch and self.state.is_update_run:
                lines.append(f"• *Branch:* `{self.state.existing_branch}` (Updating existing PR)")

            clean_prompt = self.state.user_prompt.strip()
            if clean_prompt:
                short_prompt = clean_prompt[:120] + ("..." if len(clean_prompt) > 120 else "")
                lines.append(f"• *Request:* {short_prompt}")

            lines.append("")
            lines.append("*Pipeline Progress:*")

            # Stages Checklist
            for idx, stage in enumerate(self.STAGE_ORDER, start=1):
                s_val = stage.value
                status = self.state.stage_statuses.get(s_val, StageStatus.PENDING)
                label = self.STAGE_LABELS.get(stage, s_val)
                detail = self.state.stage_details.get(s_val, "")
                duration = self.state.stage_durations.get(s_val)

                if status == StageStatus.COMPLETED:
                    dur_str = f" • {self._format_duration(duration)}" if duration else ""
                    detail_str = f" ({detail}{dur_str})" if detail else f" (Completed{dur_str})"
                    lines.append(f"[✓] *{idx}. {label}*{detail_str}")

                elif status == StageStatus.RUNNING:
                    dur = time.time() - self.state.stage_start_times.get(s_val, time.time())
                    active_sub = f": {self.state.active_activity}" if self.state.active_activity and stage == PipelineStage.AGY_EXECUTION else ""
                    detail_str = f" — {detail}" if detail and not active_sub else ""
                    lines.append(f"[>] *{idx}. {label}* (In progress{active_sub}{detail_str} • {self._format_duration(dur)})")

                elif status == StageStatus.FAILED:
                    lines.append(f"[!] *{idx}. {label}* (Failed: {detail or 'Error'})")

                else:
                    lines.append(f"[ ] *{idx}. {label}*")

            lines.append("")

            # Outcome / Footer
            if self.state.current_stage == PipelineStage.COMPLETED:
                lines.append(f"*Status:* Completed successfully in {self._format_duration(elapsed_total)}")
                if self.state.pr_url:
                    action_label = "Updated Existing Pull Request" if self.state.is_update_run else "Pull Request Ready for Review"
                    lines.append(f"<{self.state.pr_url}|{action_label}>")
            elif self.state.current_stage == PipelineStage.CLARIFICATION_NEEDED:
                lines.append("*Status:* Clarification Needed")
                if self.state.clarification_question:
                    lines.append(f"• *Question:* {self.state.clarification_question}")
                lines.append("Please reply directly in this thread with the requested details.")
            elif self.state.current_stage == PipelineStage.FAILED:
                lines.append("*Status:* Pipeline execution failed")
                if self.state.error_message:
                    lines.append(f"• *Error:* {self.state.error_message}")
            else:
                lines.append(f"Elapsed: {self._format_duration(elapsed_total)}")

            return "\n".join(lines)

    def _send_slack_api(self, endpoint: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        token = self.config.slack_token
        if not token or not self.state.channel:
            return None

        url = f"https://slack.com/api/{endpoint}"
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=utf-8"
            }
        )

        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if not data.get("ok"):
                    logger.warning(f"Slack API {endpoint} warning: {data.get('error')}")
                return data
        except Exception as e:
            logger.warning(f"Slack API {endpoint} error: {e}")
            return None

    def _dispatch_update_async(self):
        """Dispatches in-place chat.update asynchronously in a short-lived thread."""
        if not self.state.message_ts:
            return

        payload = {
            "channel": self.state.channel,
            "ts": self.state.message_ts,
            "text": self._render_progress_text(),
        }

        def worker():
            self._send_slack_api("chat.update", payload)

        t = threading.Thread(target=worker, daemon=False, name="SlackTelemetryUpdateWorker")
        t.start()
        t.join(timeout=3.0)

    def initialize_card(self, is_update_run: bool = False, existing_branch: Optional[str] = None) -> Optional[str]:
        with self._lock:
            self.state.is_update_run = is_update_run
            self.state.existing_branch = existing_branch
            self.state.start_time = time.time()

        if not self.config.slack_token or not self.state.channel:
            logger.info("Slack token or channel not configured; telemetry initialized in offline mode.")
            return None

        payload: Dict[str, Any] = {
            "channel": self.state.channel,
            "text": self._render_progress_text(),
        }
        if self.state.thread_ts:
            payload["thread_ts"] = self.state.thread_ts

        resp = self._send_slack_api("chat.postMessage", payload)
        if resp and resp.get("ok"):
            ts = resp.get("ts")
            with self._lock:
                self.state.message_ts = ts
                self.state.last_update_time = time.time()
            logger.info(f"Initialized Slack progress telemetry card (ts: {ts})")
            return ts
        return None

    def update_stage(self, stage: PipelineStage, detail: Optional[str] = None, force: bool = False) -> None:
        with self._lock:
            now = time.time()
            prev_stage = self.state.current_stage

            # Finalize previous stage duration if active
            if prev_stage in self.STAGE_ORDER:
                p_val = prev_stage.value
                if self.state.stage_statuses.get(p_val) == StageStatus.RUNNING:
                    self.state.stage_statuses[p_val] = StageStatus.COMPLETED
                    start_t = self.state.stage_start_times.get(p_val, now)
                    self.state.stage_durations[p_val] = now - start_t

            self.state.current_stage = stage
            s_val = stage.value

            if stage in self.STAGE_ORDER:
                self.state.stage_statuses[s_val] = StageStatus.RUNNING
                self.state.stage_start_times[s_val] = now
                if detail:
                    self.state.stage_details[s_val] = detail
                self.state.active_activity = ""

            self.state.last_update_time = now

        self._dispatch_update_async()

    def stream_activity(self, activity: str) -> None:
        clean_activity = activity.strip()
        if not clean_activity:
            return

        now = time.time()
        with self._lock:
            self.state.active_activity = clean_activity
            if now - self.state.last_update_time < self.min_update_interval:
                return  # Throttle to respect Slack rate limits
            self.state.last_update_time = now

        self._dispatch_update_async()

    def complete(self, pr_url: Optional[str] = None, branch_name: Optional[str] = None) -> None:
        now = time.time()
        with self._lock:
            # Mark all pipeline stages as completed
            for stage in self.STAGE_ORDER:
                s_val = stage.value
                if self.state.stage_statuses.get(s_val) != StageStatus.COMPLETED:
                    self.state.stage_statuses[s_val] = StageStatus.COMPLETED
                    if s_val in self.state.stage_start_times and s_val not in self.state.stage_durations:
                        self.state.stage_durations[s_val] = now - self.state.stage_start_times[s_val]

            self.state.current_stage = PipelineStage.COMPLETED
            self.state.pr_url = pr_url
            self.state.branch_name = branch_name
            self.state.active_activity = ""
            self.state.last_update_time = now

        self._dispatch_update_async()

    def fail(self, error_message: str) -> None:
        now = time.time()
        with self._lock:
            cur = self.state.current_stage.value
            if cur in self.state.stage_statuses:
                self.state.stage_statuses[cur] = StageStatus.FAILED
                self.state.stage_details[cur] = error_message
            self.state.current_stage = PipelineStage.FAILED
            self.state.error_message = error_message
            self.state.last_update_time = now

        self._dispatch_update_async()

    def request_clarification(self, question: str) -> None:
        now = time.time()
        with self._lock:
            self.state.current_stage = PipelineStage.CLARIFICATION_NEEDED
            self.state.clarification_question = question
            self.state.last_update_time = now

        self._dispatch_update_async()
