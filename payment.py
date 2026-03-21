"""
支付模块
集成Stripe支付系统 - License Key版本
"""

import os
from typing import Optional, Dict, Any

import stripe
from fastapi import HTTPException, status

from models import SubscriptionTier


STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "whsec_your_webhook_secret")

STRIPE_PRICE_IDS = {
    SubscriptionTier.PRO: os.getenv("STRIPE_PRICE_ID_PRO", ""),
    SubscriptionTier.PRO_YEARLY: os.getenv("STRIPE_PRICE_ID_PRO_YEARLY", "")
}

stripe.api_key = STRIPE_SECRET_KEY


class PaymentError(HTTPException):
    def __init__(self, detail: str):
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=detail
        )


def create_customer(email: str, name: Optional[str] = None) -> stripe.Customer:
    try:
        customer = stripe.Customer.create(
            email=email,
            name=name or email.split('@')[0]
        )
        return customer
    except stripe.error.StripeError as e:
        raise PaymentError(f"创建客户失败: {str(e)}")


def create_checkout_session(
    customer_id: Optional[str],
    price_id: str,
    user_id: Optional[str],
    success_url: str,
    cancel_url: str,
    metadata: Optional[Dict[str, Any]] = None
) -> stripe.checkout.Session:
    try:
        session_params = {
            "payment_method_types": ["card"],
            "line_items": [{
                "price": price_id,
                "quantity": 1
            }],
            "mode": "subscription",
            "success_url": success_url,
            "cancel_url": cancel_url
        }
        
        if customer_id:
            session_params["customer"] = customer_id
        
        if metadata:
            session_params["metadata"] = metadata
        
        session = stripe.checkout.Session.create(**session_params)
        return session
    except stripe.error.StripeError as e:
        raise PaymentError(f"创建结账会话失败: {str(e)}")


def construct_webhook_event(payload: bytes, sig_header: str) -> stripe.Event:
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET
        )
        return event
    except ValueError:
        raise PaymentError("无效的payload")
    except stripe.error.SignatureVerificationError:
        raise PaymentError("无效的签名")


def handle_webhook_event(event: stripe.Event) -> bool:
    event_type = event.type
    data = event.data.object
    
    if event_type == "checkout.session.completed":
        license_key = data.metadata.get("license_key")
        
        if license_key:
            from license import activate_license
            success, message = activate_license(license_key)
            if success:
                print(f"License Key已激活: {license_key}")
            else:
                print(f"License Key激活失败: {message}")
            return True
    
    return False


def get_price_info() -> Dict[str, Any]:
    return {
        "monthly": {
            "tier": "pro",
            "price_id": STRIPE_PRICE_IDS[SubscriptionTier.PRO],
            "amount": 499,
            "currency": "usd",
            "interval": "month"
        },
        "yearly": {
            "tier": "pro_yearly",
            "price_id": STRIPE_PRICE_IDS[SubscriptionTier.PRO_YEARLY],
            "amount": 2900,
            "currency": "usd",
            "interval": "year",
            "savings": "40%"
        }
    }
