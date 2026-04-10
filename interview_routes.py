"""
interview_routes.py
Mülakat sistemi Flask Blueprint route'ları.
"""

from flask import Blueprint, request, jsonify, session
import mysql.connector
from interview_engine import InterviewEngine
import config
from config import DB_CONFIG

interview_bp = Blueprint("interview", __name__)


def _engine() -> InterviewEngine:
    return InterviewEngine(DB_CONFIG, config.api_key)


def _get_db():
    return mysql.connector.connect(**DB_CONFIG)


# ---------------------------------------------------------------------------
# POST /api/interview/start
# Body: { job_analysis_id, cv_text_id (opsiyonel), question_count (opsiyonel, default 10) }
# ---------------------------------------------------------------------------
@interview_bp.route("/api/interview/start", methods=["POST"])
def start_interview():
    if "user_id" not in session:
        return jsonify({"success": False, "error": "Oturum açmanız gerekiyor"}), 401

    data  = request.get_json(silent=True) or {}
    job_id = data.get("job_analysis_id")
    cv_text_id = data.get("cv_text_id")
    q_count = min(int(data.get("question_count", 10)), 15)

    if not job_id:
        return jsonify({"success": False, "error": "job_analysis_id gerekli"}), 400

    user_id = session["user_id"]
    conn = _get_db()
    cursor = conn.cursor(dictionary=True)

    try:
        # İş ilanı verisini çek
        cursor.execute("""
            SELECT job_analysis_id, job_title, company_name, department,
                   required_skills, preferred_skills, exp_min_years, exp_max_years,
                   edu_min_level, work_type, employment_type
            FROM job_analyses
            WHERE job_analysis_id=%s AND user_id=%s
        """, (job_id, user_id))
        job_data = cursor.fetchone()
        if not job_data:
            return jsonify({"success": False, "error": "İş ilanı bulunamadı"}), 404

        # CV verisini çek (opsiyonel)
        cv_data = None
        if cv_text_id:
            cursor.execute("""
                SELECT cv_skills, cv_experience, cv_education, cv_languages, cv_address
                FROM cv_analyses
                WHERE user_id=%s AND cv_text_id=%s
                ORDER BY analyzed_at DESC LIMIT 1
            """, (user_id, cv_text_id))
            cv_data = cursor.fetchone()

        # Engine ile oturum oluştur
        engine = _engine()
        try:
            result = engine.create_session(
                user_id, job_id, cv_text_id,
                job_data, cv_data, q_count
            )
        finally:
            engine.disconnect()

        return jsonify({"success": True, **result})

    except Exception as e:
        print(f"[interview/start] Hata: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


# ---------------------------------------------------------------------------
# POST /api/interview/answer
# Body: { question_id, answer }
# ---------------------------------------------------------------------------
@interview_bp.route("/api/interview/answer", methods=["POST"])
def submit_answer():
    if "user_id" not in session:
        return jsonify({"success": False, "error": "Oturum açmanız gerekiyor"}), 401

    data        = request.get_json(silent=True) or {}
    question_id = data.get("question_id")
    answer      = (data.get("answer") or "").strip()

    if not question_id or not answer:
        return jsonify({"success": False, "error": "question_id ve answer gerekli"}), 400

    if len(answer) < 10:
        return jsonify({"success": False, "error": "Cevap çok kısa (en az 10 karakter)"}), 400

    user_id = session["user_id"]
    conn = _get_db()
    cursor = conn.cursor(dictionary=True)

    try:
        # Soru bu kullanıcıya mı ait?
        cursor.execute("""
            SELECT iq.question_id, is2.job_title, is2.company_name
            FROM interview_questions iq
            JOIN interview_sessions is2 ON iq.session_id = is2.session_id
            WHERE iq.question_id=%s AND is2.user_id=%s
        """, (question_id, user_id))
        row = cursor.fetchone()
        if not row:
            return jsonify({"success": False, "error": "Soru bulunamadı"}), 404

        engine = _engine()
        try:
            result = engine.evaluate_answer(
                question_id, answer,
                row["job_title"], row["company_name"]
            )
        finally:
            engine.disconnect()

        return jsonify({"success": True, "evaluation": result})

    except Exception as e:
        print(f"[interview/answer] Hata: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()


# ---------------------------------------------------------------------------
# POST /api/interview/finalize
# Body: { session_id }
# ---------------------------------------------------------------------------
@interview_bp.route("/api/interview/finalize", methods=["POST"])
def finalize_interview():
    if "user_id" not in session:
        return jsonify({"success": False, "error": "Oturum açmanız gerekiyor"}), 401

    data       = request.get_json(silent=True) or {}
    session_id = data.get("session_id")
    if not session_id:
        return jsonify({"success": False, "error": "session_id gerekli"}), 400

    engine = _engine()
    try:
        report = engine.finalize_session(session_id)
        return jsonify({"success": True, "report": report})
    except Exception as e:
        print(f"[interview/finalize] Hata: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        engine.disconnect()


# ---------------------------------------------------------------------------
# GET /api/interview/session/<id>
# ---------------------------------------------------------------------------
@interview_bp.route("/api/interview/session/<int:session_id>", methods=["GET"])
def get_session(session_id):
    if "user_id" not in session:
        return jsonify({"success": False, "error": "Oturum açmanız gerekiyor"}), 401

    engine = _engine()
    try:
        s  = engine.get_session(session_id, session["user_id"])
        qs = engine.get_session_questions(session_id)
        if not s:
            return jsonify({"success": False, "error": "Oturum bulunamadı"}), 404
        return jsonify({"success": True, "session": s, "questions": qs})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        engine.disconnect()


# ---------------------------------------------------------------------------
# GET /api/interview/sessions  (kullanıcının tüm mülakatları)
# ---------------------------------------------------------------------------
@interview_bp.route("/api/interview/sessions", methods=["GET"])
def list_sessions():
    if "user_id" not in session:
        return jsonify({"success": False, "error": "Oturum açmanız gerekiyor"}), 401

    engine = _engine()
    try:
        rows = engine.get_user_sessions(session["user_id"])
        return jsonify({"success": True, "sessions": rows})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        engine.disconnect()