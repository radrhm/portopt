"""Portfolio CRUD API routes."""

import logging
from flask import Blueprint, request, jsonify
import db

logger = logging.getLogger(__name__)
portfolio_bp = Blueprint("portfolio", __name__)


@portfolio_bp.route("/api/portfolios", methods=["GET"])
def list_portfolios():
    return jsonify({"portfolios": db.list_portfolios()})


@portfolio_bp.route("/api/portfolios/<int:pid>", methods=["GET"])
def get_portfolio(pid):
    p = db.get_portfolio(pid)
    if not p:
        return jsonify({"error": "Not found"}), 404
    return jsonify(p)


@portfolio_bp.route("/api/portfolios", methods=["POST"])
def create_portfolio():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Invalid or missing JSON body."}), 400
    pid = db.save_portfolio(data)
    return jsonify({"id": pid}), 201


@portfolio_bp.route("/api/portfolios/<int:pid>", methods=["PUT"])
def update_portfolio(pid):
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Invalid or missing JSON body."}), 400
    data["id"] = pid
    db.save_portfolio(data)
    return jsonify({"ok": True})


@portfolio_bp.route("/api/portfolios/<int:pid>", methods=["DELETE"])
def delete_portfolio(pid):
    db.delete_portfolio(pid)
    return jsonify({"ok": True})
