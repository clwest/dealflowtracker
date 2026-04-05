"""DealFlowTracker — FastAPI Backend"""
import os, json
from datetime import datetime, timezone
from typing import Optional
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import sessionmaker, joinedload
from openai import OpenAI
from app.models import User, Submission, Deal, Activity, DealStage, init_db, get_engine, utcnow
from app.auth import hash_password, verify_password, create_token, decode_token

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY", ""))
app = FastAPI(title="DealFlowTracker", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5178", "http://localhost:3000"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
DATABASE_URL = "sqlite:///./dealflow.db"
engine = get_engine(DATABASE_URL); init_db(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)

class RegisterReq(BaseModel): email: str; password: str; name: str
class LoginReq(BaseModel): email: str; password: str
class SubmissionCreate(BaseModel):
    company_name: str; website: str = ""; one_liner: str = ""; deck_url: str = ""
    sector: str = ""; raise_amount: str = ""; traction: str = ""
    founder_name: str = ""; founder_email: str = ""
class StageUpdate(BaseModel): stage: str
class ScorecardUpdate(BaseModel): team: int = 0; market: int = 0; traction: int = 0; defensibility: int = 0; fit: int = 0
class NoteCreate(BaseModel): content: str

@app.get("/api/health")
def health(): return {"status": "healthy", "service": "DealFlowTracker"}

@app.post("/api/auth/register")
def register(req: RegisterReq):
    db = SessionLocal()
    try:
        if db.query(User).filter(User.email == req.email).first(): raise HTTPException(400, "Email taken")
        user = User(email=req.email, name=req.name, password_hash=hash_password(req.password))
        db.add(user); db.commit(); db.refresh(user)
        return {"token": create_token(user.id, user.email), "user": {"id": user.id, "email": user.email, "name": user.name, "role": user.role}}
    finally: db.close()

@app.post("/api/auth/login")
def login(req: LoginReq):
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == req.email).first()
        if not user or not verify_password(req.password, user.password_hash): raise HTTPException(401, "Bad creds")
        return {"token": create_token(user.id, user.email), "user": {"id": user.id, "email": user.email, "name": user.name, "role": user.role}}
    finally: db.close()

@app.get("/api/users/me")
def get_me(p: dict = Depends(decode_token)):
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.id == p["sub"]).first()
        if not u: raise HTTPException(404)
        return {"id": u.id, "email": u.email, "name": u.name, "role": u.role}
    finally: db.close()

# ── Submissions (public intake) ───────────────────────────────────────────

@app.post("/api/submissions")
def create_submission(data: SubmissionCreate):
    db = SessionLocal()
    try:
        sub = Submission(**data.model_dump())
        db.add(sub); db.flush()
        deal = Deal(submission_id=sub.id)
        db.add(deal); db.flush()
        act = Activity(deal_id=deal.id, action_type="submitted", content=f"{data.company_name} submitted")
        db.add(act); db.commit()
        return {"submission_id": sub.id, "deal_id": deal.id, "status": "received"}
    finally: db.close()

# ── Deals (authenticated) ────────────────────────────────────────────────

@app.get("/api/deals")
def list_deals(stage: Optional[str] = None, p: dict = Depends(decode_token)):
    db = SessionLocal()
    try:
        q = db.query(Deal).options(joinedload(Deal.submission)).order_by(Deal.last_activity_at.desc())
        if stage: q = q.filter(Deal.stage == stage)
        deals = q.limit(100).all()
        return {"deals": [_deal_dict(d) for d in deals]}
    finally: db.close()

@app.get("/api/deals/{deal_id}")
def get_deal(deal_id: str, p: dict = Depends(decode_token)):
    db = SessionLocal()
    try:
        deal = db.query(Deal).options(joinedload(Deal.submission), joinedload(Deal.activities)).filter(Deal.id == deal_id).first()
        if not deal: raise HTTPException(404)
        result = _deal_dict(deal)
        result["activities"] = [{"id": a.id, "action_type": a.action_type, "content": a.content, "created_at": a.created_at.isoformat()} for a in deal.activities]
        return result
    finally: db.close()

@app.patch("/api/deals/{deal_id}/stage")
def update_stage(deal_id: str, data: StageUpdate, p: dict = Depends(decode_token)):
    db = SessionLocal()
    try:
        deal = db.query(Deal).filter(Deal.id == deal_id).first()
        if not deal: raise HTTPException(404)
        old = deal.stage.value if deal.stage else "new"
        deal.stage = DealStage(data.stage)
        deal.last_activity_at = utcnow()
        act = Activity(deal_id=deal.id, user_id=p["sub"], action_type="stage_change", content=f"Moved from {old} → {data.stage}")
        db.add(act); db.commit()
        return {"status": "updated", "stage": data.stage}
    finally: db.close()

@app.patch("/api/deals/{deal_id}/scorecard")
def update_scorecard(deal_id: str, data: ScorecardUpdate, p: dict = Depends(decode_token)):
    db = SessionLocal()
    try:
        deal = db.query(Deal).filter(Deal.id == deal_id).first()
        if not deal: raise HTTPException(404)
        sc = data.model_dump()
        deal.scorecard = sc
        vals = [v for v in sc.values() if v > 0]
        deal.score_avg = round(sum(vals) / len(vals), 1) if vals else 0
        deal.last_activity_at = utcnow()
        act = Activity(deal_id=deal.id, user_id=p["sub"], action_type="scored", content=f"Scorecard updated: avg {deal.score_avg}")
        db.add(act); db.commit()
        return {"scorecard": sc, "score_avg": deal.score_avg}
    finally: db.close()

@app.post("/api/deals/{deal_id}/notes")
def add_note(deal_id: str, data: NoteCreate, p: dict = Depends(decode_token)):
    db = SessionLocal()
    try:
        deal = db.query(Deal).filter(Deal.id == deal_id).first()
        if not deal: raise HTTPException(404)
        if data.content: deal.notes = (deal.notes or "") + f"\n---\n{data.content}"
        deal.last_activity_at = utcnow()
        act = Activity(deal_id=deal.id, user_id=p["sub"], action_type="note", content=data.content[:100])
        db.add(act); db.commit()
        return {"status": "noted"}
    finally: db.close()

@app.post("/api/deals/{deal_id}/generate-memo")
def generate_memo(deal_id: str, p: dict = Depends(decode_token)):
    db = SessionLocal()
    try:
        deal = db.query(Deal).options(joinedload(Deal.submission)).filter(Deal.id == deal_id).first()
        if not deal: raise HTTPException(404)
        sub = deal.submission
        memo = _generate_memo(sub, deal)
        deal.memo = memo
        deal.last_activity_at = utcnow()
        act = Activity(deal_id=deal.id, user_id=p["sub"], action_type="memo_generated", content="Investment memo generated")
        db.add(act); db.commit()
        return {"memo": memo}
    finally: db.close()

# ── Stats ─────────────────────────────────────────────────────────────────

@app.get("/api/stats")
def get_stats():
    db = SessionLocal()
    try:
        total = db.query(Deal).count()
        by_stage = {}
        for s in DealStage:
            c = db.query(Deal).filter(Deal.stage == s).count()
            if c: by_stage[s.value] = c
        return {"total_deals": total, "by_stage": by_stage, "total_submissions": db.query(Submission).count()}
    finally: db.close()

# ── AI Memo ───────────────────────────────────────────────────────────────

def _generate_memo(sub: Submission, deal: Deal) -> str:
    prompt = f"""Write a 1-page investment memo for:

Company: {sub.company_name}
One-liner: {sub.one_liner}
Sector: {sub.sector}
Raise: {sub.raise_amount}
Traction: {sub.traction}
Scorecard: {json.dumps(deal.scorecard or {})}

Structure: Summary, Thesis, Key Risks, Recommendation. Be concise and analytical."""

    if not client.api_key:
        return f"""# Investment Memo: {sub.company_name}

## Summary
{sub.company_name} is a {sub.sector or 'technology'} company raising {sub.raise_amount or 'undisclosed'}. {sub.one_liner or ''}

## Thesis
{sub.traction or 'Early-stage company with potential.'}

## Key Risks
- Market timing and competition
- Execution risk on product roadmap
- Capital efficiency at current burn rate

## Recommendation
[Dev Mode] Set OPENAI_API_KEY for AI-generated analysis. Current scorecard: {json.dumps(deal.scorecard or {})}"""

    try:
        r = client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": prompt}], max_tokens=1500)
        return r.choices[0].message.content or "Failed to generate memo"
    except Exception:
        return f"# Memo generation failed for {sub.company_name}"

def _deal_dict(d: Deal) -> dict:
    sub = d.submission
    return {
        "id": d.id, "stage": d.stage.value if d.stage else "new",
        "company_name": sub.company_name if sub else "Unknown",
        "one_liner": sub.one_liner if sub else "",
        "sector": sub.sector if sub else "",
        "raise_amount": sub.raise_amount if sub else "",
        "deck_url": sub.deck_url if sub else "",
        "founder_name": sub.founder_name if sub else "",
        "scorecard": d.scorecard or {},
        "score_avg": d.score_avg,
        "memo": d.memo,
        "notes": d.notes,
        "created_at": d.created_at.isoformat() if d.created_at else None,
        "last_activity_at": d.last_activity_at.isoformat() if d.last_activity_at else None,
    }
