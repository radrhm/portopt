"""PortOpt — Flask entry point."""

import logging

from flask import Flask, jsonify, render_template

import config
from middleware import register_middleware
from routes.export import export_bp
from routes.optimize import optimize_bp
from routes.portfolio import portfolio_bp
from routes.valuation import valuation_bp

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

app = Flask(__name__)
register_middleware(app)
app.register_blueprint(optimize_bp)
app.register_blueprint(portfolio_bp)
app.register_blueprint(export_bp)
app.register_blueprint(valuation_bp)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(debug=config.DEBUG, port=5000)
