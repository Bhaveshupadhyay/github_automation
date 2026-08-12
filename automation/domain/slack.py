from typing import Optional, List
from pydantic import BaseModel, Field

class SlackMessage(BaseModel):
    """Pydantic model representing an individual message in a Slack thread/conversation."""
    user: Optional[str] = None
    type: str = "message"
    ts: str
    text: str = ""
    thread_ts: Optional[str] = None
    bot_id: Optional[str] = None
    subtype: Optional[str] = None
    parent_user_id: Optional[str] = None

class SlackConversationsRepliesResponse(BaseModel):
    """Pydantic model for Slack conversations.replies API response."""
    ok: bool = False
    messages: List[SlackMessage] = Field(default_factory=list)
    has_more: Optional[bool] = None
    error: Optional[str] = None
