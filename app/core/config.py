from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ELIO_", env_file=".env", extra="ignore")
    environment: Literal["development", "test"] = "development"
    database_url: SecretStr = SecretStr("")
    db_connect_timeout_seconds: int = Field(default=2, ge=1, le=30)
    db_query_timeout_seconds: int = Field(default=5, ge=1, le=60)
    private_files_dir: Path = Path("./data/private")

    # Sessions: opaque cookie, absolute lifetime, no sliding renewal.
    session_cookie_name: str = "elio_session"
    session_ttl_hours: int = Field(default=12, ge=1, le=24 * 14)
    # Browsers accept Secure cookies on http://localhost; set False only for plain-HTTP test clients.
    session_cookie_secure: bool = True

    # Store temporary passwords in private files for operator delivery.
    credential_outbox_dir: Path = Path("./data/private/credential-outbox")
