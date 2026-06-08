from fastapi import APIRouter, File, UploadFile, Form, HTTPException
from fastapi.responses import JSONResponse
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from nlp.resume_parser import parse_resume

router = APIRouter()

@router.post("/parse")
async def parse(file: UploadFile = File(...), target_role: str = Form(default="")):
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in {".pdf",".docx",".doc",".txt"}:
        raise HTTPException(400, f"Unsupported: {ext}")
    data = await file.read()
    r = parse_resume(data, file.filename, target_role)
    return {"name":r.name,"email":r.email,"years":r.total_years_exp,
            "confidence":r.confidence,"skill_count":len(r.skills),
            "skills":[{"name":s.name,"level":s.level,"score":s.score} for s in r.skills],
            "skill_gaps":r.skill_gaps}
