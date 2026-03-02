# src/core/config.py
# Application settings loaded from environment / .env file

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # LiveKit
    livekit_url: str = ""
    livekit_api_key: str = ""
    livekit_api_secret: str = ""

    # STT / TTS
    deepgram_api_key: str = ""
    elevenlabs_api_key: str = ""

    # LLM
    anthropic_api_key: str = ""
    openai_api_key: str = ""

    # Article fetcher
    jina_api_key: str = ""  # optional — higher rate limits on Jina Reader
    rapidapi_key: str = ""  # required for Tier 2 (mediumapi.com)

    # Phase 2: Neo4j
    neo4j_uri: str = ""
    neo4j_user: str = ""
    neo4j_password: str = ""


settings = Settings()
