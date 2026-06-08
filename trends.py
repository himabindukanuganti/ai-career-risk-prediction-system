from fastapi import APIRouter, Query
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from ml.trend_forecaster import get_trend_forecast, JOB_DATA

router = APIRouter()

@router.get("/{role}")
def forecast(role: str, horizon: int = Query(default=5, ge=1, le=10)):
    r = get_trend_forecast(role, horizon)
    return {"role":r.role,"yoy_growth":r.yoy_growth,"trend_signal":r.trend_signal,
            "summary":r.summary,
            "forecast":[{"year":f.year,"postings_index":f.postings_index,
                          "median_salary":f.median_salary} for f in r.forecast]}

@router.get("/")
def overview():
    return {"roles": sorted(JOB_DATA.items(), key=lambda x:x[1]["yoy"],reverse=True)}
