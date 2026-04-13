import time
import os
from datetime import datetime
from dotenv import load_dotenv
from db import get_connection
from gemini_client import analyze_review
from moderator import moderate_review

load_dotenv()
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", 5))


# ─────────────────────────────────────────────
# FETCH PENDING — moderation queue
# ─────────────────────────────────────────────
def fetch_pending(conn):
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT id, seller_id, user_id, review_text, star_rating
        FROM reviews
        WHERE status = 'pending'
        ORDER BY created_at ASC
        LIMIT 20
    """)
    rows = cursor.fetchall()
    cursor.close()
    return rows


# ─────────────────────────────────────────────
# FETCH APPROVED + UNPROCESSED — AI queue
# ─────────────────────────────────────────────
def fetch_approved_unprocessed(conn):
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT id, seller_id, review_text, star_rating
        FROM reviews
        WHERE status = 'approved' AND is_processed = FALSE
        ORDER BY created_at ASC
        LIMIT 20
    """)
    rows = cursor.fetchall()
    cursor.close()
    return rows


# ─────────────────────────────────────────────
# UPDATE review STATUS
# ─────────────────────────────────────────────
def update_status(conn, review_id: int, status: str, reason: str = ""):
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE reviews SET status=%s WHERE id=%s",
        (status, review_id)
    )
    cursor.close()


# ─────────────────────────────────────────────
# INSERT INTO review_analysis (3 rows per review)
# ─────────────────────────────────────────────
def insert_analysis(conn, review_id: int, seller_id: int, categories: list):
    cursor = conn.cursor()
    now = datetime.now()
    for item in categories:
        if not isinstance(item, dict):
            continue
        if "category" not in item or "category_star" not in item:
            continue

        cursor.execute("""
            INSERT INTO review_analysis
                (review_id, seller_id, category, category_star, processed_at)
            VALUES (%s, %s, %s, %s, %s)
        """, (review_id, seller_id, item["category"], item["category_star"], now))
    cursor.close()


# ─────────────────────────────────────────────
# UPDATE tbl_seller_category_rating — INCREMENTAL
# ─────────────────────────────────────────────
def update_seller_category_rating(conn, seller_id: int, categories: list):
    cursor = conn.cursor(dictionary=True)

    for item in categories:
        if not isinstance(item, dict):
            print("  ⚠ Skipping invalid item:", item)
            continue

        if "category" not in item or "category_star" not in item:
            print("  ⚠ Missing keys:", item)
            continue

        cat = str(item["category"]).strip()
        new_star = int(item["category_star"])

        # optional safety
        new_star = max(1, min(5, new_star))

        cursor.execute("""
            SELECT avg_star, total_reviews
            FROM tbl_seller_category_rating
            WHERE seller_id=%s AND category=%s
        """, (seller_id, cat))
        row = cursor.fetchone()

        if row:
            old_avg   = float(row["avg_star"])
            old_count = int(row["total_reviews"])
            new_avg   = round((old_avg * old_count + new_star) / (old_count + 1), 2)
            cursor.execute("""
                UPDATE tbl_seller_category_rating
                SET avg_star=%s, total_reviews=%s
                WHERE seller_id=%s AND category=%s
            """, (new_avg, old_count + 1, seller_id, cat))
        else:
            cursor.execute("""
                INSERT INTO tbl_seller_category_rating
                    (seller_id, category, avg_star, total_reviews)
                VALUES (%s, %s, %s, 1)
            """, (seller_id, cat, new_star))

    cursor.close()


# ─────────────────────────────────────────────
# UPDATE tbl_seller_rating — OVERALL INCREMENTAL
# ─────────────────────────────────────────────
def update_seller_rating(conn, seller_id: int, star_rating: int):
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT avg_rating, total_reviews
        FROM tbl_seller_rating
        WHERE seller_id=%s
    """, (seller_id,))
    row = cursor.fetchone()

    if row:
        old_avg   = float(row["avg_rating"])
        old_count = int(row["total_reviews"])
        new_avg   = round((old_avg * old_count + star_rating) / (old_count + 1), 2)
        cursor.execute("""
            UPDATE tbl_seller_rating
            SET avg_rating=%s, total_reviews=%s
            WHERE seller_id=%s
        """, (new_avg, old_count + 1, seller_id))
    else:
        cursor.execute("""
            INSERT INTO tbl_seller_rating (seller_id, avg_rating, total_reviews)
            VALUES (%s, %s, 1)
        """, (seller_id, star_rating))

    cursor.close()


# ─────────────────────────────────────────────
# MARK PROCESSED
# ─────────────────────────────────────────────
def mark_processed(conn, review_id: int):
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE reviews SET is_processed=TRUE WHERE id=%s",
        (review_id,)
    )
    cursor.close()


# ─────────────────────────────────────────────
# STEP 1 — MODERATION
# ─────────────────────────────────────────────
def run_moderation(review: dict):
    review_id   = review["id"]
    review_text = review["review_text"]
    star_rating = review["star_rating"]

    print(f"[{datetime.now().strftime('%H:%M:%S')}] Moderating id={review_id}")

    status, reason = moderate_review(review_text, star_rating)

    conn = get_connection()
    try:
        update_status(conn, review_id, status, reason)
        conn.commit()
        icon = "✓ APPROVED" if status == "approved" else "✗ REJECTED"
        print(f"  {icon} | {reason}\n")
    except Exception as e:
        conn.rollback()
        print(f"  DB Error: {e}\n")
    finally:
        conn.close()


# ─────────────────────────────────────────────
# STEP 2 — AI CATEGORIZATION
# ─────────────────────────────────────────────
def run_categorization(review: dict):
    review_id   = review["id"]
    seller_id   = review["seller_id"]
    review_text = review["review_text"]
    star_rating = review["star_rating"]

    print(f"[{datetime.now().strftime('%H:%M:%S')}] Categorizing id={review_id} seller={seller_id}")

    try:
        categories = analyze_review(review_text, star_rating)
    except Exception as e:
        print(f"  analyze_review crashed: {e}")
        categories = []

    if not isinstance(categories, list) or len(categories) == 0:
        categories = [{"category": "Overall Experience", "category_star": star_rating}]

    safe_categories = []
    for cat in categories:
        if not isinstance(cat, dict):
            continue
        if "category" not in cat or "category_star" not in cat:
            continue
        safe_categories.append({
            "category": str(cat["category"])[:150],
            "category_star": int(max(1, min(5, cat["category_star"])))
        })

    if not safe_categories:
        safe_categories = [{"category": "Overall Experience", "category_star": star_rating}]

    print(f"  Inserting: {safe_categories}")

    conn = get_connection()
    try:
        insert_analysis(conn, review_id, seller_id, safe_categories)
        update_seller_category_rating(conn, seller_id, safe_categories)
        update_seller_rating(conn, seller_id, star_rating)
        mark_processed(conn, review_id)
        conn.commit()
        print(f"  ✓ Done\n")
    except Exception as e:
        conn.rollback()
        print(f"  ✗ DB Error: {e}\n")
        # Phir bhi mark processed karo taaki infinite loop band ho
        try:
            mark_processed(conn, review_id)
            conn.commit()
        except:
            pass
    finally:
        conn.close()


# ─────────────────────────────────────────────
# MAIN LOOP
# ─────────────────────────────────────────────
def run_worker():
    print("=" * 52)
    print("  easeMyDeal Review Worker — STARTED")
    print(f"  Poll every {POLL_INTERVAL}s | 3 fixed categories")
    print("  Step 1: Moderate → Step 2: AI Categorize")
    print("=" * 52)

    while True:
        try:
            conn = get_connection()
            pending       = fetch_pending(conn)
            to_categorize = fetch_approved_unprocessed(conn)
            conn.close()

            if pending:
                print(f"\n[Worker] {len(pending)} pending moderation")
                for r in pending:
                    run_moderation(r)

            if to_categorize:
                print(f"\n[Worker] {len(to_categorize)} approved → categorize")
                for r in to_categorize:
                    run_categorization(r)

            if not pending and not to_categorize:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] idle... ({POLL_INTERVAL}s)")

        except Exception as e:
            print(f"[Worker Error] {e}")

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    run_worker()