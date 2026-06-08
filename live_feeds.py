"""
Live Data Feeds — all free APIs
BLS · O*NET · Adzuna · RemoteOK · Coursera · Reed
"""
import httpx
import asyncio
import os
from datetime import datetime
from typing import Dict, List, Optional

BLS_KEY      = os.getenv("BLS_API_KEY", "")
ONET_USER    = os.getenv("ONET_USERNAME", "")
ONET_PASS    = os.getenv("ONET_PASSWORD", "")
ADZUNA_ID    = os.getenv("ADZUNA_APP_ID", "")
ADZUNA_KEY   = os.getenv("ADZUNA_APP_KEY", "")
REED_KEY     = os.getenv("REED_API_KEY", "")

# BLS series IDs → occupation mapping
BLS_SERIES = {
    "software engineers":   "CES6054151001",
    "data scientists":      "CES6054132001",
    "total it employment":  "CES6054000001",
    "avg weekly earnings":  "CES0500000011",
}

# ── BLS (Bureau of Labor Statistics) ─────────────────────────────────────────
async def fetch_bls_data(series_ids: Optional[List[str]] = None) -> Dict:
    """Free: 500 requests/day. Register at bls.gov/developers"""
    if not BLS_KEY:
        return {"error": "BLS_API_KEY not set in .env"}
    ids = series_ids or list(BLS_SERIES.values())
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(
            "https://api.bls.gov/publicAPI/v2/timeseries/data/",
            json={
                "seriesid":        ids,
                "startyear":       "2020",
                "endyear":         str(datetime.now().year),
                "registrationkey": BLS_KEY,
            }
        )
    data = response.json()
    results = {}
    for series in data.get("Results", {}).get("series", []):
        sid = series["seriesID"]
        label = next((k for k, v in BLS_SERIES.items() if v == sid), sid)
        results[label] = [
            {"year": p["year"], "period": p["period"], "value": float(p["value"])}
            for p in series.get("data", [])[:12]
        ]
    return {"source": "BLS", "fetched_at": datetime.utcnow().isoformat(), "data": results}


# ── O*NET Web Services ────────────────────────────────────────────────────────
async def fetch_onet_occupation(soc_code: str) -> Dict:
    """Free: unlimited. Register at services.onetcenter.org"""
    if not ONET_USER:
        return {"error": "ONET_USERNAME not set in .env"}
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(
            f"https://services.onetcenter.org/ws/online/occupations/{soc_code}/summary",
            auth=(ONET_USER, ONET_PASS),
            headers={"Accept": "application/json"},
        )
    return response.json()

async def fetch_onet_automation_score(soc_code: str) -> Dict:
    """Fetch task automation scores for an occupation."""
    if not ONET_USER:
        return {"error": "ONET_USERNAME not set in .env"}
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(
            f"https://services.onetcenter.org/ws/online/occupations/{soc_code}/summary/tasks",
            auth=(ONET_USER, ONET_PASS),
            headers={"Accept": "application/json"},
        )
    return response.json()

ONET_CODES = {
    "data analyst":         "15-2041.00",
    "data scientist":       "15-2051.00",
    "ml engineer":          "15-2051.02",
    "software engineer":    "15-1252.00",
    "data engineer":        "15-1243.00",
    "devops engineer":      "15-1244.00",
    "product manager":      "11-3021.00",
    "qa tester":            "15-1253.00",
}


# ── Adzuna Jobs API ───────────────────────────────────────────────────────────
async def fetch_adzuna_jobs(role: str, country: str = "in", pages: int = 2) -> Dict:
    """Free: 100 calls/day. Register at developer.adzuna.com"""
    if not ADZUNA_ID:
        return {"error": "ADZUNA_APP_ID not set in .env"}
    all_jobs, total = [], 0
    async with httpx.AsyncClient(timeout=15) as client:
        for page in range(1, pages + 1):
            r = await client.get(
                f"https://api.adzuna.com/v1/api/jobs/{country}/search/{page}",
                params={
                    "app_id":           ADZUNA_ID,
                    "app_key":          ADZUNA_KEY,
                    "what":             role,
                    "results_per_page": 50,
                    "sort_by":          "date",
                }
            )
            data = r.json()
            total = data.get("count", 0)
            all_jobs.extend(data.get("results", []))
    return {
        "source":         "Adzuna",
        "role":           role,
        "total_postings": total,
        "avg_salary":     _safe_mean([j.get("salary_max", 0) for j in all_jobs if j.get("salary_max")]),
        "jobs_sample":    all_jobs[:5],
        "fetched_at":     datetime.utcnow().isoformat(),
    }


# ── RemoteOK (no key needed) ──────────────────────────────────────────────────
async def fetch_remoteok_jobs(role: str) -> Dict:
    """Completely free, no API key required."""
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(
            "https://remoteok.com/api",
            headers={"User-Agent": "CareerAI/1.0 (educational project)"}
        )
    jobs = r.json()
    if isinstance(jobs, list):
        jobs = jobs[1:]  # first item is metadata
    filtered = [j for j in jobs if role.lower() in str(j.get("tags", "")).lower()
                or role.lower() in str(j.get("position", "")).lower()]
    return {
        "source":         "RemoteOK",
        "role":           role,
        "total_postings": len(filtered),
        "jobs_sample":    filtered[:5],
        "fetched_at":     datetime.utcnow().isoformat(),
    }


# ── Coursera Catalogue (no key needed) ────────────────────────────────────────
async def fetch_coursera_courses(skill: str, limit: int = 20) -> Dict:
    """Completely free, no API key required."""
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(
            "https://api.coursera.org/api/courses.v1",
            params={
                "q":      "search",
                "query":  skill,
                "fields": "name,slug,description,partnerIds,workload",
                "limit":  limit,
            }
        )
    data = r.json()
    courses = data.get("elements", [])
    return {
        "source":   "Coursera",
        "skill":    skill,
        "count":    len(courses),
        "courses":  [{"name": c["name"], "slug": c.get("slug", ""), "url": f"https://www.coursera.org/learn/{c.get('slug','')}"} for c in courses],
        "fetched_at": datetime.utcnow().isoformat(),
    }


# ── Reed Jobs API ─────────────────────────────────────────────────────────────
async def fetch_reed_jobs(role: str) -> Dict:
    """Free: 100/day. Register at reed.co.uk/developers"""
    if not REED_KEY:
        return {"error": "REED_API_KEY not set in .env"}
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(
            "https://www.reed.co.uk/api/1.0/search",
            params={"keywords": role, "resultsToTake": 100},
            auth=(REED_KEY, "")
        )
    data = r.json()
    jobs = data.get("results", [])
    return {
        "source":          "Reed",
        "role":            role,
        "total_postings":  data.get("totalResults", 0),
        "avg_salary":      _safe_mean([j.get("maximumSalary", 0) for j in jobs if j.get("maximumSalary")]),
        "jobs_sample":     jobs[:5],
        "fetched_at":      datetime.utcnow().isoformat(),
    }


# ── Aggregate fetcher ─────────────────────────────────────────────────────────
async def get_all_live_data(role: str) -> Dict:
    """Fetch all available free sources in parallel."""
    results = await asyncio.gather(
        fetch_adzuna_jobs(role),
        fetch_remoteok_jobs(role),
        fetch_coursera_courses(role),
        return_exceptions=True
    )
    soc = ONET_CODES.get(role.lower())
    onet_data = await fetch_onet_automation_score(soc) if soc else {}
    return {
        "role":               role,
        "adzuna":             results[0] if not isinstance(results[0], Exception) else {},
        "remoteok":           results[1] if not isinstance(results[1], Exception) else {},
        "coursera":           results[2] if not isinstance(results[2], Exception) else {},
        "onet_automation":    onet_data,
        "aggregated_at":      datetime.utcnow().isoformat(),
    }


def _safe_mean(values: list) -> float:
    return round(sum(values) / len(values), 2) if values else 0.0
