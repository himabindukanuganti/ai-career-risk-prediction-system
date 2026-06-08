from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, JSON, Boolean, Text
from sqlalchemy.orm import relationship
from datetime import datetime
from models.db_session import Base

class User(Base):
    __tablename__ = "users"
    id            = Column(Integer, primary_key=True, index=True)
    name          = Column(String(100))
    email         = Column(String(150), unique=True, index=True)
    resume_path   = Column(String(500), nullable=True)
    current_role  = Column(String(150), nullable=True)
    years_exp     = Column(Float, default=0)
    created_at    = Column(DateTime, default=datetime.utcnow)
    skill_profile    = relationship("SkillProfile",   back_populates="user", cascade="all, delete")
    risk_predictions = relationship("RiskPrediction", back_populates="user", cascade="all, delete")
    recommendations  = relationship("Recommendation", back_populates="user", cascade="all, delete")

class SkillProfile(Base):
    __tablename__ = "skill_profiles"
    id           = Column(Integer, primary_key=True, index=True)
    user_id      = Column(Integer, ForeignKey("users.id"))
    skill_name   = Column(String(200))
    level        = Column(String(50))
    score        = Column(Float, default=0.0)
    verified     = Column(Boolean, default=False)
    source       = Column(String(100))
    extracted_at = Column(DateTime, default=datetime.utcnow)
    user         = relationship("User", back_populates="skill_profile")

class RiskPrediction(Base):
    __tablename__ = "risk_predictions"
    id              = Column(Integer, primary_key=True, index=True)
    user_id         = Column(Integer, ForeignKey("users.id"))
    role            = Column(String(150))
    risk_score      = Column(Float)
    risk_category   = Column(String(50))
    viability_index = Column(Float)
    shap_values     = Column(JSON)
    predicted_at    = Column(DateTime, default=datetime.utcnow)
    user            = relationship("User", back_populates="risk_predictions")

class JobTrend(Base):
    __tablename__ = "job_trends"
    id             = Column(Integer, primary_key=True, index=True)
    role           = Column(String(150), index=True)
    date           = Column(DateTime)
    posting_count  = Column(Integer, default=0)
    median_salary  = Column(Float, default=0.0)
    yoy_growth     = Column(Float, default=0.0)
    sector         = Column(String(100))
    source         = Column(String(100))
    fetched_at     = Column(DateTime, default=datetime.utcnow)

class Recommendation(Base):
    __tablename__ = "recommendations"
    id             = Column(Integer, primary_key=True, index=True)
    user_id        = Column(Integer, ForeignKey("users.id"))
    type           = Column(String(50))
    title          = Column(String(300))
    provider       = Column(String(150))
    resource_url   = Column(String(500))
    skill_tags     = Column(JSON)
    priority_score = Column(Float)
    phase          = Column(Integer)
    created_at     = Column(DateTime, default=datetime.utcnow)
    user           = relationship("User", back_populates="recommendations")

class Course(Base):
    __tablename__ = "courses"
    id           = Column(Integer, primary_key=True, index=True)
    title        = Column(String(300))
    platform     = Column(String(100))
    url          = Column(String(500))
    skill_tags   = Column(JSON)
    avg_rating   = Column(Float, default=0.0)
    duration_hr  = Column(Float, default=0.0)
    salary_lift  = Column(Float, default=0.0)
    difficulty   = Column(String(50))
    source       = Column(String(100), default="static")
    last_updated = Column(DateTime, default=datetime.utcnow)
