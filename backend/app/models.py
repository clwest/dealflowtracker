"""DealFlowTracker — Data Models"""
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Text, Integer, Float, DateTime, ForeignKey, JSON, Enum, create_engine
from sqlalchemy.orm import declarative_base, relationship
import enum

Base = declarative_base()
def gen_uuid(): return str(uuid.uuid4())
def utcnow(): return datetime.now(timezone.utc)

class DealStage(str, enum.Enum):
    new = "new"
    review = "review"
    diligence = "diligence"
    term_sheet = "term_sheet"
    closed_won = "closed_won"
    closed_lost = "closed_lost"

class User(Base):
    __tablename__ = "users"
    id = Column(String, primary_key=True, default=gen_uuid)
    email = Column(String, unique=True, nullable=False, index=True)
    name = Column(String, nullable=False)
    password_hash = Column(String, nullable=True)
    role = Column(String, default="investor")  # investor, admin
    created_at = Column(DateTime, default=utcnow)

class Submission(Base):
    __tablename__ = "submissions"
    id = Column(String, primary_key=True, default=gen_uuid)
    company_name = Column(String, nullable=False)
    website = Column(String, nullable=True)
    one_liner = Column(String, nullable=True)
    deck_url = Column(String, nullable=True)
    sector = Column(String, nullable=True)
    raise_amount = Column(String, nullable=True)
    traction = Column(Text, nullable=True)
    founder_name = Column(String, nullable=True)
    founder_email = Column(String, nullable=True)
    submitted_at = Column(DateTime, default=utcnow)
    deal = relationship("Deal", back_populates="submission", uselist=False)

class Deal(Base):
    __tablename__ = "deals"
    id = Column(String, primary_key=True, default=gen_uuid)
    submission_id = Column(String, ForeignKey("submissions.id"), nullable=False)
    owner_id = Column(String, ForeignKey("users.id"), nullable=True)
    stage = Column(Enum(DealStage), default=DealStage.new)
    scorecard = Column(JSON, default=dict)  # {team: 1-5, market: 1-5, traction: 1-5, defensibility: 1-5, fit: 1-5}
    memo = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    score_avg = Column(Float, default=0.0)
    created_at = Column(DateTime, default=utcnow)
    last_activity_at = Column(DateTime, default=utcnow)
    submission = relationship("Submission", back_populates="deal")
    activities = relationship("Activity", back_populates="deal", order_by="Activity.created_at.desc()")

class Activity(Base):
    __tablename__ = "activities"
    id = Column(String, primary_key=True, default=gen_uuid)
    deal_id = Column(String, ForeignKey("deals.id"), nullable=False)
    user_id = Column(String, ForeignKey("users.id"), nullable=True)
    action_type = Column(String, nullable=False)  # stage_change, note, memo_generated, scored
    content = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    deal = relationship("Deal", back_populates="activities")

class AnalyticsEvent(Base):
    __tablename__ = "analytics_events"
    id = Column(String, primary_key=True, default=gen_uuid)
    event_type = Column(String, nullable=False, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=True)
    resource_id = Column(String, nullable=True)
    metadata_ = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime, default=utcnow)

class Contact(Base):
    __tablename__ = "contacts"
    id = Column(String, primary_key=True, default=gen_uuid)
    name = Column(String, nullable=False)
    firm = Column(String, nullable=True)
    role = Column(String, nullable=True)
    email = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    tags = Column(JSON, default=list)  # ["lead_investor", "angel", "strategic"]
    notes = Column(Text, nullable=True)
    created_by = Column(String, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=utcnow)

class DealContact(Base):
    __tablename__ = "deal_contacts"
    id = Column(String, primary_key=True, default=gen_uuid)
    deal_id = Column(String, ForeignKey("deals.id"), nullable=False)
    contact_id = Column(String, ForeignKey("contacts.id"), nullable=False)
    role_in_deal = Column(String, default="investor")  # investor, advisor, introducer
    created_at = Column(DateTime, default=utcnow)

# ── Founder Toolkit: Shared Project (cross-app data flow) ─────────────────

class FounderProject(Base):
    __tablename__ = "founder_projects"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    title = Column(String, nullable=False)
    stage = Column(String, default="started")  # started, mentor_done, deck_created, deal_opened, contract_drafted
    mentor_session_id = Column(String, nullable=True)
    mentor_notes = Column(JSON, nullable=True)  # {summary, next_steps, key_feedback, mentor_name}
    deck_id = Column(String, nullable=True)
    deck_summary = Column(JSON, nullable=True)  # {tl_dr, slide_count, template, title}
    deal_id = Column(String, nullable=True)
    deal_data = Column(JSON, nullable=True)  # {company_name, raise_amount, sector, score_avg}
    contract_id = Column(String, nullable=True)
    contract_data = Column(JSON, nullable=True)  # {title, status, template_name}
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


def get_engine(url="sqlite:///./dealflow.db"): return create_engine(url, echo=False)
def init_db(url="sqlite:///./dealflow.db"):
    e = get_engine(url); Base.metadata.create_all(e)
    # Add missing columns if table was created by another app (shared DB)
    from sqlalchemy import inspect as sa_inspect, text
    inspector = sa_inspect(e)
    if inspector.has_table("users"):
        existing = {c["name"] for c in inspector.get_columns("users")}
        with e.begin() as conn:
            if "role" not in existing:
                conn.execute(text("ALTER TABLE users ADD COLUMN role VARCHAR DEFAULT 'investor'"))
    return e
