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


# ── C4: PEER COMPS ────────────────────────────────────────────────────────────

_PEER_CACHE: dict = {}     # { ticker: (timestamp, payload) }
_PEER_TTL   = 60 * 60 * 6  # 6 hours

@valuation_bp.route("/api/valuation/peers/<ticker>")
def get_peers(ticker):
    import time
    sym = (ticker or "").strip().upper()
    if not sym:
        return jsonify({"error": "ticker is required"}), 400
    now = time.time()
    hit = _PEER_CACHE.get(sym)
    if hit and (now - hit[0]) < _PEER_TTL:
        return jsonify(hit[1])
    try:
        from services.peers import fetch_peer_metrics
        data = fetch_peer_metrics(sym)
        _PEER_CACHE[sym] = (now, data)
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": f"Failed to fetch peers: {e}"}), 500


# ── AI BUSINESS ANALYSIS ──────────────────────────────────────────────────────

@valuation_bp.route("/api/valuation/analysis", methods=["POST"])
def get_analysis():
    body = request.get_json(silent=True) or {}
    ticker = (body.get("ticker") or "").strip().upper()
    if not ticker:
        return jsonify({"error": "ticker is required"}), 400
    financials = body.get("financials") or {}
    if not financials:
        try:
            from services.valuation import fetch_financials
            financials = fetch_financials(ticker)
        except Exception:
            pass
    try:
        from services.valuation import get_business_analysis
        data = get_business_analysis(ticker, financials)
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


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


@valuation_bp.route("/api/valuation/settings", methods=["GET"])
def get_val_settings():
    from db import get_setting
    return jsonify(get_setting("valuation_model_settings"))


@valuation_bp.route("/api/valuation/settings", methods=["PUT"])
def save_val_settings():
    from db import save_setting
    body = request.get_json(silent=True) or {}
    save_setting("valuation_model_settings", body)
    return jsonify({"ok": True})


@valuation_bp.route("/api/valuation/lists/<int:lid>/to-portfolio", methods=["POST"])
def convert_list_to_portfolio(lid):
    from db import get_val_list, save_portfolio
    lst = get_val_list(lid)
    if not lst:
        return jsonify({"error": "not found"}), 404
    # Handle both legacy array shape and new {active, stocks} workspace shape
    raw = lst.get("tickers")
    if isinstance(raw, dict):
        items = raw.get("stocks") or []
    elif isinstance(raw, list):
        items = raw
    else:
        items = []
    # Build tickers dict matching the portfolio schema: {TICKER: {name, price}}
    tickers_dict = {}
    for t in items:
        sym = (t or {}).get("ticker", "")
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
