"""PortOpt — Flask entry point."""

import logging
from flask import Flask, render_template, jsonify

from routes.optimize import optimize_bp
from routes.portfolio import portfolio_bp
from routes.export import export_bp
from routes.valuation import valuation_bp

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s %(name)s %(message)s",
)

app = Flask(__name__)
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
    app.run(debug=True, port=5000)
