from uvicorn import run

from app.config import Config
from app.logging import setup_logging

if __name__ == "__main__":
    setup_logging()
    Config.validate_config()

    host = "127.0.0.1" if Config.ENVIRONMENT in ("local", "dev") else "0.0.0.0"
    reload = Config.ENVIRONMENT in ("local", "dev")

    run("app.app:app", host=host, log_config=None, access_log=True)
