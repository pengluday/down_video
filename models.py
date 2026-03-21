"""
数据模型定义
License Key系统相关模型
"""

from enum import Enum
from typing import Optional
from datetime import datetime

from pydantic import BaseModel, Field


class SubscriptionTier(str, Enum):
    FREE = "free"
    PRO = "pro"
    PRO_YEARLY = "pro_yearly"


class SubscriptionLimit(BaseModel):
    tier: SubscriptionTier
    max_daily_downloads: int
    max_resolution: int
    download_speed_limit: Optional[int]
    has_ads: bool
    priority_server: bool


SUBSCRIPTION_LIMITS = {
    SubscriptionTier.FREE: SubscriptionLimit(
        tier=SubscriptionTier.FREE,
        max_daily_downloads=5,
        max_resolution=480,
        download_speed_limit=300,
        has_ads=True,
        priority_server=False
    ),
    SubscriptionTier.PRO: SubscriptionLimit(
        tier=SubscriptionTier.PRO,
        max_daily_downloads=-1,
        max_resolution=1080,
        download_speed_limit=None,
        has_ads=False,
        priority_server=True
    ),
    SubscriptionTier.PRO_YEARLY: SubscriptionLimit(
        tier=SubscriptionTier.PRO_YEARLY,
        max_daily_downloads=-1,
        max_resolution=1080,
        download_speed_limit=None,
        has_ads=False,
        priority_server=True
    )
}


class RateLimitRecord(BaseModel):
    key: str
    window_start: datetime
    request_count: int = 0
    download_count: int = 0


class SubscriptionCreate(BaseModel):
    price_id: str
