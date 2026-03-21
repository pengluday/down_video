"""
数据库模块
包含IP限流等数据操作
License Key系统不需要用户表
"""

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from models import RateLimitRecord


DB_PATH = Path(__file__).parent / "data" / "rate_limit.db"
DB_PATH.parent.mkdir(exist_ok=True)


def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_database():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ip_rate_limits (
            ip_address TEXT PRIMARY KEY,
            window_start TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            request_count INTEGER DEFAULT 0,
            download_count INTEGER DEFAULT 0
        )
    """)
    
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ip_limits_window ON ip_rate_limits(window_start)")
    
    conn.commit()
    conn.close()


def check_ip_rate_limit(ip_address: str, window_minutes: int = 60) -> RateLimitRecord:
    conn = get_db_connection()
    cursor = conn.cursor()
    
    window_start = datetime.utcnow() - timedelta(minutes=window_minutes)
    
    cursor.execute("""
        SELECT * FROM ip_rate_limits WHERE ip_address = ?
    """, (ip_address,))
    
    row = cursor.fetchone()
    
    if row:
        record_window = datetime.fromisoformat(row['window_start'])
        if record_window < window_start:
            cursor.execute("""
                UPDATE ip_rate_limits 
                SET window_start = CURRENT_TIMESTAMP,
                    request_count = 0,
                    download_count = 0
                WHERE ip_address = ?
            """, (ip_address,))
            conn.commit()
            conn.close()
            
            return RateLimitRecord(
                key=ip_address,
                window_start=datetime.utcnow(),
                request_count=0,
                download_count=0
            )
        else:
            conn.close()
            return RateLimitRecord(
                key=ip_address,
                window_start=record_window,
                request_count=row['request_count'],
                download_count=row['download_count']
            )
    else:
        cursor.execute("""
            INSERT INTO ip_rate_limits (ip_address, window_start, request_count, download_count)
            VALUES (?, CURRENT_TIMESTAMP, 0, 0)
        """, (ip_address,))
        conn.commit()
        conn.close()
        
        return RateLimitRecord(
            key=ip_address,
            window_start=datetime.utcnow(),
            request_count=0,
            download_count=0
        )


def increment_ip_request_count(ip_address: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT INTO ip_rate_limits (ip_address, window_start, request_count, download_count)
        VALUES (?, CURRENT_TIMESTAMP, 1, 0)
        ON CONFLICT(ip_address) DO UPDATE SET
            request_count = request_count + 1
    """, (ip_address,))
    
    conn.commit()
    conn.close()


def increment_ip_download_count(ip_address: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT INTO ip_rate_limits (ip_address, window_start, request_count, download_count)
        VALUES (?, CURRENT_TIMESTAMP, 0, 1)
        ON CONFLICT(ip_address) DO UPDATE SET
            download_count = download_count + 1
    """, (ip_address,))
    
    conn.commit()
    conn.close()


init_database()
