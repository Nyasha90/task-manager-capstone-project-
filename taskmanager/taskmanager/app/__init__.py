import json
import logging
import os

from flask import Flask, jsonify

from .models import db


class JsonFormatter(logging.Formatter):
    """Structured JSON logs: easy to ship to ELK / Fluentd."""

    def format(self, record):
        return json.dumps({
            "time": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        })


def create_app(config=None):
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.getenv("SECRET_KEY", "dev-secret-change-me"),
        SQLALCHEMY_DATABASE_URI=os.getenv("DATABASE_URL", "sqlite:///tasks.db"),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        APP_VERSION=os.getenv("APP_VERSION", "1.0.0"),
        METRICS=True,
    )
    if config:
        app.config.update(config)

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    app.logger.handlers = [handler]
    app.logger.setLevel(logging.INFO)

    db.init_app(app)

    from .routes import bp
    app.register_blueprint(bp)

    with app.app_context():
        db.create_all()

    if app.config["METRICS"]:
        from prometheus_flask_exporter import PrometheusMetrics
        metrics = PrometheusMetrics(app)  # exposes /metrics
        metrics.info("app_info", "Application info", version=app.config["APP_VERSION"])

    @app.errorhandler(404)
    def not_found(_):
        return jsonify(error="not found"), 404

    @app.errorhandler(405)
    def not_allowed(_):
        return jsonify(error="method not allowed"), 405

    @app.errorhandler(500)
    def server_error(e):
        app.logger.error("Unhandled error: %s", e)
        return jsonify(error="internal server error"), 500

    return app
