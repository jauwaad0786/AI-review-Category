import mysql.connector
from mysql.connector import pooling
from dotenv import load_dotenv
import os

load_dotenv()

# Connection pool - production me baar baar connect nahi karna
_pool = pooling.MySQLConnectionPool(
    pool_name="easemydeal_pool",
    pool_size=5,
    host=os.getenv("DB_HOST", "localhost"),
    user=os.getenv("DB_USER", "root"),
    password=os.getenv("DB_PASSWORD", "root123"),
    database=os.getenv("DB_NAME", "easemydeal_reviews"),
    autocommit=False
)

def get_connection():
    return _pool.get_connection()
