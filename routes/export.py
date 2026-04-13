"""PDF export route."""

import io
import logging
import traceback

from flask import Blueprint, request, jsonify, send_file

from services.pdf_export import build_pdf

logger = logging.getLogger(__name__)
export_bp = Blueprint("export", __name__)


@export_bp.route("/api/export-pdf", methods=["POST"])
def export_pdf():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Invalid or missing JSON body."}), 400
    try:
        pdf_bytes = build_pdf(data)
        return send_file(
            io.BytesIO(pdf_bytes),
            mimetype="application/pdf",
            as_attachment=True,
            download_name="portopt-report.pdf",
        )
    except Exception as e:
        logger.error(traceback.format_exc())
        return jsonify({"error": str(e)}), 500
