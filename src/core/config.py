from functools import lru_cache
from pydantic import Field, AliasChoices
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    """
    Enterprise Pydantic Settings class.
    Automatically loads from environment variables and local .env file.
    """
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False
    )

    gemini_api_key: str = Field(
        default="",
        description="Google Gemini API Key from Google AI Studio"
    )
    github_token: str = Field(
        default="",
        validation_alias=AliasChoices("GITHUB_TOKEN", "PAT_TOKEN"),
        description="GitHub Personal Access Token"
    )
    github_repository: str = Field(
        default="",
        description="GitHub Repository name (owner/repo)"
    )
    user_prompt: str = Field(
        default="",
        description="User prompt request from Slack/Telegram"
    )
    
    telegram_bot_token: str = Field(default="", description="Telegram Bot Token")
    telegram_chat_id: str = Field(default="", description="Telegram Chat ID")
    
    slack_bot_token: str = Field(default="", description="Slack Bot Token")
    slack_channel_id: str = Field(
        default="",
        validation_alias=AliasChoices("SLACK_CHANNEL_ID", "CHANNEL_ID"),
        description="Slack Channel ID"
    )


settings:Settings = Settings()
