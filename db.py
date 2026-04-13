import time
import mysql.connector
from mysql.connector import pooling, errors
from dotenv import load_dotenv
import os

load_dotenv()

# ─────────────────────────────────────────────
# Connection Pool — 5 → 30 for 50-200 concurrent users
# pool_reset_session=True  → stale connections auto-cleaned
# ─────────────────────────────────────────────
_pool = pooling.MySQLConnectionPool(
    pool_name="easemydeal_pool",
    pool_size=30,                                   # was 5
    pool_reset_session=True,                        # NEW — cleans dirty sessions
    host=os.getenv("DB_HOST", "localhost"),
    user=os.getenv("DB_USER", "root"),
    password=os.getenv("DB_PASSWORD", "root123"),
    database=os.getenv("DB_NAME", "easemydeal_reviews"),
    autocommit=False,
    connection_timeout=10,                          # NEW — don't hang forever
    use_pure=True,
)


def get_connection(retries: int = 3, delay: float = 0.3):
    """
    Get a pooled connection.
    Retries on PoolExhausted (busy burst) with small backoff.
    """
    last_err = None
    for attempt in range(retries):
        try:
            return _pool.get_connection()
        except errors.PoolExhaustedError as e:
            last_err = e
            if attempt < retries - 1:
                time.sleep(delay * (attempt + 1))   # 0.3s, 0.6s, 0.9s
    raise last_err