from fastapi import APIRouter
from pydantic import BaseModel
from typing import List
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from ml.recommendation_engine import build_upskill_roadmap, content_based_filter

router = APIRouter()

class RoadmapReq(BaseModel):
    current_role: str; target_role: str
    skill_gaps: List[str]; years_exp: float = 2.0

@router.post("/roadmap")
def roadmap(req: RoadmapReq):
    return build_upskill_roadmap(req.current_role, req.target_role,
                                  req.skill_gaps, req.years_exp)

@router.get("/courses")
def courses(skills: str = ""):
    gaps = [s.strip() for s in skills.split(",") if s.strip()]
    c = content_based_filter(gaps, 2)
    return {"courses":[{"title":x.title,"platform":x.platform,"phase":x.phase} for x in c]}
