"""DealFlowTracker — FastAPI Backend"""
import os, json
from dotenv import load_dotenv
load_dotenv()
from datetime import datetime, timezone
from typing import Optional
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import sessionmaker, joinedload
from openai import OpenAI
from app.models import User, Submission, Deal, Activity, Contact, DealContact, AnalyticsEvent, FounderProject, DealStage, init_db, get_engine, utcnow
from app.auth import hash_password, verify_password, create_token, decode_token

AI_MODEL = os.getenv("AI_MODEL", "gpt-5-mini")
def get_openai_client():
    return OpenAI(api_key=os.getenv("OPENAI_API_KEY", ""))
app = FastAPI(title="DealFlowTracker", version="1.0.0")

from app.stripe_billing import router as stripe_router
app.include_router(stripe_router)

_origins_env = os.getenv("ALLOWED_ORIGINS", "")
ALLOWED_ORIGINS = [o.strip() for o in _origins_env.split(",") if o.strip()] if _origins_env else ["*"]
app.add_middleware(CORSMiddleware, allow_origins=ALLOWED_ORIGINS, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./dealflow.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
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
class ContactCreate(BaseModel):
    name: str; firm: str = ""; role: str = ""; email: str = ""; phone: str = ""
    tags: list[str] = []; notes: str = ""
class ContactUpdate(BaseModel):
    name: Optional[str] = None; firm: Optional[str] = None; role: Optional[str] = None
    email: Optional[str] = None; phone: Optional[str] = None
    tags: Optional[list[str]] = None; notes: Optional[str] = None
class LinkContact(BaseModel): contact_id: str; role_in_deal: str = "investor"

@app.get("/api/health")
def health(): return {"status": "healthy", "service": "DealFlowTracker"}


# ── Brain bridge — proxy questions to u-d-b's PA (Rigby) ───────────────────

class BrainAskRequest(BaseModel):
    message: str
    conversation_id: Optional[str] = None


@app.post("/api/brain/ask")
def brain_ask(req: BrainAskRequest, p: dict = Depends(decode_token)):
    from app.brain_client import ask
    if not req.message.strip():
        raise HTTPException(400, "message is required")
    result = ask(req.message, conversation_id=req.conversation_id,
                 workspace="dealflowtracker", user_id=p.get("sub"))
    if not result.get("ok"):
        raise HTTPException(502, result.get("error", "brain unreachable"))
    return result

def _track(event_type: str, user_id: str = None, resource_id: str = None, metadata: dict = None):
    db = SessionLocal()
    try:
        evt = AnalyticsEvent(event_type=event_type, user_id=user_id, resource_id=resource_id, metadata_=metadata or {})
        db.add(evt); db.commit()
    except Exception:
        pass
    finally:
        db.close()

@app.get("/api/events")
def list_events(event_type: Optional[str] = None, limit: int = 100, p: dict = Depends(decode_token)):
    db = SessionLocal()
    try:
        q = db.query(AnalyticsEvent).order_by(AnalyticsEvent.created_at.desc())
        if event_type: q = q.filter(AnalyticsEvent.event_type == event_type)
        events = q.limit(limit).all()
        return {"events": [{"id": e.id, "event_type": e.event_type, "user_id": e.user_id, "resource_id": e.resource_id, "metadata": e.metadata_, "created_at": e.created_at.isoformat()} for e in events]}
    finally: db.close()

@app.get("/api/events/summary")
def events_summary(p: dict = Depends(decode_token)):
    db = SessionLocal()
    try:
        from collections import Counter
        events = db.query(AnalyticsEvent.event_type).all()
        counts = Counter(e[0] for e in events)
        return {"total_events": sum(counts.values()), "by_type": dict(counts)}
    finally: db.close()

@app.post("/api/auth/register")
def register(req: RegisterReq):
    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.email == req.email).first()
        if existing:
            existing.password_hash = hash_password(req.password)
            existing.name = req.name
            db.commit()
            return {"token": create_token(existing.id, existing.email), "user": {"id": existing.id, "email": existing.email, "name": existing.name, "role": existing.role}}
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
        _track("deal_submitted", resource_id=deal.id, metadata={"company": data.company_name, "sector": data.sector})
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
        _track("stage_changed", p["sub"], deal_id, {"from": old, "to": data.stage})
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
        _track("scorecard_saved", p["sub"], deal_id, {"score_avg": deal.score_avg})
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
        _track("memo_generated", p["sub"], deal_id, {"company": sub.company_name})
        return {"memo": memo}
    finally: db.close()

# ── Contacts ─────────────────────────────────────────────────────────────

@app.post("/api/contacts")
def create_contact(data: ContactCreate, p: dict = Depends(decode_token)):
    db = SessionLocal()
    try:
        c = Contact(name=data.name, firm=data.firm, role=data.role, email=data.email,
                    phone=data.phone, tags=data.tags, notes=data.notes, created_by=p["sub"])
        db.add(c); db.commit(); db.refresh(c)
        return _contact_dict(c)
    finally: db.close()

@app.get("/api/contacts")
def list_contacts(q: Optional[str] = None, p: dict = Depends(decode_token)):
    db = SessionLocal()
    try:
        query = db.query(Contact).order_by(Contact.created_at.desc())
        if q:
            query = query.filter(
                Contact.name.ilike(f"%{q}%") | Contact.firm.ilike(f"%{q}%") | Contact.email.ilike(f"%{q}%")
            )
        return {"contacts": [_contact_dict(c) for c in query.limit(100).all()]}
    finally: db.close()

@app.get("/api/contacts/{contact_id}")
def get_contact(contact_id: str, p: dict = Depends(decode_token)):
    db = SessionLocal()
    try:
        c = db.query(Contact).filter(Contact.id == contact_id).first()
        if not c: raise HTTPException(404)
        # Get linked deals
        links = db.query(DealContact).filter(DealContact.contact_id == contact_id).all()
        deal_ids = [l.deal_id for l in links]
        deals = db.query(Deal).options(joinedload(Deal.submission)).filter(Deal.id.in_(deal_ids)).all() if deal_ids else []
        result = _contact_dict(c)
        result["deals"] = [{"id": d.id, "company_name": d.submission.company_name if d.submission else "Unknown", "stage": d.stage.value if d.stage else "new"} for d in deals]
        return result
    finally: db.close()

@app.patch("/api/contacts/{contact_id}")
def update_contact(contact_id: str, data: ContactUpdate, p: dict = Depends(decode_token)):
    db = SessionLocal()
    try:
        c = db.query(Contact).filter(Contact.id == contact_id).first()
        if not c: raise HTTPException(404)
        for field, val in data.model_dump(exclude_none=True).items():
            setattr(c, field, val)
        db.commit()
        return _contact_dict(c)
    finally: db.close()

@app.post("/api/deals/{deal_id}/contacts")
def link_contact_to_deal(deal_id: str, data: LinkContact, p: dict = Depends(decode_token)):
    db = SessionLocal()
    try:
        deal = db.query(Deal).filter(Deal.id == deal_id).first()
        if not deal: raise HTTPException(404)
        contact = db.query(Contact).filter(Contact.id == data.contact_id).first()
        if not contact: raise HTTPException(404, "Contact not found")
        existing = db.query(DealContact).filter(DealContact.deal_id == deal_id, DealContact.contact_id == data.contact_id).first()
        if existing: return {"status": "already_linked"}
        link = DealContact(deal_id=deal_id, contact_id=data.contact_id, role_in_deal=data.role_in_deal)
        db.add(link); db.commit()
        act = Activity(deal_id=deal_id, user_id=p["sub"], action_type="contact_linked",
                      content=f"Linked {contact.name} ({contact.firm or 'No firm'}) as {data.role_in_deal}")
        db.add(act); db.commit()
        return {"status": "linked"}
    finally: db.close()

@app.get("/api/deals/{deal_id}/contacts")
def get_deal_contacts(deal_id: str, p: dict = Depends(decode_token)):
    db = SessionLocal()
    try:
        links = db.query(DealContact).filter(DealContact.deal_id == deal_id).all()
        contact_ids = [l.contact_id for l in links]
        contacts = db.query(Contact).filter(Contact.id.in_(contact_ids)).all() if contact_ids else []
        role_map = {l.contact_id: l.role_in_deal for l in links}
        return {"contacts": [{**_contact_dict(c), "role_in_deal": role_map.get(c.id, "investor")} for c in contacts]}
    finally: db.close()

# ── Analytics ────────────────────────────────────────────────────────────

@app.get("/api/analytics")
def get_analytics(p: dict = Depends(decode_token)):
    db = SessionLocal()
    try:
        total = db.query(Deal).count()
        by_stage = {}
        for s in DealStage:
            c = db.query(Deal).filter(Deal.stage == s).count()
            by_stage[s.value] = c

        # Conversion funnel
        funnel_stages = ["new", "review", "diligence", "term_sheet", "closed_won"]
        funnel = []
        for stage in funnel_stages:
            count = sum(by_stage.get(s, 0) for s in funnel_stages[funnel_stages.index(stage):])
            count += by_stage.get("closed_lost", 0) if stage == "new" else 0
            funnel.append({"stage": stage, "count": count, "label": STAGE_LABELS_MAP.get(stage, stage)})

        # Top sectors
        deals = db.query(Deal).options(joinedload(Deal.submission)).all()
        sector_counts: dict[str, int] = {}
        total_score = 0.0
        scored_count = 0
        for d in deals:
            if d.submission and d.submission.sector:
                s = d.submission.sector
                sector_counts[s] = sector_counts.get(s, 0) + 1
            if d.score_avg and d.score_avg > 0:
                total_score += d.score_avg
                scored_count += 1

        top_sectors = sorted(sector_counts.items(), key=lambda x: x[1], reverse=True)[:8]
        avg_score = round(total_score / scored_count, 1) if scored_count else 0

        won = by_stage.get("closed_won", 0)
        lost = by_stage.get("closed_lost", 0)
        win_rate = round(won / (won + lost) * 100) if (won + lost) > 0 else 0

        return {
            "total_deals": total,
            "by_stage": by_stage,
            "funnel": funnel,
            "top_sectors": [{"sector": s, "count": c} for s, c in top_sectors],
            "avg_score": avg_score,
            "win_rate": win_rate,
            "total_contacts": db.query(Contact).count(),
            "deals_with_memos": db.query(Deal).filter(Deal.memo.isnot(None)).count(),
        }
    finally: db.close()

STAGE_LABELS_MAP = {"new": "New", "review": "Review", "diligence": "Diligence", "term_sheet": "Term Sheet", "closed_won": "Won", "closed_lost": "Lost"}

# ── Founder Project (cross-app data flow) ────────────────────────────────

@app.get("/api/founder-projects")
def list_founder_projects(p: dict = Depends(decode_token)):
    db = SessionLocal()
    try:
        projects = db.query(FounderProject).filter(FounderProject.user_id == p["sub"]).order_by(FounderProject.updated_at.desc()).all()
        return {"projects": [_founder_project_dict(fp) for fp in projects]}
    finally: db.close()


class ImportFromProjectReq(BaseModel):
    project_id: str


@app.post("/api/founder-projects/import")
def import_from_founder_project(data: ImportFromProjectReq, p: dict = Depends(decode_token)):
    """Import from a Founder Project to create a submission + deal."""
    db = SessionLocal()
    try:
        fp = db.query(FounderProject).filter(
            FounderProject.id == data.project_id, FounderProject.user_id == p["sub"]
        ).first()
        if not fp:
            raise HTTPException(404, "Founder Project not found")

        notes = fp.mentor_notes or {}
        deck = fp.deck_summary or {}

        # Create submission from project data
        sub = Submission(
            company_name=fp.title,
            one_liner=notes.get("summary", "")[:200],
            deck_url="",
            sector="",
            raise_amount=deck.get("raise_amount", ""),
            traction=notes.get("key_feedback", ""),
            founder_name="",
            founder_email=p.get("email", ""),
        )
        db.add(sub); db.flush()

        deal = Deal(submission_id=sub.id, owner_id=p["sub"])
        db.add(deal); db.flush()

        act = Activity(deal_id=deal.id, user_id=p["sub"], action_type="imported",
                      content=f"Imported from Founder Project: {fp.title}")
        db.add(act)

        # Write deal reference back to founder project
        fp.deal_id = deal.id
        fp.deal_data = {
            "company_name": fp.title,
            "raise_amount": deck.get("raise_amount", ""),
            "sector": "",
            "score_avg": 0,
        }
        if fp.stage in ("mentor_done", "deck_created"):
            fp.stage = "deal_opened"

        db.commit()
        _track("deal_imported_from_project", p["sub"], deal.id, {"founder_project_id": fp.id})

        return {
            "submission_id": sub.id,
            "deal_id": deal.id,
            "deal": _deal_dict(deal),
            "founder_project_stage": fp.stage,
        }
    finally: db.close()


def _founder_project_dict(p: FounderProject) -> dict:
    return {
        "id": p.id, "title": p.title, "stage": p.stage,
        "mentor_notes": p.mentor_notes, "deck_id": p.deck_id,
        "deck_summary": p.deck_summary, "deal_id": p.deal_id,
        "deal_data": p.deal_data, "contract_id": p.contract_id,
        "contract_data": p.contract_data,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }

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

    if not os.getenv("OPENAI_API_KEY"):
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
        r = get_openai_client().chat.completions.create(model=AI_MODEL, messages=[{"role": "user", "content": prompt}], max_completion_tokens=1500)
        return r.choices[0].message.content or "Failed to generate memo"
    except Exception:
        return f"# Memo generation failed for {sub.company_name}"

def _contact_dict(c: Contact) -> dict:
    return {"id": c.id, "name": c.name, "firm": c.firm, "role": c.role, "email": c.email,
            "phone": c.phone, "tags": c.tags or [], "notes": c.notes,
            "created_at": c.created_at.isoformat() if c.created_at else None}

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
