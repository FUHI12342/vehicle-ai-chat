from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_embedding_model: str = "text-embedding-3-small"
    embedding_provider: str = "local"  # "local" (e5) or "openai"
    local_embedding_model: str = "intfloat/multilingual-e5-large-instruct"
    chroma_persist_dir: str = "./chroma_data"
    pdf_dir: str = "./pdfs"
    cors_origins: str = "http://localhost:3000"
    session_ttl_seconds: int = 3600

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
