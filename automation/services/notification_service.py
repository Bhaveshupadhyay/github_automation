import json
import logging
import urllib.request
from automation.domain.models import WorkflowEnvironment, GitPRDetails

logger = logging.getLogger("automation.notification")

class NotificationService:
    """Service responsible for sending interactive notifications to Slack."""
    
    def __init__(self, config: WorkflowEnvironment, pr_details: GitPRDetails):
        self.config = config
        self.pr_details = pr_details

    def send_slack_notification(self, pr_url: str):
        if not self.config.slack_token or not self.config.slack_channel:
            logger.info("ℹ️ Slack notification skipped (SLACK_TOKEN or SLACK_CHANNEL not set).")
            return

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
        if self.config.slack_thread_ts:
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
            with urllib.request.urlopen(req) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                if result.get("ok"):
                    logger.info("✅ Slack notification posted successfully!")
                else:
                    logger.warning(f"⚠️ Slack API error: {result.get('error')}")
        except Exception as e:
            logger.error(f"❌ Error sending Slack notification: {e}")
