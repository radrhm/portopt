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


# ── VALUATION LISTS ────────────────────────────────────────────────────────────

@valuation_bp.route("/api/valuation/lists", methods=["GET"])
def get_lists():
    from db import list_val_lists
    return jsonify(list_val_lists())


@valuation_bp.route("/api/valuation/lists", methods=["POST"])
def create_list():
    from db import save_val_list
    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "New List").strip()[:80]
    lid = save_val_list({"name": name, "tickers": []})
    from db import get_val_list
    return jsonify(get_val_list(lid)), 201


@valuation_bp.route("/api/valuation/lists/<int:lid>", methods=["PUT"])
def update_list(lid):
    from db import get_val_list, save_val_list
    lst = get_val_list(lid)
    if not lst:
        return jsonify({"error": "not found"}), 404
    body = request.get_json(silent=True) or {}
    if "name" in body:
        lst["name"] = (body["name"] or "New List").strip()[:80]
    if "tickers" in body:
        lst["tickers"] = body["tickers"]
    save_val_list(lst)
    return jsonify(get_val_list(lid))


@valuation_bp.route("/api/valuation/lists/<int:lid>", methods=["DELETE"])
def delete_list(lid):
    from db import get_val_list, delete_val_list
    if not get_val_list(lid):
        return jsonify({"error": "not found"}), 404
    delete_val_list(lid)
    return jsonify({"ok": True})


@valuation_bp.route("/api/valuation/lists/<int:lid>/to-portfolio", methods=["POST"])
def convert_list_to_portfolio(lid):
    from db import get_val_list, save_portfolio
    lst = get_val_list(lid)
    if not lst:
        return jsonify({"error": "not found"}), 404
    # Build tickers dict matching the portfolio schema: {TICKER: {name, price}}
    tickers_dict = {}
    for t in lst["tickers"]:
        sym = t.get("ticker", "")
        if sym:
            tickers_dict[sym] = {"name": t.get("name", sym), "price": t.get("price", 0)}
    pid = save_portfolio({
        "name": lst["name"],
        "tickers": tickers_dict,
        "settings": {},
        "overrides": {},
        "bl_views": {},
    })
    return jsonify({"portfolio_id": pid})
