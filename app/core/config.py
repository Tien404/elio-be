from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ELIO_", env_file=".env", extra="ignore")
    environment: Literal["development", "test"] = "development"
    odbc_connection_string: SecretStr = SecretStr("")
    db_connect_timeout_seconds: int = Field(default=2, ge=1, le=30)
    db_query_timeout_seconds: int = Field(default=5, ge=1, le=60)
    private_files_dir: Path = Path("./data/private")
