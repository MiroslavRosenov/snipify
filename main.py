from uvicorn import run

from app.config import Config
from app.logging import setup_logging

if __name__ == "__main__":
    setup_logging()
    Config.validate_config()

    host = "127.0.0.1" if Config.is_development_environment() else "0.0.0.0"
    run("app.app:app", host=host, log_config=None, access_log=True)
