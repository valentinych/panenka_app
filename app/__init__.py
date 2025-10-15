import logging
import os

from flask import Flask


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret-key")

    from .routes import bp as main_bp

    app.register_blueprint(main_bp)

    _configure_logging(app)

    return app


def _configure_logging(app: Flask) -> None:
    """Configure application logging to ensure visibility in production."""

    log_level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    try:
        log_level = getattr(logging, log_level_name)
    except AttributeError:
        log_level = logging.INFO

    stream_handler = logging.StreamHandler()
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        "%Y-%m-%d %H:%M:%S",
    )
    stream_handler.setFormatter(formatter)

    if not app.logger.handlers:
        app.logger.addHandler(stream_handler)

    app.logger.setLevel(log_level)

    # Make sure gunicorn/werkzeug loggers follow the same level and handler.
    for logger_name in ("gunicorn.error", "gunicorn.access", "werkzeug"):
        external_logger = logging.getLogger(logger_name)
        external_logger.setLevel(log_level)
        if not external_logger.handlers:
            external_logger.addHandler(stream_handler)

