"""Equity valuation routes — page + API."""

from flask import Blueprint, request, jsonify, render_template

valuation_bp = Blueprint("valuation", __name__)


@valuation_bp.route("/valuation")
def valuation_page():
    return render_template("valuation.html")


@valuation_bp.route("/api/valuation/financials")
def get_financials():
    ticker = request.args.get("ticker", "").strip().upper()
    if not ticker:
        return jsonify({"error": "ticker is required"}), 400
    try:
        from services.valuation import fetch_financials
        data = fetch_financials(ticker)
        return jsonify(data)
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        return jsonify({"error": f"Failed to fetch data: {str(e)}"}), 500
