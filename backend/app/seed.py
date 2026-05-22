"""DealFlowTracker — Seed demo data"""
import os
from dotenv import load_dotenv
load_dotenv()
from sqlalchemy.orm import sessionmaker
from app.models import User, Submission, Deal, Activity, DealStage, init_db, get_engine
from app.auth import hash_password

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./dealflow.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

DEALS = [
    {"company_name": "NeuralShip", "one_liner": "AI-powered supply chain optimization", "sector": "Logistics/AI", "raise_amount": "$3M", "traction": "15 enterprise pilots, $200K ARR", "founder_name": "Alex Rivera", "website": "neuralship.ai", "stage": "review"},
    {"company_name": "GreenLedger", "one_liner": "Carbon accounting for SMBs", "sector": "Climate Tech", "raise_amount": "$1.5M", "traction": "80 paying customers, $50K MRR", "founder_name": "Sam Okafor", "website": "greenledger.io", "stage": "diligence"},
    {"company_name": "CodePair", "one_liner": "AI pair programming for teams", "sector": "Developer Tools", "raise_amount": "$5M", "traction": "500 teams, $80K MRR, 30% m/m growth", "founder_name": "Maya Chen", "website": "codepair.dev", "stage": "term_sheet"},
    {"company_name": "HealthPulse", "one_liner": "Remote patient monitoring platform", "sector": "HealthTech", "raise_amount": "$2M", "traction": "3 hospital partnerships, FDA clearance pending", "founder_name": "Dr. James Park", "website": "healthpulse.co", "stage": "new"},
    {"company_name": "RetailOS", "one_liner": "Unified POS + inventory for indie retailers", "sector": "Retail Tech", "raise_amount": "$1M", "traction": "120 stores, $30K MRR", "founder_name": "Lisa Wang", "website": "retailos.com", "stage": "new"},
    {"company_name": "EduVerse", "one_liner": "VR classrooms for remote education", "sector": "EdTech", "raise_amount": "$4M", "traction": "2 university pilots, 500 students", "founder_name": "Tom Bradley", "website": "eduverse.io", "stage": "review"},
]

def seed():
    engine = get_engine(DATABASE_URL); init_db(DATABASE_URL)
    Session = sessionmaker(bind=engine); db = Session()
    if db.query(User).count() > 0: print("Already seeded"); db.close(); return
    user = User(email="demo@dealflow.dev", name="Demo Investor", password_hash=hash_password("demo123"), role="admin")
    db.add(user); db.flush()
    for d in DEALS:
        stage = d.pop("stage")
        sub = Submission(**d); db.add(sub); db.flush()
        deal = Deal(submission_id=sub.id, owner_id=user.id, stage=DealStage(stage))
        db.add(deal); db.flush()
        act = Activity(deal_id=deal.id, action_type="submitted", content=f"{d['company_name']} submitted")
        db.add(act)
    db.commit()
    print(f"Seeded 1 user + {len(DEALS)} deals")
    db.close()

if __name__ == "__main__": seed()
