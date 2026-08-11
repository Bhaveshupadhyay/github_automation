import json
import logging
import urllib.request
from typing import Optional
from automation.domain.models import WorkflowEnvironment

logger = logging.getLogger("automation.slack_history")

class SlackHistoryService:
    """Service to retrieve full chronological conversation thread history from Slack API."""
    
    def __init__(self, config: WorkflowEnvironment):
        self.config = config

    def fetch_thread_history(self) -> Optional[str]:
        """Fetches all messages in the Slack thread associated with slack_thread_ts and formats them as standard User / Assistant dialogue."""
        token = self.config.slack_token
        channel = self.config.slack_channel
        thread_ts = self.config.slack_thread_ts

        if not token or not channel or not thread_ts:
            return None

        url = f"https://slack.com/api/conversations.replies?channel={channel}&ts={thread_ts}"
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/x-www-form-urlencoded"
            }
        )

        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if data.get("ok") and "messages" in data:
                    messages = data["messages"]
                    formatted_turns = []
                    for msg in messages:
                        text = msg.get("text", "").strip()
                        if not text:
                            continue
                        
                        # Differentiate Human User vs AI Assistant Bot messages
                        if msg.get("bot_id") or msg.get("subtype") == "bot_message":
                            role = "Assistant (AI)"
                        else:
                            role = "User (Human)"
                        
                        formatted_turns.append(f"### {role}:\n{text}")
                    
                    history_str = "\n\n".join(formatted_turns)
                    logger.info(f"💬 Retrieved {len(messages)} messages from Slack thread {thread_ts} with clean User/Assistant role formatting.")
                    return history_str
        except Exception as e:
            logger.warning(f"⚠️ Failed to fetch Slack thread history: {e}")

        return None
