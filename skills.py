from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from nlp.resume_parser import ROLE_BENCHMARKS, compute_skill_gaps, ExtractedSkill

router = APIRouter()

class SkillIn(BaseModel):
    skill_name: str
    level: Optional[str] = "Intermediate"

class GapReq(BaseModel):
    current_skills: List[SkillIn]
    target_role: str

@router.post("/gap-analysis")
def gap_analysis(req: GapReq):
    skills = [ExtractedSkill(name=s.skill_name, category="") for s in req.current_skills]
    bench  = ROLE_BENCHMARKS.get(req.target_role.lower(), [])
    have   = {s.skill_name.lower() for s in req.current_skills}
    gaps   = [s for s in bench if s.lower() not in have]
    matched= [s for s in bench if s.lower() in have]
    return {"gaps":gaps,"matched":matched,"match_pct":round(len(matched)/max(1,len(bench))*100,1)}

@router.get("/benchmarks/{role}")
def benchmark(role: str):
    b = ROLE_BENCHMARKS.get(role.lower())
    if not b: raise HTTPException(404, f"No benchmark for: {role}")
    return {"role":role,"required_skills":b}
