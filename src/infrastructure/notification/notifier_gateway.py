import json
import urllib.request
from src.domain.interfaces import INotifierGateway

class CompositeNotifierAdapter(INotifierGateway):
    """Adapter sending notifications to both Telegram and Slack if credentials exist."""

    def __init__(
        self,
        telegram_token: str = "",
        telegram_chat_id: str = "",
        slack_token: str = "",
        slack_channel_id: str = ""
    ):
        self.telegram_token = telegram_token
        self.telegram_chat_id = telegram_chat_id
        self.slack_token = slack_token
        self.slack_channel_id = slack_channel_id

    def notify(self, message: str) -> None:
        print(f"[Notifier] {message}")
        if self.telegram_token and self.telegram_chat_id:
            self._send_telegram(message)
        if self.slack_token and self.slack_channel_id:
            self._send_slack(message)

    def _send_telegram(self, text: str) -> None:
        url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
        payload = json.dumps({"chat_id": self.telegram_chat_id, "text": text, "parse_mode": "Markdown"}).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req):
                pass
        except Exception as e:
            print(f"[Telegram Error] {e}")

    def _send_slack(self, text: str) -> None:
        url = "https://slack.com/api/chat.postMessage"
        headers = {
            "Authorization": f"Bearer {self.slack_token}",
            "Content-Type": "application/json"
        }
        payload = json.dumps({"channel": self.slack_channel_id, "text": text, "mrkdwn": True}).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers=headers)
        try:
            with urllib.request.urlopen(req):
                pass
        except Exception as e:
            print(f"[Slack Error] {e}")
