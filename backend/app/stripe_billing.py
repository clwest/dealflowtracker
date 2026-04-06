"""PitchDeckForge — Stripe Billing Integration

Uses Stripe Checkout (hosted) for subscriptions.
No custom payment forms — Stripe handles all PCI compliance.
"""

import os
import stripe
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

router = APIRouter(prefix="/api/stripe", tags=["billing"])

stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
FRONTEND_URL = os.getenv("FRONTEND_URL", "https://pitchdeckforge.vercel.app")

# Price IDs — set these after creating products in Stripe Dashboard
PRICE_IDS = {
    "pro_monthly": os.getenv("STRIPE_PRICE_PRO_MONTHLY", ""),
    "team_monthly": os.getenv("STRIPE_PRICE_TEAM_MONTHLY", ""),
}


class CheckoutRequest(BaseModel):
    plan: str  # "pro_monthly" or "team_monthly"


@router.post("/checkout")
def checkout(req: CheckoutRequest, request: Request):
    """Create a Stripe Checkout session — called from frontend."""
    from app.auth import decode_token
    from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

    # Manual auth extraction (router can't easily share Depends)
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")

    token = auth_header.split(" ")[1]
    from jose import jwt, JWTError
    SECRET_KEY = os.getenv("SECRET_KEY", "founder-toolkit-shared-secret-2026")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

    if not stripe.api_key:
        raise HTTPException(status_code=500, detail="Stripe not configured")

    price_id = PRICE_IDS.get(req.plan)
    if not price_id:
        raise HTTPException(status_code=400, detail=f"Unknown plan: {req.plan}")

    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            payment_method_types=["card"],
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=f"{FRONTEND_URL}?checkout=success",
            cancel_url=f"{FRONTEND_URL}?checkout=cancel",
            client_reference_id=payload["sub"],
            customer_email=payload.get("email"),
            metadata={
                "user_id": payload["sub"],
                "plan": req.plan,
            },
        )
        return {"url": session.url, "session_id": session.id}
    except stripe.error.StripeError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/webhook")
async def stripe_webhook(request: Request):
    """Handle Stripe webhook events (subscription created/cancelled)."""
    body = await request.body()
    sig = request.headers.get("stripe-signature", "")

    try:
        event = stripe.Webhook.construct_event(body, sig, STRIPE_WEBHOOK_SECRET)
    except (ValueError, stripe.error.SignatureVerificationError):
        raise HTTPException(status_code=400, detail="Invalid webhook signature")

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        user_id = session.get("client_reference_id") or session["metadata"].get("user_id")
        plan = session["metadata"].get("plan", "pro_monthly")
        subscription_id = session.get("subscription")

        if user_id:
            _update_user_subscription(user_id, plan, subscription_id)

    elif event["type"] in ("customer.subscription.deleted", "customer.subscription.updated"):
        sub = event["data"]["object"]
        # Find user by subscription ID and update status
        if sub.get("status") in ("canceled", "unpaid", "past_due"):
            _cancel_user_subscription(sub["id"])

    return JSONResponse({"received": True})


def _update_user_subscription(user_id: str, plan: str, subscription_id: str):
    """Update user's subscription status in the shared database."""
    from app.models import User, get_engine
    from sqlalchemy.orm import sessionmaker

    DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./pitchdeckforge.db")
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

    engine = get_engine(DATABASE_URL)
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if user:
            # Add subscription fields if they exist
            if hasattr(user, 'subscription_plan'):
                user.subscription_plan = plan
            if hasattr(user, 'stripe_subscription_id'):
                user.stripe_subscription_id = subscription_id
            db.commit()
            print(f"[STRIPE] Updated subscription for user {user_id}: plan={plan}")
    finally:
        db.close()


def _cancel_user_subscription(subscription_id: str):
    """Cancel a user's subscription by Stripe subscription ID."""
    from app.models import User, get_engine
    from sqlalchemy.orm import sessionmaker

    DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./pitchdeckforge.db")
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

    engine = get_engine(DATABASE_URL)
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        # Search all users for matching subscription ID
        users = db.query(User).all()
        for user in users:
            if hasattr(user, 'stripe_subscription_id') and user.stripe_subscription_id == subscription_id:
                user.subscription_plan = "free"
                user.stripe_subscription_id = None
                db.commit()
                print(f"[STRIPE] Cancelled subscription for user {user.id}")
                break
    finally:
        db.close()
