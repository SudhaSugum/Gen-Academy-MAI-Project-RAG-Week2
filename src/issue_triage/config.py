"""Environment-only application configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    database_url: str
    checkpoint_path: str
    checkpoint_backend: str
    checkpoint_database_url: str
    pinecone_api_key: str
    pinecone_index: str
    pinecone_cloud: str
    pinecone_region: str
    openai_api_key: str
    chat_model: str
    embedding_model: str
    embedding_dimensions: int
    retrieval_threshold: float
    keyword_overlap_threshold: float
    prompt_version: str
    mem0_api_key: str


def get_settings() -> Settings:
    load_dotenv()
    return Settings(
        database_url=os.getenv("DATABASE_URL", "sqlite:///./data/issue_triage.db"),
        checkpoint_path=os.getenv("CHECKPOINT_PATH", "./data/checkpoints.sqlite"),
        checkpoint_backend=os.getenv("CHECKPOINT_BACKEND", "sqlite").lower(),
        checkpoint_database_url=os.getenv("CHECKPOINT_DATABASE_URL", os.getenv("DATABASE_URL", "sqlite:///./data/checkpoints.sqlite")),
        pinecone_api_key=os.getenv("PINECONE_API_KEY", ""),
        pinecone_index=os.getenv("PINECONE_INDEX", "issue-triage-v1"),
        pinecone_cloud=os.getenv("PINECONE_CLOUD", "aws"),
        pinecone_region=os.getenv("PINECONE_REGION", "us-east-1"),
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        chat_model=os.getenv("CHAT_MODEL", "gpt-4o-mini"),
        embedding_model=os.getenv("EMBEDDING_MODEL", "text-embedding-3-small"),
        embedding_dimensions=int(os.getenv("EMBEDDING_DIMENSIONS", "1536")),
        retrieval_threshold=float(os.getenv("RETRIEVAL_THRESHOLD", "0.45")),
        keyword_overlap_threshold=float(os.getenv("KEYWORD_OVERLAP_THRESHOLD", "0.12")),
        prompt_version=os.getenv("PROMPT_VERSION", "triage_v1"),
        mem0_api_key=os.getenv("MEM0_API_KEY", ""),
    )
