import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    app_name: str = "AI-Powered Document Intelligence System"
    debug: bool = False
    database_url: str = "sqlite:///./document_intelligence.db"
    secret_key: str = "dev-secret-key-change-me"
    api_prefix: str = "/api"
    upload_dir: str = "uploads"
    max_upload_size_mb: int = 250
    frontend_url: str = "http://localhost:5173"
    ai_provider: Literal["ollama"] = "ollama"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:3b"
    ollama_context_length: int = Field(default=4096, ge=512)
    ollama_timeout_seconds: float = Field(default=180, gt=0)
    ollama_max_parallel_requests: int = Field(default=1, ge=1)
    ollama_retries: int = Field(default=2, ge=0, le=5)
    ollama_keep_alive: str = "10m"
    embedding_model_name: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_dimension: int = Field(default=384, gt=0)
    model_cache_dir: str = str(ROOT_DIR / ".cache" / "models")
    tesseract_path: str = r"E:\Tesseract-OCR\tesseract.exe"
    tesseract_language: str = "eng"
    ocr_timeout_seconds: int = Field(default=120, gt=0)
    allowed_extensions: Annotated[list[str], NoDecode] = [
        "pdf",
        "png",
        "jpg",
        "jpeg",
        "tif",
        "tiff",
        "xlsx",
        "xls",
        "csv",
    ]

    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("allowed_extensions", mode="before")
    @classmethod
    def parse_allowed_extensions(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                parsed = value.split(",")
            value = parsed
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ValueError("ALLOWED_EXTENSIONS must be a comma-separated string or JSON list.")
        return [item.strip().lower().lstrip(".") for item in value if item.strip()]

    @field_validator("tesseract_path", mode="before")
    @classmethod
    def default_tesseract_path(cls, value: str | None) -> str:
        return value.strip() if value and value.strip() else r"E:\Tesseract-OCR\tesseract.exe"


settings = Settings()
