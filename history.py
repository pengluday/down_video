"""
下载历史记录数据库模块
使用SQLite存储下载历史，自动清理过期记录
"""

import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional
from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass
class HistoryRecord:
    download_time: float
    video_title: str
    file_size: int
    download_url: str
    platform: str = "unknown"
    duration: Optional[int] = None
    client_id: str = ""


class HistoryDB:
    def __init__(self, db_path: str = "history.db"):
        self.db_path = db_path
        self.lock = threading.Lock()
        self._init_db()
    
    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            # 检查表结构，添加client_id字段（如果不存在）
            cursor.execute("PRAGMA table_info(download_history)")
            columns = [column[1] for column in cursor.fetchall()]
            
            if "client_id" not in columns:
                cursor.execute("""
                    ALTER TABLE download_history
                    ADD COLUMN client_id TEXT DEFAULT ''
                """)
                conn.commit()
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS download_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    download_time REAL NOT NULL,
                    video_title TEXT NOT NULL,
                    file_size INTEGER NOT NULL,
                    download_url TEXT NOT NULL,
                    platform TEXT DEFAULT 'unknown',
                    duration INTEGER,
                    client_id TEXT DEFAULT '',
                    created_at REAL NOT NULL
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_download_time 
                ON download_history(download_time DESC)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_client_id 
                ON download_history(client_id)
            """)
            conn.commit()
    
    def add_record(
        self,
        video_title: str,
        file_size: int,
        download_url: str,
        platform: str = "unknown",
        duration: Optional[int] = None,
        client_id: str = ""
    ) -> int:
        with self.lock:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                current_time = time.time()
                cursor.execute("""
                    INSERT INTO download_history 
                    (download_time, video_title, file_size, download_url, platform, duration, client_id, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (current_time, video_title, file_size, download_url, platform, duration, client_id, current_time))
                conn.commit()
                return cursor.lastrowid
    
    def get_records(self, limit: int = 100) -> list[dict]:
        with self.lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT * FROM download_history
                    ORDER BY download_time DESC
                    LIMIT ?
                """, (limit,))
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
    
    def get_records_by_client(self, client_id: str, limit: int = 100) -> list[dict]:
        with self.lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT * FROM download_history
                    WHERE client_id = ?
                    ORDER BY download_time DESC
                    LIMIT ?
                """, (client_id, limit))
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
    
    def delete_old_records(self, days: int = 7) -> int:
        with self.lock:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cutoff_time = time.time() - (days * 24 * 60 * 60)
                cursor.execute("""
                    DELETE FROM download_history
                    WHERE download_time < ?
                """, (cutoff_time,))
                deleted_count = cursor.rowcount
                conn.commit()
                return deleted_count
    
    def get_stats(self) -> dict:
        with self.lock:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM download_history")
                total_records = cursor.fetchone()[0]
                
                cursor.execute("SELECT SUM(file_size) FROM download_history")
                total_size = cursor.fetchone()[0] or 0
                
                return {
                    "total_records": total_records,
                    "total_size": total_size
                }
    
    def get_client_stats(self, client_id: str) -> dict:
        with self.lock:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM download_history WHERE client_id = ?", (client_id,))
                total_records = cursor.fetchone()[0]
                
                cursor.execute("SELECT SUM(file_size) FROM download_history WHERE client_id = ?", (client_id,))
                total_size = cursor.fetchone()[0] or 0
                
                return {
                    "client_id": client_id,
                    "total_records": total_records,
                    "total_size": total_size
                }


HISTORY_DB_PATH = Path(__file__).parent / "data" / "history.db"
HISTORY_DB_PATH.parent.mkdir(exist_ok=True)

history_db = HistoryDB(str(HISTORY_DB_PATH))


def cleanup_old_records():
    deleted = history_db.delete_old_records(days=7)
    if deleted > 0:
        logger.info(f"已清理 {deleted} 条过期历史记录")


def start_cleanup_scheduler():
    def cleanup_loop():
        while True:
            time.sleep(60 * 60)
            try:
                cleanup_old_records()
            except Exception as e:
                logger.error(f"清理历史记录失败: {e}")
    
    thread = threading.Thread(target=cleanup_loop, daemon=True)
    thread.start()
    logger.info("历史记录清理调度器已启动")


logger = logging.getLogger(__name__)