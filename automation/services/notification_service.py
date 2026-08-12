import json
import logging
import threading
import urllib.request
from typing import Dict, Any, Optional
from automation.domain import WorkflowEnvironment, GitPRDetails, TaskIntent
from automation.interfaces.notification_interface import INotificationService

logger = logging.getLogger("automation.notification")

class NotificationService(INotificationService):
    """Service responsible for sending interactive notifications to Slack asynchronously in non-blocking threads."""
    
    def __init__(self, config: WorkflowEnvironment, pr_details: Optional[GitPRDetails] = None):
        self.config = config
        self.pr_details = pr_details

    def _post_slack_payload_sync(self, payload: Dict[str, Any]):
        """Synchronous HTTP worker method executed in a background thread."""
        if not self.config.slack_token or not self.config.slack_channel:
            logger.info("ℹ️ Slack notification skipped (SLACK_TOKEN or SLACK_CHANNEL not set).")
            return

        if self.config.slack_thread_ts and "thread_ts" not in payload:
            payload["thread_ts"] = self.config.slack_thread_ts

        req = urllib.request.Request(
            "https://slack.com/api/chat.postMessage",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.config.slack_token}",
                "Content-Type": "application/json; charset=utf-8"
            }
        )

        try:
            # Enforce strict 5-second HTTP timeout
            with urllib.request.urlopen(req, timeout=5) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                if result.get("ok"):
                    logger.info("✅ Slack notification posted successfully!")
                else:
                    logger.warning(f"⚠️ Slack API error: {result.get('error')}")
        except Exception as e:
            # Fail-safe: Notification failures log warnings and NEVER crash the pipeline
            logger.warning(f"⚠️ Non-critical Slack notification skipped ({e}).")

    def _dispatch_async(self, payload: Dict[str, Any]):
        """Dispatches notification payload in a thread and joins with a short timeout to ensure HTTP delivery."""
        thread = threading.Thread(
            target=self._post_slack_payload_sync,
            args=(payload,),
            daemon=False,
            name="SlackNotificationWorker"
        )
        thread.start()
        # Wait up to 5 seconds for HTTP POST to finish before process termination
        thread.join(timeout=5.0)

    def send_pr_notification(self, pr_url: str):
        payload = {
            "channel": self.config.slack_channel,
            "text": (
                f"🚀 *Pull Request Created & Ready for Review!*\n\n"
                f"📦 *Repository:* `{self.config.target_repo}`\n"
                f"🧠 *Model:* `{self.config.model_name}` (Effort: `{self.config.effort_val}`)\n"
                f"📌 *Prompt:* `{self.config.user_prompt}`\n"
                f"🔗 *PR Link:* <{pr_url}|View Pull Request>\n\n"
                f"👀 Please review and merge when ready!"
            )
        }
        self._dispatch_async(payload)

    def send_slack_notification(self, pr_url: str):
        """Backward-compatible alias for send_pr_notification."""
        self.send_pr_notification(pr_url)

    def send_clarification_notification(self, intent: TaskIntent):
        question = intent.clarification_question or "Could you please provide missing required details to proceed?"
        payload = {
            "channel": self.config.slack_channel,
            "text": (
                f"❓ *Clarification Needed by Antigravity AI*\n\n"
                f"📌 *Question:* {question}\n\n"
                f"💬 *Please reply in this thread with the requested detail!*"
            )
        }
        self._dispatch_async(payload)

    def send_deployment_notification(self, deploy_result: Dict[str, Any]):
        status_emoji = "✅" if deploy_result.get("success") else "❌"
        status_text = "SUCCESSFUL" if deploy_result.get("success") else "FAILED"
        payload = {
            "channel": self.config.slack_channel,
            "text": (
                f"{status_emoji} *Operational Deployment {status_text}*\n\n"
                f"📦 *Repository:* `{self.config.target_repo}`\n"
                f"🚀 *Action:* `{deploy_result.get('action')}`\n"
                f"📌 *Prompt:* `{self.config.user_prompt}`\n\n"
                f"📋 *Log Output:*\n```\n{deploy_result.get('output')}\n```"
            )
        }
        self._dispatch_async(payload)
