from flask import Flask, request, jsonify
from database import get_connection
import uuid
from datetime import datetime, timedelta

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

app = Flask(__name__)

# ==============================
# 🔥 RATE LIMITER
# ==============================
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per minute"]
)

# ==============================
# 🔐 SECURITY HEADERS
# ==============================
@app.after_request
def add_security_headers(response):

    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Server"] = "Secure-Flask-API"

    return response


# ==============================
# 🟢 HOME
# ==============================
@app.route("/")
def home():

    return jsonify({
        "status": "ok",
        "message": "Backend running 🚀"
    })


# ==============================
# 🟢 HEALTH
# ==============================
@app.route("/health")
def health():

    return jsonify({
        "status": "healthy"
    })


# ==============================
# 🟢 START CHALLENGE
# ==============================
@limiter.limit("10 per minute")
@app.route("/start-challenge", methods=["GET"])
def start_challenge():

    conn = get_connection()
    cursor = conn.cursor()

    try:

        # 🔐 Generate token
        public_id = str(uuid.uuid4())

        # ⏳ Token expires after 120s
        expires_at = datetime.now() + timedelta(seconds=120)

        cursor.execute("""
            INSERT INTO captcha_challenges
            (
                public_id,
                challenge_type,
                difficulty_level,
                params_json,
                expires_at
            )
            VALUES (%s, %s, %s, %s, %s)
        """, (
            public_id,
            "VR_PUZZLE",
            1,
            "{}",
            expires_at
        ))

        conn.commit()

        return jsonify({
            "challenge_token": public_id,
            "expires_at": expires_at.isoformat(),
            "type": "VR_PUZZLE"
        })

    except Exception as e:

        conn.rollback()

        return jsonify({
            "error": str(e)
        }), 500

    finally:

        cursor.close()
        conn.close()


# ==============================
# 🧠 SUBMIT RESULT
# ==============================
@limiter.limit("30 per minute")
@app.route("/submit-result", methods=["POST"])
def submit_result():

    data = request.get_json()

    challenge_token = data.get("challenge_token")

    solve_time = data.get("solveTime")

    retry_attempts = data.get("retryAttempts")

    wrong_placements = data.get("wrongPlacements")

    # ==============================
    # 🛡️ VALIDATION
    # ==============================
    if challenge_token is None:

        return jsonify({
            "error": "missing token"
        }), 400

    if not isinstance(solve_time, (int, float)):

        return jsonify({
            "error": "invalid solveTime"
        }), 400

    if not isinstance(retry_attempts, int):

        return jsonify({
            "error": "invalid retryAttempts"
        }), 400

    if not isinstance(wrong_placements, int):

        return jsonify({
            "error": "invalid wrongPlacements"
        }), 400

    if solve_time <= 0 or solve_time > 300:

        return jsonify({
            "error": "invalid solve_time range"
        }), 400

    if retry_attempts < 0 or retry_attempts > 10:

        return jsonify({
            "error": "invalid retry_attempts range"
        }), 400

    if wrong_placements < 0 or wrong_placements > 100:

        return jsonify({
            "error": "invalid wrong_placements range"
        }), 400

    conn = get_connection()
    cursor = conn.cursor()

    try:

        # ==============================
        # 🔐 VERIFY TOKEN
        # ==============================
        cursor.execute("""
            SELECT
                challenge_id,
                is_used,
                expires_at
            FROM captcha_challenges
            WHERE public_id = %s
        """, (challenge_token,))

        challenge = cursor.fetchone()

        if challenge is None:

            return jsonify({
                "error": "invalid token"
            }), 403

        challenge_id, is_used, expires_at = challenge

        # ==============================
        # ❌ REPLAY PROTECTION
        # ==============================
        if is_used:

            return jsonify({
                "error": "replay detected"
            }), 403

        # ==============================
        # ❌ EXPIRATION CHECK
        # ==============================
        if datetime.now() > expires_at:

            return jsonify({
                "error": "challenge expired"
            }), 403

        # ==============================
        # 🧠 SERVER DECISION LOGIC
        # ==============================

        # 🤖 suspiciously fast
        if solve_time < 2:

            decision = "BOT_DETECTED"
            score = 0.1

        # ❌ too many retries
        elif retry_attempts >= 3:

            decision = "FAIL"
            score = 0.3

        # ❌ too many wrong placements
        elif wrong_placements >= 5:

            decision = "FAIL"
            score = 0.3

        # ❌ timeout
        elif solve_time >= 30:

            decision = "FAIL"
            score = 0.2

        # ✅ normal human behavior
        else:

            decision = "PASS"
            score = 0.9

        # ==============================
        # 💾 SAVE RESULT
        # ==============================
        cursor.execute("""
            INSERT INTO captcha_results
            (
                challenge_id,
                completion_time,
                behavior_score,
                retry_attempts,
                wrong_placements,
                decision
            )
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (
            challenge_id,
            solve_time,
            score,
            retry_attempts,
            wrong_placements,
            decision
        ))

        result_id = cursor.lastrowid

        # ==============================
        # 📊 BEHAVIOR METRICS
        # ==============================
        reaction_time = solve_time / max(
            wrong_placements,
            1
        )

        movement_smoothness = 0.85

        path_deviation = 0.25

        error_count = wrong_placements

        cursor.execute("""
            INSERT INTO behavior_metrics
            (
                result_id,
                reaction_time,
                movement_smoothness,
                path_deviation,
                error_count
            )
            VALUES (%s, %s, %s, %s, %s)
        """, (
            result_id,
            reaction_time,
            movement_smoothness,
            path_deviation,
            error_count
        ))

        # ==============================
        # 🔐 MARK TOKEN USED
        # ==============================
        cursor.execute("""
            UPDATE captcha_challenges
            SET is_used = TRUE
            WHERE challenge_id = %s
        """, (challenge_id,))

        conn.commit()

        return jsonify({
            "decision": decision,
            "behavior_score": score
        })

    except Exception as e:

        conn.rollback()

        return jsonify({
            "error": str(e)
        }), 500

    finally:

        cursor.close()
        conn.close()


# ==============================
# 🚀 RUN SERVER
# ==============================
if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True
    )