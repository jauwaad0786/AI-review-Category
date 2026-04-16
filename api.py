import time
from flask import Flask, jsonify, request
from flask_cors import CORS
from db import get_connection
from seller_analysis import analyze_seller          # moved to top — was inside route

app = Flask(__name__)
CORS(app)

# ─────────────────────────────────────────────
# SIMPLE TTL CACHE — seller summary is hot endpoint
# Avoids repeated DB hits for same seller within 60s
# Thread-safe reads, last-write-wins on updates (acceptable)
# ─────────────────────────────────────────────
_cache: dict = {}                                   # {key: (value, expires_at)}
_CACHE_TTL   = 60                                   # seconds


def _cache_get(key: str):
    entry = _cache.get(key)
    if entry and time.time() < entry[1]:
        return entry[0]
    _cache.pop(key, None)
    return None


def _cache_set(key: str, value, ttl: int = _CACHE_TTL):
    _cache[key] = (value, time.time() + ttl)


def _cache_del(key: str):
    _cache.pop(key, None)


# ─────────────────────────────────────────────
# POST /api/reviews
# New review (goes to pending)
# ─────────────────────────────────────────────
@app.route("/api/reviews", methods=["POST"])
def add_review():
    data = request.get_json()

    seller_profile_id   = data.get("seller_profile_id")
    user_id     = data.get("user_id")
    comment = data.get("comment", "").strip()
    rating = int(data.get("rating", 3))

    if not seller_profile_id or not user_id or not comment or not (1 <= rating <= 5):
        return jsonify({"error": "Invalid input"}), 400

    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO reviews (seller_profile_id, user_id, comment, rating, status, is_processed)
            VALUES (%s, %s, %s, %s, 0, 0)
        """, (seller_profile_id, user_id, comment, rating))
        conn.commit()
        new_id = cursor.lastrowid
        cursor.close()
    finally:
        conn.close()

    # Invalidate summary cache when new review arrives
    _cache_del(f"summary:{seller_profile_id}")

    return jsonify({
        "message": "Review submitted (pending approval)",
        "review_id": new_id
    }), 201


# ─────────────────────────────────────────────
# GET /api/reviews/pending
# Admin: see pending reviews
# ─────────────────────────────────────────────
@app.route("/api/reviews/pending", methods=["GET"])
def get_pending_reviews():
    conn = get_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT * FROM reviews
            WHERE status=0
            ORDER BY created_at DESC
            LIMIT 50
        """)
        rows = cursor.fetchall()
        cursor.close()
    finally:
        conn.close()

    return jsonify(rows)


# ─────────────────────────────────────────────
# POST /api/review/<id>/approve
# ─────────────────────────────────────────────
@app.route("/api/review/<int:review_id>/approve", methods=["POST"])
def approve_review(review_id):
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE reviews SET status=1 WHERE id=%s",
            (review_id,)
        )
        conn.commit()

        # Also invalidate seller's summary cache
        cursor.execute("SELECT seller_profile_id FROM reviews WHERE id=%s", (review_id,))
        row = cursor.fetchone()
        if row:
            _cache_del(f"summary:{row[0]}")
        cursor.close()
    finally:
        conn.close()

    return jsonify({"message": "Review approved"})


# ─────────────────────────────────────────────
# POST /api/review/<id>/reject
# ─────────────────────────────────────────────
@app.route("/api/review/<int:review_id>/reject", methods=["POST"])
def reject_review(review_id):
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE reviews SET status=2 WHERE id=%s",
            (review_id,)
        )
        conn.commit()
        cursor.close()
    finally:
        conn.close()

    return jsonify({"message": "Review rejected"})


# ─────────────────────────────────────────────
# GET /api/seller/<seller_profile_id>/summary
# Main dashboard API — CACHED (60s TTL)
# ─────────────────────────────────────────────
@app.route("/api/seller/<int:seller_profile_id>/summary", methods=["GET"])
def seller_summary(seller_profile_id):
    cache_key = f"summary:{seller_profile_id}"
    cached = _cache_get(cache_key)
    if cached:
        return jsonify(cached)

    conn = get_connection()
    try:
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT avg_rating, total_reviews
            FROM tbl_seller_rating
            WHERE seller_profile_id=%s
        """, (seller_profile_id,))
        overall = cursor.fetchone() or {"avg_rating": 0, "total_reviews": 0}

        cursor.execute("""
            SELECT category, avg_star
            FROM tbl_seller_category_rating
            WHERE seller_profile_id=%s
        """, (seller_profile_id,))
        categories = cursor.fetchall()
        cursor.close()
    finally:
        conn.close()

    result = {
        "seller_profile_id":      seller_profile_id,
        "overall_rating": float(overall["avg_rating"]),
        "total_reviews":  int(overall["total_reviews"]),
        "categories":     {c["category"]: float(c["avg_star"]) for c in categories}
    }
    _cache_set(cache_key, result)
    return jsonify(result)


# ─────────────────────────────────────────────
# GET /api/seller/<seller_profile_id>/reviews
# Approved reviews + categories
# ─────────────────────────────────────────────
@app.route("/api/seller/<int:seller_profile_id>/reviews", methods=["GET"])
def seller_reviews(seller_profile_id):
    conn = get_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT
                r.id,
                r.user_id,
                r.comment,
                r.rating,
                r.created_at,
                GROUP_CONCAT(ra.category     ORDER BY ra.id SEPARATOR '||') AS categories,
                GROUP_CONCAT(ra.category_star ORDER BY ra.id SEPARATOR '||') AS category_stars
            FROM reviews r
            LEFT JOIN review_analysis ra ON ra.review_id = r.id
            WHERE r.seller_profile_id = %s AND r.status=1
            GROUP BY r.id
            ORDER BY r.created_at DESC
            LIMIT 50
        """, (seller_profile_id,))
        rows = cursor.fetchall()
        cursor.close()
    finally:
        conn.close()

    result = []
    for row in rows:
        cats = []
        if row["categories"]:
            names = row["categories"].split("||")
            stars = row["category_stars"].split("||")
            cats  = [{"category": n, "star": int(s)} for n, s in zip(names, stars)]
        result.append({
            "id":          row["id"],
            "user_id":     row["user_id"],
            "comment": row["comment"],
            "rating": row["rating"],
            "created_at":  row["created_at"].strftime("%Y-%m-%d %H:%M:%S"),
            "categories":  cats
        })

    return jsonify(result)


# ─────────────────────────────────────────────
# GET /api/stats
# ─────────────────────────────────────────────
@app.route("/api/stats", methods=["GET"])
def get_stats():
    conn = get_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT COUNT(*) as total FROM reviews")
        total = cursor.fetchone()["total"]
        cursor.execute(
            "SELECT COUNT(*) as pending FROM reviews WHERE status=0"
        )
        pending = cursor.fetchone()["pending"]
        cursor.close()
    finally:
        conn.close()

    return jsonify({"total_reviews": total, "pending_reviews": pending})


# ─────────────────────────────────────────────
# GET /api/sellers
# All sellers with review count
# ─────────────────────────────────────────────
@app.route("/api/sellers", methods=["GET"])
def get_sellers():
    conn = get_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT
                r.seller_profile_id AS seller_profile_id,
                COUNT(r.id) AS total_reviews,
                ROUND(AVG(r.rating), 1) AS avg_rating,
                SUM(CASE WHEN r.status = 1 THEN 1 ELSE 0 END) AS approved,
                SUM(CASE WHEN r.status = 2 THEN 1 ELSE 0 END) AS rejected,
                SUM(CASE WHEN r.status = 0 THEN 1 ELSE 0 END) AS pending
            FROM reviews r
            GROUP BY r.seller_profile_id
            ORDER BY r.seller_profile_id ASC
        """)
        rows = cursor.fetchall()
        cursor.close()
    finally:
        conn.close()

    for r in rows:
        r['avg_rating'] = round(float(r['avg_rating'] or 0), 1)
    return jsonify(rows)


# ─────────────────────────────────────────────
# GET /api/reviews/rejected
# ─────────────────────────────────────────────
@app.route("/api/reviews/rejected", methods=["GET"])
def get_rejected():
    seller_profile_id = request.args.get("seller_profile_id")
    conn = get_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        if seller_profile_id:
            cursor.execute("""
                SELECT id, seller_profile_id, user_id, comment,
                    rating, status, reject_reason, created_at
                FROM reviews
                WHERE status = 2 AND seller_profile_id = %s
                ORDER BY created_at DESC LIMIT 50
            """, (seller_profile_id,))
            rows = cursor.fetchall()
        else:
            cursor.execute("""
                SELECT id, seller_profile_id, user_id, comment,
                    rating, status, reject_reason, created_at
                FROM reviews
                WHERE status = 2
                ORDER BY created_at DESC LIMIT 50
            """)
            rows = cursor.fetchall()

        cursor.close()
    finally:
        conn.close()

    for r in rows:
        r['created_at'] = r['created_at'].strftime("%Y-%m-%d %H:%M:%S")
    return jsonify(rows)


# ─────────────────────────────────────────────
# GET /api/sellers/list
# Dropdown — id + name
# ─────────────────────────────────────────────
@app.route("/api/sellers/list", methods=["GET"])
def get_sellers_list():
    conn = get_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT DISTINCT seller_profile_id AS seller_profile_id
            FROM reviews
            ORDER BY seller_profile_id ASC
        """)
        rows = cursor.fetchall()
        cursor.close()
    finally:
        conn.close()

    return jsonify([r["seller_profile_id"] for r in rows])


# ─────────────────────────────────────────────
# GET /api/seller/<id>/deep-analysis
# Seller intent + dynamic categories (heavy — NOT cached, on-demand)
# ─────────────────────────────────────────────
@app.route("/api/seller/<int:seller_profile_id>/deep-analysis", methods=["GET"])
def seller_deep_analysis(seller_profile_id):
    conn = get_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT user_id, comment, rating, created_at
            FROM reviews
            WHERE seller_profile_id = %s AND status = 1
            ORDER BY created_at DESC
            LIMIT 40
        """, (seller_profile_id,))
        rows = cursor.fetchall()
        cursor.close()
    finally:
        conn.close()

    for r in rows:
        if r['created_at']:
            r['created_at'] = r['created_at'].strftime("%Y-%m-%d %H:%M:%S")

    result = analyze_seller(seller_profile_id, rows)
    return jsonify(result)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)