from uvicorn import run

from app.config import Config
from app.logging import setup_logging

if __name__ == "__main__":
    setup_logging()
    Config.validate_config()

    run(
        "app.app:app",
        log_config=None,
        access_log=False,
        reload=Config.is_development_environment(),
        forwarded_allow_ips="*",
    )
