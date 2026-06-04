from pydantic_settings import BaseSettings, SettingsConfigDict
from urllib.parse import quote_plus, unquote_plus


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", env_file=".env", extra="ignore")

    MYSQL_HOST: str = "127.0.0.1"
    MYSQL_PORT: int = 3306
    MYSQL_USER: str = "root"
    MYSQL_PASSWORD: str = "root"
    MYSQL_DATABASE: str = "nba"
    MYSQL_POOL_SIZE: int = 10
    MYSQL_MAX_OVERFLOW: int = 20
    MYSQL_POOL_RECYCLE_SECONDS: int = 3600

    REQUEST_TIMEOUT_SECONDS: float = 15.0
    CRAWLER_HTTP_PROXY: str | None = None
    CRAWLER_HTTPS_PROXY: str | None = None
    SIAMESE_UIE_MODEL_NAME: str = "uie-base"
    SIAMESE_UIE_BATCH_SIZE: int = 8
    SERVER_PORT: int = 9002

    @property
    def mysql_sqlalchemy_url(self) -> str:
        user = quote_plus(self.MYSQL_USER)
        password_decoded = unquote_plus(self.MYSQL_PASSWORD)
        password = quote_plus(password_decoded)
        return (
            "mysql+pymysql://"
            f"{user}:{password}"
            f"@{self.MYSQL_HOST}:{self.MYSQL_PORT}/{self.MYSQL_DATABASE}"
            "?charset=utf8mb4"
        )


settings = Settings()
