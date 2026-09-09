import logging
from flask import Flask

from app.config import Config, ensure_dirs
from app.db import db


def create_app():
    ensure_dirs()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)

    from app.dashboard.routes import bp as dashboard_bp
    app.register_blueprint(dashboard_bp)

    with app.app_context():
        db.create_all()

    return app
