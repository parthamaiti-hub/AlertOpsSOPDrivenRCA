from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    openai_api_key: str = ""
    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_db: str = "sop_alert_analytics"
    rabbitmq_url: str = "amqp://guest:guest@localhost:5672/"
    chroma_host: str = "localhost"
    chroma_port: int = 8100
    prompt_backend: str = "file"
    retry_max_batch_size: int = 50

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
