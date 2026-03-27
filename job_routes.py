"""
job_routes.py
app.py dosyanıza şu satırları ekleyin:

    from job_routes import job_bp
    app.register_blueprint(job_bp)

Sonra bu dosyayı proje kök dizinine koyun.
"""

from flask import Blueprint, request, jsonify, session
from job_analyzer import JobAnalyzer
import config
from config import DB_CONFIG

job_bp = Blueprint("job", __name__)


def _get_analyzer() -> JobAnalyzer:
    return JobAnalyzer(DB_CONFIG, config.api_key)


# -----------------------------------------------------------------------
# POST /api/analyze-job
# Body: { "source": "<URL veya ham metin>" }
# -----------------------------------------------------------------------
@job_bp.route("/api/analyze-job", methods=["POST"])
def analyze_job():
    if "user_id" not in session:
        return jsonify({"success": False, "error": "Oturum açmanız gerekiyor"}), 401

    data = request.get_json(silent=True) or {}
    source = (data.get("source") or "").strip()

    if not source:
        return jsonify({"success": False, "error": "İş ilanı URL'si veya metni gerekli"}), 400

    analyzer = _get_analyzer()
    try:
        result = analyzer.run(user_id=session["user_id"], source=source)
        return jsonify({"success": True, **result})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500
    finally:
        analyzer.disconnect()


# -----------------------------------------------------------------------
# GET /api/user-jobs
# -----------------------------------------------------------------------
@job_bp.route("/api/user-jobs", methods=["GET"])
def list_user_jobs():
    if "user_id" not in session:
        return jsonify({"success": False, "error": "Oturum açmanız gerekiyor"}), 401

    analyzer = _get_analyzer()
    try:
        jobs = analyzer.get_user_jobs(session["user_id"])
        return jsonify({"success": True, "jobs": jobs})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500
    finally:
        analyzer.disconnect()


# -----------------------------------------------------------------------
# GET /api/job-detail/<id>
# -----------------------------------------------------------------------
@job_bp.route("/api/job-detail/<int:job_analysis_id>", methods=["GET"])
def job_detail(job_analysis_id):
    if "user_id" not in session:
        return jsonify({"success": False, "error": "Oturum açmanız gerekiyor"}), 401

    analyzer = _get_analyzer()
    try:
        job = analyzer.get_job_detail(job_analysis_id, session["user_id"])
        if not job:
            return jsonify({"success": False, "error": "İlan bulunamadı"}), 404
        return jsonify({"success": True, "job": job})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500
    finally:
        analyzer.disconnect()


# -----------------------------------------------------------------------
# PATCH /api/job-detail/<id>
# Eksik alanları kullanıcı cevabıyla tamamlar
# Body: { "field": "value", ... }
# Örnek: { "location_city": "İstanbul", "edu_min_level": "bachelor" }
# -----------------------------------------------------------------------
@job_bp.route("/api/job-detail/<int:job_analysis_id>", methods=["PATCH"])
def update_job(job_analysis_id):
    if "user_id" not in session:
        return jsonify({"success": False, "error": "Oturum açmanız gerekiyor"}), 401

    data = request.get_json(silent=True) or {}
    if not data:
        return jsonify({"success": False, "error": "Güncellenecek alan gönderilmedi"}), 400

    ALLOWED = {
        "job_title", "department", "employment_type", "company_name",
        "location_city", "location_district", "location_country",
        "is_remote", "work_type",
        "exp_min_years", "exp_max_years", "exp_description",
        "edu_min_level", "edu_description",
        "salary_min", "salary_max", "salary_currency", "salary_negotiable",
    }

    filtered = {k: v for k, v in data.items() if k in ALLOWED}
    if not filtered:
        return jsonify({"success": False, "error": "Geçerli alan bulunamadı"}), 400

    analyzer = _get_analyzer()
    try:
        import mysql.connector
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor()

        set_clause = ", ".join(f"{k} = %s" for k in filtered)
        values = list(filtered.values()) + [job_analysis_id, session["user_id"]]
        cursor.execute(
            f"UPDATE job_analyses SET {set_clause}, missing_fields = '[]', "
            f"completeness_score = 100 "
            f"WHERE job_analysis_id = %s AND user_id = %s",
            values,
        )
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"success": True, "updated": list(filtered.keys())})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 500
    finally:
        analyzer.disconnect()