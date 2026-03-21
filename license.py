"""
License Key 系统
使用简单的License Key替代复杂的用户登录系统
"""

import secrets
import string
from datetime import datetime, timedelta
from typing import Optional, Tuple
import sqlite3
from pathlib import Path


# License Key格式：XXXX-XXXX-XXXX-XXXX
LICENSE_KEY_LENGTH = 16
LICENSE_KEY_GROUPS = 4
GROUP_SIZE = LICENSE_KEY_LENGTH // LICENSE_KEY_GROUPS

# 数据库路径
DB_PATH = Path(__file__).parent / "licenses.db"


def generate_license_key() -> str:
    """
    生成License Key
    格式：XXXX-XXXX-XXXX-XXXX
    """
    chars = string.ascii_uppercase + string.digits
    groups = []
    
    for _ in range(LICENSE_KEY_GROUPS):
        group = ''.join(secrets.choice(chars) for _ in range(GROUP_SIZE))
        groups.append(group)
    
    return '-'.join(groups)


def init_license_db():
    """初始化License Key数据库"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS licenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            license_key TEXT UNIQUE NOT NULL,
            tier TEXT NOT NULL DEFAULT 'pro',
            status TEXT NOT NULL DEFAULT 'active',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            activated_at TIMESTAMP,
            expires_at TIMESTAMP,
            stripe_session_id TEXT,
            stripe_customer_id TEXT,
            activation_count INTEGER DEFAULT 0,
            max_activations INTEGER DEFAULT 3,
            last_used TIMESTAMP,
            metadata TEXT
        )
    """)
    
    # 创建索引
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_license_key 
        ON licenses(license_key)
    """)
    
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_status 
        ON licenses(status)
    """)
    
    conn.commit()
    conn.close()


def create_license(
    tier: str = 'pro',
    stripe_session_id: Optional[str] = None,
    stripe_customer_id: Optional[str] = None,
    expires_days: int = 365
) -> Tuple[str, bool]:
    """
    创建新的License Key
    
    Args:
        tier: 订阅等级 (pro, pro_yearly)
        stripe_session_id: Stripe会话ID
        stripe_customer_id: Stripe客户ID
        expires_days: 过期天数
    
    Returns:
        (license_key, success)
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        license_key = generate_license_key()
        
        # 计算过期时间
        created_at = datetime.utcnow()
        expires_at = created_at + timedelta(days=expires_days)
        
        cursor.execute("""
            INSERT INTO licenses (
                license_key, tier, status, created_at,
                expires_at, stripe_session_id, stripe_customer_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            license_key, tier, 'active', created_at,
            expires_at, stripe_session_id, stripe_customer_id
        ))
        
        conn.commit()
        return license_key, True
        
    except sqlite3.IntegrityError:
        # License Key重复，重试
        return create_license(tier, stripe_session_id, stripe_customer_id, expires_days)
    except Exception as e:
        print(f"创建License Key失败: {e}")
        return "", False
    finally:
        conn.close()


def verify_license(license_key: str) -> Tuple[bool, Optional[dict]]:
    """
    验证License Key
    
    Args:
        license_key: License Key
    
    Returns:
        (is_valid, license_info)
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT * FROM licenses 
            WHERE license_key = ? AND status = 'active'
        """, (license_key,))
        
        row = cursor.fetchone()
        
        if not row:
            return False, None
        
        # 检查是否过期
        expires_at = datetime.fromisoformat(row[6]) if row[6] else None
        if expires_at and expires_at < datetime.utcnow():
            # 标记为过期
            cursor.execute("""
                UPDATE licenses SET status = 'expired' 
                WHERE license_key = ?
            """, (license_key,))
            conn.commit()
            return False, None
        
        # 更新最后使用时间
        cursor.execute("""
            UPDATE licenses SET last_used = CURRENT_TIMESTAMP 
            WHERE license_key = ?
        """, (license_key,))
        conn.commit()
        
        # 返回License信息
        license_info = {
            'id': row[0],
            'license_key': row[1],
            'tier': row[2],
            'status': row[3],
            'created_at': row[4],
            'activated_at': row[5],
            'expires_at': row[6],
            'stripe_session_id': row[7],
            'stripe_customer_id': row[8],
            'activation_count': row[9],
            'max_activations': row[10],
            'last_used': row[11]
        }
        
        return True, license_info
        
    except Exception as e:
        print(f"验证License Key失败: {e}")
        return False, None
    finally:
        conn.close()


def activate_license(license_key: str) -> Tuple[bool, str]:
    """
    激活License Key
    
    Args:
        license_key: License Key
    
    Returns:
        (success, message)
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        # 先验证License Key
        is_valid, license_info = verify_license(license_key)
        
        if not is_valid:
            return False, "无效的License Key"
        
        # 检查激活次数
        if license_info['activation_count'] >= license_info['max_activations']:
            return False, "License Key已达到最大激活次数"
        
        # 更新激活信息
        cursor.execute("""
            UPDATE licenses 
            SET activated_at = CURRENT_TIMESTAMP,
                activation_count = activation_count + 1
            WHERE license_key = ?
        """, (license_key,))
        
        conn.commit()
        return True, "激活成功"
        
    except Exception as e:
        print(f"激活License Key失败: {e}")
        return False, f"激活失败: {str(e)}"
    finally:
        conn.close()


def get_license_info(license_key: str) -> Optional[dict]:
    """
    获取License Key信息
    
    Args:
        license_key: License Key
    
    Returns:
        license_info or None
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT * FROM licenses WHERE license_key = ?
        """, (license_key,))
        
        row = cursor.fetchone()
        
        if not row:
            return None
        
        return {
            'id': row[0],
            'license_key': row[1],
            'tier': row[2],
            'status': row[3],
            'created_at': row[4],
            'activated_at': row[5],
            'expires_at': row[6],
            'stripe_session_id': row[7],
            'stripe_customer_id': row[8],
            'activation_count': row[9],
            'max_activations': row[10],
            'last_used': row[11]
        }
        
    except Exception as e:
        print(f"获取License Key信息失败: {e}")
        return None
    finally:
        conn.close()


def revoke_license(license_key: str) -> bool:
    """
    撤销License Key
    
    Args:
        license_key: License Key
    
    Returns:
        success
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            UPDATE licenses SET status = 'revoked' 
            WHERE license_key = ?
        """, (license_key,))
        
        conn.commit()
        return True
        
    except Exception as e:
        print(f"撤销License Key失败: {e}")
        return False
    finally:
        conn.close()


def get_license_by_stripe_session(session_id: str) -> Optional[str]:
    """
    通过Stripe会话ID获取License Key
    
    Args:
        session_id: Stripe会话ID
    
    Returns:
        license_key or None
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT license_key FROM licenses 
            WHERE stripe_session_id = ?
        """, (session_id,))
        
        row = cursor.fetchone()
        return row[0] if row else None
        
    except Exception as e:
        print(f"获取License Key失败: {e}")
        return None
    finally:
        conn.close()


# 初始化数据库
init_license_db()