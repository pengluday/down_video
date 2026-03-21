"""
限流模块
包含IP限流、License Key权限检查等功能
"""

from datetime import datetime
from typing import Optional, Tuple
from fastapi import Request, HTTPException, status

from models import SubscriptionTier, SUBSCRIPTION_LIMITS
from database import (
    check_ip_rate_limit, increment_ip_request_count, increment_ip_download_count
)


IP_MAX_REQUESTS_PER_HOUR = 100
IP_MAX_DOWNLOADS_PER_HOUR = 20


class RateLimitExceeded(HTTPException):
    def __init__(self, detail: str, retry_after: int = 3600):
        super().__init__(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=detail,
            headers={"Retry-After": str(retry_after)}
        )


class QuotaExceeded(HTTPException):
    def __init__(self, detail: str):
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail
        )


def get_client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip
    
    if request.client:
        return request.client.host
    
    return "unknown"


def check_ip_rate_limit_allowed(ip_address: str) -> Tuple[bool, str]:
    if ip_address == "unknown":
        return True, ""
    
    record = check_ip_rate_limit(ip_address)
    
    if record.request_count >= IP_MAX_REQUESTS_PER_HOUR:
        return False, f"IP请求过于频繁，每小时限制{IP_MAX_REQUESTS_PER_HOUR}次请求"
    
    if record.download_count >= IP_MAX_DOWNLOADS_PER_HOUR:
        return False, f"IP下载次数过多，每小时限制{IP_MAX_DOWNLOADS_PER_HOUR}次下载"
    
    return True, ""


def check_resolution_allowed(
    license_info: Optional[dict], 
    requested_resolution: int
) -> Tuple[bool, str, int]:
    if license_info is None:
        max_resolution = 480
        limits = SUBSCRIPTION_LIMITS[SubscriptionTier.FREE]
        is_pro = False
    else:
        tier_value = license_info.get('tier', 'free')
        tier = SubscriptionTier(tier_value) if tier_value in [t.value for t in SubscriptionTier] else SubscriptionTier.FREE
        limits = SUBSCRIPTION_LIMITS.get(tier, SUBSCRIPTION_LIMITS[SubscriptionTier.FREE])
        max_resolution = limits.max_resolution
        is_pro = tier in [SubscriptionTier.PRO, SubscriptionTier.PRO_YEARLY]
    
    if requested_resolution > max_resolution:
        if not is_pro:
            return False, f"需要升级Pro会员才能下载{requested_resolution}p视频", max_resolution
        else:
            return False, f"您的订阅不支持{requested_resolution}p视频", max_resolution
    
    return True, "", max_resolution


def record_request(ip_address: str):
    if ip_address != "unknown":
        increment_ip_request_count(ip_address)


def record_download(ip_address: str):
    if ip_address != "unknown":
        increment_ip_download_count(ip_address)


def get_user_limits_info(license_info: Optional[dict]) -> dict:
    if license_info is None:
        limits = SUBSCRIPTION_LIMITS[SubscriptionTier.FREE]
        tier = "free"
        is_pro = False
    else:
        tier_value = license_info.get('tier', 'free')
        tier = SubscriptionTier(tier_value) if tier_value in [t.value for t in SubscriptionTier] else SubscriptionTier.FREE
        limits = SUBSCRIPTION_LIMITS.get(tier, SUBSCRIPTION_LIMITS[SubscriptionTier.FREE])
        is_pro = tier in [SubscriptionTier.PRO, SubscriptionTier.PRO_YEARLY]
    
    max_downloads = limits.max_daily_downloads
    
    return {
        "tier": tier.value if isinstance(tier, SubscriptionTier) else tier,
        "is_pro": is_pro,
        "max_resolution": limits.max_resolution,
        "max_daily_downloads": max_downloads,
        "used_downloads": 0,
        "remaining_downloads": -1 if max_downloads < 0 else max_downloads,
        "download_speed_limit": limits.download_speed_limit,
        "has_ads": limits.has_ads,
        "priority_server": limits.priority_server
    }


async def rate_limit_dependency(request: Request):
    ip_address = get_client_ip(request)
    record_request(ip_address)
    
    allowed, reason = check_ip_rate_limit_allowed(ip_address)
    if not allowed:
        raise RateLimitExceeded(reason)
    
    return ip_address


async def check_download_allowed(
    request: Request,
    license_info: Optional[dict] = None
):
    ip_address = get_client_ip(request)
    
    allowed, reason = check_ip_rate_limit_allowed(ip_address)
    if not allowed:
        raise RateLimitExceeded(reason)
    
    limits_info = get_user_limits_info(license_info)
    
    return ip_address, limits_info
