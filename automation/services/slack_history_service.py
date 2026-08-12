import json
import logging
import urllib.request
from typing import Optional, List, Dict, Any
from automation.domain.models import WorkflowEnvironment

logger = logging.getLogger("automation.slack_history")

class SlackHistoryService:
    """Service to retrieve chronological conversation thread history from Slack API."""
    
    def __init__(self, config: WorkflowEnvironment):
        self.config = config

    def fetch_thread_messages(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Single internal API entrypoint to fetch raw message dicts from Slack API."""
        token = self.config.slack_token
        channel = self.config.slack_channel
        thread_ts = self.config.slack_thread_ts

        if not token or not channel or not thread_ts:
            return []

        url = f"https://slack.com/api/conversations.replies?channel={channel}&ts={thread_ts}"
        if limit:
            url += f"&limit={limit}"

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
                    return data["messages"]
        except Exception as e:
            logger.warning(f"⚠️ Failed to fetch Slack messages: {e}")

        return []

    def fetch_first_message_text(self) -> Optional[str]:
        """Returns Turn 1 (the initial root user message text) of the Slack thread."""
        messages = self.fetch_thread_messages(limit=1)
        if messages and len(messages) > 0:
            first_msg = messages[0].get("text", "").strip()
            logger.info(f"💬 Retrieved root message from Slack thread {self.config.slack_thread_ts}: '{first_msg[:60]}...'")
            return first_msg
        return None

    def fetch_thread_history(self) -> Optional[str]:
        """Fetches all messages in the Slack thread and formats them as standard User / Assistant dialogue."""
        messages = self.fetch_thread_messages()
        if not messages:
            return None

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
        
        if formatted_turns:
            history_str = "\n\n".join(formatted_turns)
            logger.info(f"💬 Retrieved {len(messages)} messages from Slack thread {self.config.slack_thread_ts} with clean User/Assistant role formatting.")
            return history_str

        return None
