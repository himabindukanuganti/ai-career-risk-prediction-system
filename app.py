import os, sys, re, json, asyncio, threading, webbrowser, time, sqlite3, secrets as _sec
from pathlib       import Path
from datetime      import datetime, timedelta, timezone
from typing        import List, Optional, Dict, Any
from database      import get_connection

# ── deps ──────────────────────────────────────────────────────────────────────
try:
    from fastapi import (FastAPI,Request,File, UploadFile, Form, HTTPException,
                         WebSocket, WebSocketDisconnect, Depends, status)
    from fastapi.responses  import HTMLResponse
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.staticfiles     import StaticFiles
    from fastapi.security        import OAuth2PasswordBearer, OAuth2PasswordRequestForm
    from pydantic import BaseModel
    import uvicorn
except ImportError:
    print("pip install fastapi uvicorn[standard] python-multipart httpx"); sys.exit(1)

try:    import httpx
except: print("pip install httpx"); sys.exit(1)

# ── Phase 4: Rate limiting ─────────────────────────────────────────────────────
try:
    from slowapi import Limiter, _rate_limit_exceeded_handler
    from slowapi.util import get_remote_address
    from slowapi.errors import RateLimitExceeded
    HAS_RATELIMIT = True
except ImportError:
    HAS_RATELIMIT = False

# ── Phase 4: Email ─────────────────────────────────────────────────────────────
try:
    import aiosmtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart
    HAS_EMAIL = True
except ImportError:
    HAS_EMAIL = False

# ── Phase 4: Sentry ────────────────────────────────────────────────────────────
try:
    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    HAS_SENTRY = True
except ImportError:
    HAS_SENTRY = False

# Patch bcrypt BEFORE passlib loads
try:
    import bcrypt as _bcrypt_mod, types as _types
    if not hasattr(_bcrypt_mod, '__about__'):
        _bcrypt_mod.__about__ = _types.SimpleNamespace(__version__='4.0.0')
except ImportError:
    pass

try:
    from jose       import JWTError, jwt
    from passlib.context import CryptContext
    HAS_JWT = True
except ImportError:
    HAS_JWT = False

try:    from dotenv import load_dotenv; load_dotenv()
except: pass

# ── config ────────────────────────────────────────────────────────────────────
PORT       = int(os.getenv("PORT", 8000))
HOST       = os.getenv("HOST", "127.0.0.1")
DEBUG      = os.getenv("DEBUG", "true").lower() == "true"
STATIC_DIR = Path(__file__).parent / "frontend"
DB_PATH    = Path(__file__).parent / "careerai.db"
CACHE_TTL  = int(os.getenv("CACHE_TTL_SECONDS", 3600))
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-CHANGE-before-deploy")
ALGO       = "HS256"
AT_EXP     = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 60))
RT_EXP     = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", 7))
ADZUNA_ID  = os.getenv("ADZUNA_APP_ID","");  ADZUNA_KEY = os.getenv("ADZUNA_APP_KEY","")
BLS_KEY    = os.getenv("BLS_API_KEY","")
ONET_USER  = os.getenv("ONET_USERNAME","");  ONET_PASS  = os.getenv("ONET_PASSWORD","")
YOUTUBE_KEY = os.getenv("YOUTUBE_API_KEY", "")
REED_KEY    = os.getenv("REED_API_KEY", "")

# ── Phase 4 config ───────────────────────────────────────────────────────────
RATE_LIMIT_PER_MIN  = int(os.getenv("RATE_LIMIT_PER_MINUTE", 60))
RATE_LIMIT_AUTH_MIN = int(os.getenv("RATE_LIMIT_AUTH_PER_MINUTE", 10))
ALLOWED_ORIGINS     = [o.strip() for o in os.getenv("ALLOWED_ORIGINS","*").split(",")]
SMTP_HOST   = os.getenv("SMTP_HOST", "")
SMTP_PORT   = int(os.getenv("SMTP_PORT", 587))
SMTP_USER   = os.getenv("SMTP_USER", "")
SMTP_PASS   = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM   = os.getenv("SMTP_FROM", "CareerAI <no-reply@careerai.app>")
SENTRY_DSN  = os.getenv("SENTRY_DSN", "")

# ── Startup security check ───────────────────────────────────────────────────
if SECRET_KEY == "dev-secret-CHANGE-before-deploy" and not DEBUG:
    print("\n⚠️  WARNING: Using default SECRET_KEY in production! Set SECRET_KEY in .env\n")
if SENTRY_DSN and HAS_SENTRY:
    sentry_sdk.init(dsn=SENTRY_DSN, integrations=[FastApiIntegration()],
                    traces_sample_rate=0.1, environment="production" if not DEBUG else "development")
    print("  Sentry error tracking: ✓")

TOP_ROLES  = ["data analyst","data engineer","ml engineer","software engineer",
              "devops engineer","product manager"]

# ── database ──────────────────────────────────────────────────────────────────
def init_db():
    c = get_connection()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS api_cache(key TEXT PRIMARY KEY,value TEXT,fetched_at TEXT);
    CREATE TABLE IF NOT EXISTS job_trends(id INTEGER PRIMARY KEY AUTOINCREMENT,
      role TEXT,date TEXT,posting_count INTEGER,avg_salary REAL,source TEXT,fetched_at TEXT,
      UNIQUE(role,date,source));
    CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT,email TEXT UNIQUE,password TEXT,role TEXT DEFAULT 'user',
      is_active INTEGER DEFAULT 1,created_at TEXT DEFAULT CURRENT_TIMESTAMP,last_login TEXT);
    CREATE TABLE IF NOT EXISTS refresh_tokens(id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id INTEGER,token TEXT UNIQUE,expires_at TEXT,revoked INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS pw_reset_tokens(id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id INTEGER,token TEXT UNIQUE,expires_at TEXT,used INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS user_profiles(id INTEGER PRIMARY KEY,user_id INTEGER UNIQUE,
      current_role TEXT,target_role TEXT,years_exp REAL DEFAULT 0,
      education_level REAL DEFAULT 0.5,skills TEXT,updated_at TEXT);
    CREATE TABLE IF NOT EXISTS saved_analyses(id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id INTEGER,type TEXT,title TEXT,data TEXT,
      created_at TEXT DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS model_registry(id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT,version TEXT,algorithm TEXT,artifact_path TEXT,
      metrics TEXT,params TEXT,trained_at TEXT,is_active INTEGER DEFAULT 1);
    """)
    c.commit(); c.close()

def cget(k):
    try:
        c = get_connection(); r=c.execute("SELECT value,fetched_at FROM api_cache WHERE key=?",(k,)).fetchone(); c.close()
        if not r: return None
        if datetime.now(timezone.utc)-datetime.fromisoformat(r[1].replace('Z','+00:00') if r[1].endswith('Z') else r[1]).replace(tzinfo=timezone.utc if '+' not in r[1] else None) > timedelta(seconds=CACHE_TTL): return None
        return json.loads(r[0])
    except: return None

def cset(k,v):
    try:
        c = get_connection()
        c.execute("INSERT OR REPLACE INTO api_cache(key,value,fetched_at)VALUES(?,?,?)",(k,json.dumps(v),datetime.now(timezone.utc).isoformat()))
        c.commit(); c.close()
    except: pass

def save_trend(role,count,salary,source):
    try:
        c = get_connection()
        c.execute("INSERT OR IGNORE INTO job_trends(role,date,posting_count,avg_salary,source,fetched_at)VALUES(?,?,?,?,?,?)",
                  (role,datetime.now(timezone.utc).date().isoformat(),count,salary,source,datetime.now(timezone.utc).isoformat()))
        c.commit(); c.close()
    except: pass

def trend_history(role,days=60):
    try:
        c = get_connection()
        rows=c.execute("SELECT date,posting_count,avg_salary FROM job_trends WHERE role=? ORDER BY date DESC LIMIT ?",(role,days)).fetchall()
        c.close(); return [{"date":r[0],"posting_count":r[1],"avg_salary":r[2]} for r in rows]
    except: return []

def log_model_registry(name,version,algorithm,artifact_path,metrics,params):
    try:
        c = get_connection()
        c.execute("UPDATE model_registry SET is_active=0 WHERE name=?", (name,))
        c.execute("INSERT INTO model_registry(name,version,algorithm,artifact_path,metrics,params,trained_at)VALUES(?,?,?,?,?,?,?)",
                  (name,version,algorithm,str(artifact_path),json.dumps(metrics),json.dumps(params),datetime.now(timezone.utc).isoformat()))
        c.commit(); c.close()
    except: pass

# ── auth helpers ──────────────────────────────────────────────────────────────
_pwd = CryptContext(schemes=["bcrypt"],deprecated="auto") if HAS_JWT else None
_oauth2 = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)

def _hash(pw):  return _pwd.hash(pw[:72]) if _pwd else pw
def _verify(plain,hashed): return _pwd.verify(plain[:72],hashed) if _pwd else plain==hashed

def _make_at(uid,email):
    if not HAS_JWT: return f"dev-{uid}"
    return jwt.encode({"sub":str(uid),"email":email,"type":"access",
                        "exp":datetime.now(timezone.utc)+timedelta(minutes=AT_EXP)},SECRET_KEY,algorithm=ALGO)

def _make_rt(uid):
    tok=_sec.token_urlsafe(64); exp=datetime.now(timezone.utc)+timedelta(days=RT_EXP)
    c = get_connection(); c.execute("INSERT INTO refresh_tokens(user_id,token,expires_at)VALUES(?,?,?)",(uid,tok,exp.isoformat())); c.commit(); c.close()
    return tok

def _decode(tok):
    if not HAS_JWT:
        if tok and tok.startswith("dev-"): return {"sub":tok.split("-")[1]}
        raise HTTPException(401,"Invalid token")
    try: return jwt.decode(tok,SECRET_KEY,algorithms=[ALGO])
    except JWTError: raise HTTPException(401,"Invalid or expired token",headers={"WWW-Authenticate":"Bearer"})

def _user_by_email(email):
    c = get_connection()
    r=c.execute("SELECT id,name,email,password,role,is_active,created_at FROM users WHERE email=?",(email,)).fetchone()
    c.close()
    return {"id":r[0],"name":r[1],"email":r[2],"password":r[3],"role":r[4],"is_active":r[5],"created_at":r[6]} if r else None

def _user_by_id(uid):
    c = get_connection()
    r=c.execute("SELECT id,name,email,role,is_active,created_at,last_login FROM users WHERE id=?",(uid,)).fetchone()
    c.close()
    return {"id":r[0],"name":r[1],"email":r[2],"role":r[3],"is_active":r[4],"created_at":r[5],"last_login":r[6]} if r else None

def _create_user(name,email,password):
    if _user_by_email(email): raise HTTPException(400,"Email already registered")
    c = get_connection()
    try:
        cur=c.execute("INSERT INTO users(name,email,password)VALUES(?,?,?)",(name,email,_hash(password))); c.commit(); uid=cur.lastrowid
    except sqlite3.IntegrityError:
        raise HTTPException(400,"Email already registered")
    finally: c.close()
    return _user_by_id(uid)

async def cur_user(token:str=Depends(_oauth2)):
    if not token: raise HTTPException(401,"Not authenticated",headers={"WWW-Authenticate":"Bearer"})
    p=_decode(token); uid=int(p.get("sub",0)); u=_user_by_id(uid)
    if not u or not u["is_active"]: raise HTTPException(401,"User not found")
    return u

async def admin_user(u:Dict=Depends(cur_user)):
    if u["role"] != "admin": raise HTTPException(403,"Admin access required")
    return u

# ── fallback data ─────────────────────────────────────────────────────────────
FB = {
    "data analyst":         {"count":12500,"salary":9.5, "yoy":0.05,"trend":"stable"},
    "data engineer":        {"count":8900, "salary":14.0,"yoy":0.20,"trend":"rising"},
    "ml engineer":          {"count":6200, "salary":19.0,"yoy":0.28,"trend":"rising"},
    "software engineer":    {"count":45000,"salary":11.0,"yoy":0.03,"trend":"stable"},
    "devops engineer":      {"count":7800, "salary":16.0,"yoy":0.22,"trend":"rising"},
    "product manager":      {"count":5500, "salary":21.0,"yoy":0.10,"trend":"rising"},
    "data entry specialist":{"count":4200, "salary":2.8, "yoy":-0.18,"trend":"declining"},
    "qa tester":            {"count":6100, "salary":5.1, "yoy":-0.10,"trend":"declining"},
}
FB_AUTO = {
    "data analyst":         {"routine":0.45,"ai_replace":0.42,"sector_auto":0.38},
    "data engineer":        {"routine":0.30,"ai_replace":0.28,"sector_auto":0.35},
    "ml engineer":          {"routine":0.20,"ai_replace":0.15,"sector_auto":0.30},
    "software engineer":    {"routine":0.35,"ai_replace":0.38,"sector_auto":0.40},
    "devops engineer":      {"routine":0.40,"ai_replace":0.35,"sector_auto":0.38},
    "data entry specialist":{"routine":0.92,"ai_replace":0.94,"sector_auto":0.88},
    "qa tester":            {"routine":0.72,"ai_replace":0.68,"sector_auto":0.62},
    "product manager":      {"routine":0.25,"ai_replace":0.30,"sector_auto":0.28},
    "accountant":           {"routine":0.78,"ai_replace":0.70,"sector_auto":0.65},
    "customer support":     {"routine":0.68,"ai_replace":0.72,"sector_auto":0.60},
}
ONET_SKILLS = {
    "python":"Dev","java":"Dev","javascript":"Web","typescript":"Web","c++":"Dev","go":"Dev",
    "sql":"DB","postgresql":"DB","mongodb":"DB","redis":"DB",
    "spark":"DataEng","kafka":"DataEng","airflow":"DataEng","dbt":"DataEng",
    "tableau":"Viz","power bi":"Viz","looker":"Viz",
    "machine learning":"AI","deep learning":"AI","tensorflow":"AI","pytorch":"AI",
    "scikit-learn":"AI","xgboost":"AI","nlp":"AI","llm":"GenAI","langchain":"GenAI",
    "aws":"Cloud","azure":"Cloud","gcp":"Cloud",
    "docker":"DevOps","kubernetes":"DevOps","terraform":"DevOps","git":"DevOps","ci/cd":"DevOps",
    "agile":"Mgmt","scrum":"Mgmt","leadership":"Soft",
}
ROLE_BENCH = {
    "data analyst":      ["sql","python","tableau","excel","statistics","power bi"],
    "data engineer":     ["python","sql","spark","kafka","airflow","dbt","aws","docker"],
    "ml engineer":       ["python","machine learning","deep learning","tensorflow","pytorch","docker","kubernetes"],
    "software engineer": ["python","java","sql","git","docker"],
    "devops engineer":   ["kubernetes","docker","terraform","aws","ci/cd"],
    "qa tester":         ["python","selenium","pytest","ci/cd","git"],
}
ONET_SOC = {
    "data analyst":"15-2041.00","ml engineer":"15-2051.02","software engineer":"15-1252.00",
    "data engineer":"15-1243.00","devops engineer":"15-1244.00",
    "product manager":"11-3021.00","qa tester":"15-1253.00",
}

# ── live API fetchers ─────────────────────────────────────────────────────────
async def adzuna(role):
    k=f"az:{role}"
    if v:=cget(k): return {**v,"source":"cache"}
    if not ADZUNA_ID:
        fb=FB.get(role.lower(),{"count":5000,"salary":10})
        return {"role":role,"posting_count":fb["count"],"avg_salary_lpa":fb["salary"],"source":"fallback"}
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r=await c.get("https://api.adzuna.com/v1/api/jobs/in/search/1",
              params={"app_id":ADZUNA_ID,"app_key":ADZUNA_KEY,"what":role,"results_per_page":10})
            d=r.json(); jobs=d.get("results",[])
            sals=[j.get("salary_max",0) for j in jobs if j.get("salary_max",0)>0]
            res={"role":role,"posting_count":d.get("count",0),
                 "avg_salary_lpa":round(sum(sals)/len(sals)/100000,2) if sals else 0,
                 "top_companies":list({j.get("company",{}).get("display_name","") for j in jobs if j.get("company")})[:5],
                 "top_locations":list({j.get("location",{}).get("display_name","") for j in jobs if j.get("location")})[:4],
                 "sample_titles":[j.get("title","") for j in jobs[:3]],
                 "fetched_at":datetime.now(timezone.utc).isoformat(),"source":"adzuna_live"}
            cset(k,res); save_trend(role,res["posting_count"],res["avg_salary_lpa"],"adzuna"); return res
    except Exception as e:
        fb=FB.get(role.lower(),{"count":5000,"salary":10})
        return {"role":role,"posting_count":fb["count"],"avg_salary_lpa":fb["salary"],"source":"fallback_error","error":str(e)}

async def onet_auto(role):
    soc=ONET_SOC.get(role.lower()); k=f"onet:auto:{soc or role}"
    if v:=cget(k): return v
    if not ONET_USER or not soc:
        fb=FB_AUTO.get(role.lower(),{"routine":0.5,"ai_replace":0.5,"sector_auto":0.5})
        return {**fb,"source":"fallback"}
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r=await c.get(f"https://services.onetcenter.org/ws/online/occupations/{soc}/summary/tasks",
              auth=(ONET_USER,ONET_PASS),headers={"Accept":"application/json"})
            tasks=r.json().get("task",[]); hi=sum(1 for t in tasks if t.get("importance",{}).get("value",0)>3.5)
            fb=FB_AUTO.get(role.lower(),{})
            res={"routine":round(1-hi/max(1,len(tasks)),2),"ai_replace":fb.get("ai_replace",0.5),
                 "sector_auto":fb.get("sector_auto",0.5),"soc_code":soc,"task_count":len(tasks),
                 "source":"onet_live","fetched_at":datetime.now(timezone.utc).isoformat()}
            cset(k,res); return res
    except Exception as e:
        fb=FB_AUTO.get(role.lower(),{"routine":0.5,"ai_replace":0.5,"sector_auto":0.5})
        return {**fb,"source":"error","error":str(e)}

async def onet_skills(role):
    soc=ONET_SOC.get(role.lower()); k=f"onet:sk:{soc or role}"
    if v:=cget(k): return v
    if not ONET_USER or not soc: return {"skills":ROLE_BENCH.get(role.lower(),[]),"source":"fallback"}
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r=await c.get(f"https://services.onetcenter.org/ws/online/occupations/{soc}/summary/skills",
              auth=(ONET_USER,ONET_PASS),headers={"Accept":"application/json"})
            raw=r.json().get("element",[]); skills=[s.get("name","").lower() for s in raw if s.get("score",{}).get("value",0)>=3][:10]
            res={"skills":skills or ROLE_BENCH.get(role.lower(),[]),"source":"onet_live"}
            cset(k,res); return res
    except: return {"skills":ROLE_BENCH.get(role.lower(),[]),"source":"fallback"}

async def coursera(skill, limit=8):
    k=f"ca:{skill}"
    if v:=cget(k): return v
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r=await c.get("https://api.coursera.org/api/courses.v1",
              params={"q":"search","query":skill,"fields":"name,slug,workload","limit":limit})
            res=[{"title":x.get("name",""),"platform":"Coursera",
                  "url":f"https://www.coursera.org/learn/{x.get('slug','')}",
                  "workload":x.get("workload",""),"source":"coursera_live"}
                 for x in r.json().get("elements",[])]
            cset(k,res); return res
    except: return []

async def remoteok(role):
    k=f"ro:{role}"
    if v:=cget(k): return v
    try:
        async with httpx.AsyncClient(timeout=10,headers={"User-Agent":"CareerAI/3.0"}) as c:
            r=await c.get("https://remoteok.com/api"); jobs=r.json()
            if isinstance(jobs,list): jobs=jobs[1:]
            f=[j for j in jobs if role.lower() in str(j.get("tags","")).lower() or role.lower() in str(j.get("position","")).lower()]
            res={"role":role,"total_remote":len(f),
                 "top_companies":list({j.get("company","") for j in f[:10] if j.get("company")})[:5],
                 "source":"remoteok_live","fetched_at":datetime.now(timezone.utc).isoformat()}
            cset(k,res); return res
    except Exception as e: return {"role":role,"total_remote":0,"source":"error","error":str(e)}

# ── NEW: Live recommendation fetchers ────────────────────────────────────────

async def youtube_tutorials(skill: str, limit: int = 4):
    """Fetch real YouTube tutorial videos for a skill."""
    k = f"yt:{skill}"
    if v := cget(k): return v
    if not YOUTUBE_KEY:
        return []
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(
                "https://www.googleapis.com/youtube/v3/search",
                params={
                    "part": "snippet",
                    "q": f"{skill} tutorial course 2024",
                    "type": "video",
                    "videoDuration": "long",
                    "relevanceLanguage": "en",
                    "maxResults": limit,
                    "key": YOUTUBE_KEY,
                }
            )
            items = r.json().get("items", [])
            res = [
                {
                    "title": i["snippet"]["title"],
                    "channel": i["snippet"]["channelTitle"],
                    "url": f"https://www.youtube.com/watch?v={i['id']['videoId']}",
                    "thumbnail": i["snippet"]["thumbnails"]["default"]["url"],
                    "platform": "YouTube",
                    "source": "youtube_live",
                    "matched_skill": skill,
                    "content_type": "video",
                }
                for i in items if i.get("id", {}).get("videoId")
            ]
            cset(k, res)
            return res
    except Exception as e:
        return []


async def github_trending_tools(role: str, limit: int = 5):
    """Fetch trending GitHub repos relevant to a role."""
    k = f"gh:{role}"
    if v := cget(k): return v
    role_topics = {
        "data analyst":         "data-analysis",
        "data engineer":        "data-engineering",
        "ml engineer":          "machine-learning",
        "software engineer":    "software-development",
        "devops engineer":      "devops",
        "product manager":      "product-management",
        "qa tester":            "testing",
        "data entry specialist":"automation",
        "accountant":           "finance",
        "customer support":     "customer-service",
    }
    topic = role_topics.get(role.lower(), role.lower().replace(" ", "-"))
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(
                "https://api.github.com/search/repositories",
                params={"q": f"topic:{topic}", "sort": "stars", "order": "desc", "per_page": limit},
                headers={"Accept": "application/vnd.github.v3+json"}
            )
            items = r.json().get("items", [])
            res = [
                {
                    "name": i["name"],
                    "description": (i.get("description") or "")[:120],
                    "url": i["html_url"],
                    "stars": i["stargazers_count"],
                    "language": i.get("language", ""),
                    "source": "github_live",
                }
                for i in items
            ]
            cset(k, res)
            return res
    except Exception as e:
        return []


async def bls_salary(role: str):
    """Fetch salary data from BLS.gov API."""
    k = f"bls:{role}"
    if v := cget(k): return v
    bls_series = {
        "data analyst":          "OEUS000000015204100",
        "data engineer":         "OEUS000000015124300",
        "ml engineer":           "OEUS000000015205100",
        "software engineer":     "OEUS000000015125200",
        "devops engineer":       "OEUS000000015124400",
        "product manager":       "OEUS000000011302100",
        "qa tester":             "OEUS000000015125300",
        "data entry specialist": "OEUS000000043906100",
        "accountant":            "OEUS000000013201100",
        "customer support":      "OEUS000000043405100",
    }
    series_id = bls_series.get(role.lower())
    if not BLS_KEY or not series_id:
        fb = FB.get(role.lower(), {"salary": 10.0})
        return {"annual_mean_usd": fb["salary"] * 8500, "annual_mean_inr": fb["salary"], "source": "fallback"}
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(
                "https://api.bls.gov/publicAPI/v2/timeseries/data/",
                json={
                    "seriesid": [series_id],
                    "startyear": "2022",
                    "endyear": "2024",
                    "registrationkey": BLS_KEY,
                }
            )
            data = r.json()
            series = data.get("Results", {}).get("series", [])
            if series:
                latest = series[0].get("data", [{}])[0]
                val = float(latest.get("value", "0").replace(",", ""))
                res = {
                    "annual_mean_usd": val,
                    "annual_mean_inr": round(val * 83.5 / 100000, 1),
                    "year": latest.get("year"),
                    "source": "bls_live",
                }
                cset(k, res)
                return res
    except Exception as e:
        pass
    fb = FB.get(role.lower(), {"salary": 10.0})
    return {"annual_mean_usd": fb["salary"] * 8500, "annual_mean_inr": fb["salary"], "source": "fallback"}


async def reed_jobs(role: str, limit: int = 5):
    """Fetch live jobs + salary from Reed API."""
    k = f"reed:{role}"
    if v := cget(k): return v
    if not REED_KEY:
        return {"total": 0, "avg_salary_gbp": 0, "jobs": [], "source": "no_key"}
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(
                "https://www.reed.co.uk/api/1.0/search",
                params={"keywords": role, "resultsToTake": limit},
                auth=(REED_KEY, ""),
            )
            data = r.json()
            jobs = data.get("results", [])
            sals = [j.get("maximumSalary", 0) for j in jobs if j.get("maximumSalary", 0) > 0]
            res = {
                "total": data.get("totalResults", 0),
                "avg_salary_gbp": round(sum(sals) / len(sals), 0) if sals else 0,
                "jobs": [
                    {
                        "title": j.get("jobTitle", ""),
                        "company": j.get("employerName", ""),
                        "salary": j.get("maximumSalary", 0),
                        "url": j.get("jobUrl", ""),
                        "location": j.get("locationName", ""),
                    }
                    for j in jobs[:5]
                ],
                "source": "reed_live",
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            }
            cset(k, res)
            return res
    except Exception as e:
        return {"total": 0, "avg_salary_gbp": 0, "jobs": [], "source": "error", "error": str(e)}


async def onet_career_paths(role: str):
    """Fetch related bright-outlook occupations (pivot roles) from O*NET."""
    soc = ONET_SOC.get(role.lower())
    k = f"onet:related:{soc or role}"
    if v := cget(k): return v
    if not ONET_USER or not soc:
        return []
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(
                f"https://services.onetcenter.org/ws/online/occupations/{soc}/related/bright_outlook",
                auth=(ONET_USER, ONET_PASS),
                headers={"Accept": "application/json"}
            )
            occs = r.json().get("occupation", [])
            res = [
                {
                    "role": o.get("title", ""),
                    "soc_code": o.get("code", ""),
                    "url": o.get("href", ""),
                    "source": "onet_live",
                }
                for o in occs[:5]
            ]
            # Enrich each pivot role with BLS salary
            for p in res:
                sal = await bls_salary(p["role"].lower())
                p["salary_lpa"] = sal.get("annual_mean_inr", 0)
                p["salary_source"] = sal.get("source", "fallback")
            cset(k, res)
            return res
    except Exception as e:
        return []


async def coursera_certifications(role: str, limit: int = 4):
    """Fetch Coursera professional certificates for a target role."""
    k = f"ca:cert:{role}"
    if v := cget(k): return v
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(
                "https://api.coursera.org/api/courses.v1",
                params={
                    "q": "search",
                    "query": f"{role} professional certificate",
                    "fields": "name,slug,workload",
                    "limit": limit,
                }
            )
            items = r.json().get("elements", [])
            res = [
                {
                    "title": x.get("name", ""),
                    "provider": "Coursera",
                    "url": f"https://www.coursera.org/learn/{x.get('slug', '')}",
                    "workload": x.get("workload", ""),
                    "type": "certification",
                    "source": "coursera_live",
                }
                for x in items
            ]
            cset(k, res)
            return res
    except Exception as e:
        return []


# ── NLP resume parser ─────────────────────────────────────────────────────────
def extract_text(fb,fname):
    ext=Path(fname).suffix.lower()
    if ext==".pdf":
        try: import fitz; d=fitz.open(stream=fb,filetype="pdf"); return "\n".join(p.get_text() for p in d)
        except: pass
    if ext in (".docx",".doc"):
        try:
            import docx as dx,io; return "\n".join(p.text for p in dx.Document(io.BytesIO(fb)).paragraphs)
        except: pass
    return fb.decode("utf-8",errors="ignore")

def parse_resume(text,target=""):
    tl=text.lower(); skills,seen=[],set()
    for sk,cat in ONET_SKILLS.items():
        if re.search(r'\b'+re.escape(sk)+r'\b',tl) and sk not in seen:
            seen.add(sk); ctx=tl[max(0,tl.find(sk)-80):tl.find(sk)+80]
            if any(w in ctx for w in ["expert","advanced","senior","lead"]): lv,sc="Advanced",0.88
            elif any(w in ctx for w in ["basic","familiar","beginner","learning"]): lv,sc="Beginner",0.25
            else: lv,sc="Intermediate",0.55
            skills.append({"name":sk.title(),"category":cat,"level":lv,"score":sc})
    em=re.search(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",text)
    ym=re.search(r"(\d+)\+?\s+years?\s+of\s+(experience|exp)",text,re.IGNORECASE)
    name=""
    try:
        import spacy; doc=spacy.load("en_core_web_lg")(text[:200])
        name=next((e.text for e in doc.ents if e.label_=="PERSON"),"")
    except: pass
    bench=ROLE_BENCH.get(target.lower(),[]); have={s["name"].lower() for s in skills}
    return {"name":name,"email":em.group(0) if em else "","years":float(ym.group(1)) if ym else 0.0,
            "skills":skills,"skill_gaps":[s for s in bench if s.lower() not in have],
            "skill_count":len(skills),"gap_count":len([s for s in bench if s.lower() not in have]),
            "confidence":round(sum([bool(name),bool(em),len(skills)>3,bool(ym)])/4,2)}

# ── XGBoost risk prediction (Phase 3) ─────────────────────────────────────────
async def risk_predict_xgb(role,years,n_sk,edu=0.5):
    occ      = await onet_auto(role)
    jobs     = await adzuna(role)
    hist     = trend_history(role,60)
    if len(hist)>=7 and hist[-1]["posting_count"]:
        yoy = round((hist[0]["posting_count"]-hist[-1]["posting_count"])/hist[-1]["posting_count"],3)
    else:
        yoy = FB.get(role.lower(),{}).get("yoy",0.05)
    remote_ratio = 0.30
    try:
        from ml.risk_model import predict_risk as xgb_predict
        result = xgb_predict(
            routine_task_ratio  = occ.get("routine",  0.5),
            ai_replaceability   = occ.get("ai_replace",0.5),
            sector_automation   = occ.get("sector_auto",0.5),
            n_skills            = n_sk,
            education_level     = edu,
            experience_years    = years,
            demand_growth       = yoy,
            remote_work_ratio   = remote_ratio,
        )
        return {"role": role.title(), **result, "onet_source": occ.get("source","fallback"), "demand_growth_used": yoy}
    except Exception as e:
        uniq = min(1.0,n_sk/20.0)
        sc   = min(100,round(occ.get("routine",0.5)*30+occ.get("ai_replace",0.5)*35+
                             occ.get("sector_auto",0.5)*15+(1-uniq)*10+(1-edu)*5+(1-min(1,years/20))*5,1))
        cat  = "Low" if sc<25 else "Medium" if sc<50 else "High" if sc<75 else "Critical"
        return {"role":role.title(),"risk_score":sc,"risk_category":cat,"viability_index":round(100-sc,1),
                "shap_values":{},"algorithm":"weighted_formula_fallback","error":str(e)}

# ── Prophet forecasting (Phase 3) ─────────────────────────────────────────────
async def get_forecast_prophet(role,horizon=5):
    jobs = await adzuna(role)
    hist = trend_history(role,365)
    cur_s = jobs.get("avg_salary_lpa") or FB.get(role.lower(),{}).get("salary",10.0)
    try:
        from ml.forecaster import forecast_with_prophet
        return forecast_with_prophet(role, hist, horizon, cur_s)
    except Exception as e:
        fb  = FB.get(role.lower(),{"yoy":0.05,"trend":"stable"})
        yoy = fb["yoy"]; cur_c = jobs.get("posting_count") or fb.get("count",5000)
        return {"role":role.title(),"current_postings":cur_c,"current_salary_lpa":cur_s,
                "yoy_growth":yoy,"trend_signal":fb["trend"],
                "forecast":[{"year":datetime.now(timezone.utc).year+i+1,
                             "postings_index":round(cur_c*((1+yoy)**(i+1))),
                             "salary_lpa":round(cur_s*((1+yoy*0.7)**(i+1)),2),
                             "method":"growth_rate_fallback"} for i in range(horizon)],
                "forecast_method":"growth_rate_fallback","error":str(e),
                "fetched_at":datetime.now(timezone.utc).isoformat()}

# ── Fully Live Recommendation Engine ─────────────────────────────────────────
async def recommend(cur: str, tgt: str, gaps: list, yrs: float = 2.0):
    """
    Fully live recommendations — Coursera, YouTube, GitHub, BLS, Reed, O*NET.
    Zero hardcoded data.
    """
    # Fetch all data concurrently
    (
        coursera_results,
        yt_results,
        gh_results,
        bls_cur,
        bls_tgt,
        reed_cur,
        reed_tgt,
        pivot_roles,
        cert_results,
    ) = await asyncio.gather(
        asyncio.gather(*[coursera(g, 3) for g in gaps[:4]], return_exceptions=True),
        asyncio.gather(*[youtube_tutorials(g, 2) for g in gaps[:4]], return_exceptions=True),
        github_trending_tools(tgt, 5),
        bls_salary(cur),
        bls_salary(tgt),
        reed_jobs(cur, 5),
        reed_jobs(tgt, 5),
        onet_career_paths(cur),
        coursera_certifications(tgt, 4),
        return_exceptions=True,
    )

    # Build courses list from Coursera + YouTube
    courses, seen = [], set()
    cr = coursera_results if isinstance(coursera_results, (list, tuple)) else []
    for skill, res in zip(gaps[:4], cr):
        if isinstance(res, list):
            for c in res:
                if c["title"] not in seen:
                    seen.add(c["title"])
                    courses.append({**c, "matched_skill": skill, "content_type": "course"})

    yr = yt_results if isinstance(yt_results, (list, tuple)) else []
    for skill, res in zip(gaps[:4], yr):
        if isinstance(res, list):
            for v in res:
                if v["title"] not in seen:
                    seen.add(v["title"])
                    courses.append({**v, "content_type": "video"})

    for i, c in enumerate(courses[:12]):
        c["phase"] = 1 if i < 4 else 2 if i < 8 else 3

    # Salary projection from BLS + Reed
    cur_sal = bls_cur.get("annual_mean_inr", 0) if isinstance(bls_cur, dict) else 0
    tgt_sal = bls_tgt.get("annual_mean_inr", 0) if isinstance(bls_tgt, dict) else 0
    reed_cur_avg = reed_cur.get("avg_salary_gbp", 0) if isinstance(reed_cur, dict) else 0
    reed_tgt_avg = reed_tgt.get("avg_salary_gbp", 0) if isinstance(reed_tgt, dict) else 0

    # Use Reed as supplement if BLS returns 0
    if cur_sal == 0 and reed_cur_avg > 0:
        cur_sal = round(reed_cur_avg * 83.5 / 100000, 1)
    if tgt_sal == 0 and reed_tgt_avg > 0:
        tgt_sal = round(reed_tgt_avg * 83.5 / 100000, 1)
    # Adzuna/fallback last resort
    if cur_sal == 0:
        cur_sal = FB.get(cur.lower(), {}).get("salary", 8.0)
    if tgt_sal == 0:
        tgt_sal = FB.get(tgt.lower(), {}).get("salary", 15.0)

    growth = (tgt_sal - cur_sal) / max(1, cur_sal)
    salary_projection = {
        "now":  f"₹{round(cur_sal, 1)} LPA",
        "6mo":  f"₹{round(cur_sal * (1 + growth * 0.3), 1)} LPA",
        "12mo": f"₹{round(cur_sal * (1 + growth * 0.65), 1)} LPA",
        "18mo": f"₹{round(tgt_sal, 1)} LPA",
        "bls_source":  bls_cur.get("source", "fallback") if isinstance(bls_cur, dict) else "fallback",
        "reed_source": reed_tgt.get("source", "fallback") if isinstance(reed_tgt, dict) else "fallback",
    }

    # Certifications from Coursera live
    certs = []
    if isinstance(cert_results, list):
        for cert in cert_results:
            certs.append({
                "title": cert["title"],
                "provider": "Coursera",
                "url": cert["url"],
                "workload": cert.get("workload", ""),
                "salary_lift_pct": round(abs(growth) * 100 * 0.4, 1),
                "source": cert.get("source", "coursera_live"),
            })

    # Pivot roles from O*NET live
    pivot_list = []
    if isinstance(pivot_roles, list):
        for p in pivot_roles:
            sal = p.get("salary_lpa", 0)
            pivot_list.append({
                "role": p["role"],
                "soc_code": p.get("soc_code", ""),
                "salary": f"₹{sal} LPA" if sal else "See O*NET",
                "months": 9,
                "feasibility": min(0.95, 0.6 + (1 / max(1, len(gaps))) * 0.3),
                "source": p.get("source", "onet_live"),
                "url": p.get("url", ""),
            })

    # GitHub trending tools
    gh_tools = gh_results if isinstance(gh_results, list) else []

    # Reed live jobs data
    live_jobs = {
        "current_role_openings": reed_cur.get("total", 0) if isinstance(reed_cur, dict) else 0,
        "target_role_openings":  reed_tgt.get("total", 0) if isinstance(reed_tgt, dict) else 0,
        "sample_target_jobs":    reed_tgt.get("jobs", []) if isinstance(reed_tgt, dict) else [],
        "source": "reed_live",
    }

    phases = [
        {
            "phase": i + 1,
            "label": ["Months 1–6", "Months 7–12", "Months 13–18"][i],
            "theme": ["Foundations & Core Skills", "Production & Projects", "Advanced & Portfolio"][i],
            "courses": [c["title"] for c in courses[:12] if c.get("phase") == i + 1],
        }
        for i in range(3)
    ]

    return {
        "current_role":      cur.title(),
        "target_role":       tgt.title(),
        "total_months":      18,
        "courses":           courses[:12],
        "live_course_count": len([c for c in courses if "live" in c.get("source", "")]),
        "certifications":    certs,
        "pivot_roles":       pivot_list,
        "github_tools":      gh_tools,
        "live_jobs":         live_jobs,
        "salary_projection": salary_projection,
        "phases":            phases,
        "data_sources": {
            "courses":     "Coursera API (live)",
            "videos":      "YouTube Data API v3 (live)" if YOUTUBE_KEY else "not configured — add YOUTUBE_API_KEY",
            "github":      "GitHub Search API (live)",
            "salary":      f"BLS.gov ({bls_cur.get('source','?')})" if isinstance(bls_cur, dict) else "BLS.gov",
            "jobs":        f"Reed API ({reed_tgt.get('source','?')})" if isinstance(reed_tgt, dict) else "Reed API",
            "pivot_roles": "O*NET Bright Outlook (live)" if ONET_USER else "not configured",
        },
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }

# ── pydantic models ───────────────────────────────────────────────────────────
class RegReq(BaseModel):  name:str; email:str; password:str
class RefReq(BaseModel):  refresh_token:str
class SkillIn(BaseModel): skill_name:str; level:Optional[str]="Intermediate"
class GapReq(BaseModel):  current_skills:List[SkillIn]; target_role:str
class RiskReq(BaseModel): role:str; years_exp:float; n_skills:int=10; education_level:float=0.5
class RoadReq(BaseModel): current_role:str; target_role:str; skill_gaps:List[str]; years_exp:float=2.0
class ProfUpd(BaseModel): current_role:Optional[str]=None; target_role:Optional[str]=None; years_exp:Optional[float]=None; education_level:Optional[float]=None; skills:Optional[List[str]]=None
class SaveReq(BaseModel): type:str; title:str; data:Dict
class PwReq(BaseModel):   email:str
class PwConf(BaseModel):  token:str; new_password:str

# ── app ───────────────────────────────────────────────────────────────────────
from contextlib import asynccontextmanager

_BACKEND_DIR = Path(__file__).parent / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

@asynccontextmanager
async def lifespan(application: FastAPI):
    global _scheduler
    init_db()
    try:
        from ml.risk_model import get_model, MODEL_PATH, META_PATH
        get_model()
        if META_PATH.exists():
            with open(META_PATH) as f: meta = json.load(f)
            log_model_registry("risk_model", meta.get("model_version","3.0.0"),
                               "XGBoostClassifier", str(MODEL_PATH),
                               meta.get("metrics",{}), {"n_estimators":200,"max_depth":4})
        print("  XGBoost risk model ready")
    except Exception as e:
        print(f"  XGBoost load warning: {e}")
    try:
        from scheduler.job import create_scheduler
        _scheduler = create_scheduler(DB_PATH, TOP_ROLES)
        _scheduler.start()
        print("  APScheduler started (retraining every Sunday)")
    except Exception as e:
        print(f"  Scheduler warning: {e}")
    yield
    if _scheduler:
        _scheduler.shutdown(wait=False)

app=FastAPI(title="CareerAI",description="Career Risk & Prediction System",version="4.0.0",lifespan=lifespan)
app.add_middleware(CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS if "*" not in ALLOWED_ORIGINS else ["*"],
    allow_methods=["*"],allow_headers=["*"],allow_credentials=True)

if HAS_RATELIMIT:
    limiter = Limiter(key_func=get_remote_address)
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    def rate_limit(rate:str):
        return limiter.limit(rate)
else:
    limiter = None
    def rate_limit(rate:str):
        def decorator(f): return f
        return decorator

ASSETS_DIR = STATIC_DIR / "assets"
if ASSETS_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(ASSETS_DIR)), name="assets")

class _WS:
    def __init__(self): self.c=[]
    async def connect(self,ws): await ws.accept(); self.c.append(ws)
    def disconnect(self,ws):
        if ws in self.c: self.c.remove(ws)
_ws=_WS()

_scheduler = None

from fastapi.responses import FileResponse, Response

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    fav = STATIC_DIR / "favicon.ico"
    return FileResponse(str(fav)) if fav.exists() else Response(status_code=204)

@app.get("/live_connect.js", include_in_schema=False)
async def live_connect():
    js = STATIC_DIR / "live_connect.js"
    if js.exists(): return FileResponse(str(js), media_type="application/javascript")
    return Response(content='(function(){console.log("CareerAI live_connect stub");})()',media_type="application/javascript")

@app.get("/", response_class=HTMLResponse)
async def root():
    idx = STATIC_DIR / "index.html"
    return HTMLResponse(idx.read_text(encoding="utf-8") if idx.exists() else _html())

@app.get("/health")
async def health():
    db_ok = True
    try: c=sqlite3.connect(DB_PATH); c.execute("SELECT 1"); c.close()
    except: db_ok = False
    model_trained=False; model_version="not_trained"
    try:
        from ml.risk_model import MODEL_PATH, META_PATH
        model_trained = MODEL_PATH.exists()
        model_version = json.load(open(META_PATH))["model_version"] if META_PATH.exists() else "not_trained"
    except: pass
    return {"status":"healthy","version":"4.0.0","phase":4,
            "auth":HAS_JWT,"db":db_ok,
            "rate_limiting":HAS_RATELIMIT,"email_configured":bool(SMTP_HOST),"sentry":bool(SENTRY_DSN),
            "xgboost_model_ready":model_trained,"model_version":model_version,
            "scheduler_running":_scheduler is not None and getattr(_scheduler,"running",False),
            "apis":{"adzuna":bool(ADZUNA_ID),"bls":bool(BLS_KEY),"onet":bool(ONET_USER),
                    "youtube":bool(YOUTUBE_KEY),"reed":bool(REED_KEY),
                    "coursera":True,"remoteok":True,"github":True,"smtp":bool(SMTP_HOST)}}

@app.get("/api/v1/status")
async def api_status():
    return {"adzuna":{"live":bool(ADZUNA_ID),"register":"developer.adzuna.com"},
            "bls":{"live":bool(BLS_KEY),"register":"bls.gov/developers"},
            "onet":{"live":bool(ONET_USER),"register":"services.onetcenter.org"},
            "youtube":{"live":bool(YOUTUBE_KEY),"register":"console.cloud.google.com"},
            "reed":{"live":bool(REED_KEY),"register":"reed.co.uk/developers"},
            "coursera":{"live":True},"remoteok":{"live":True},"github":{"live":True}}

# ── auth routes ───────────────────────────────────────────────────────────────
@app.post("/api/v1/auth/register",status_code=201)
@rate_limit("10/minute")
async def auth_reg(req:RegReq, request:Request):
    if len(req.password)<8: raise HTTPException(400,"Password must be ≥8 characters")
    if not re.match(r"[^@]+@[^@]+\.[^@]+",req.email): raise HTTPException(400,"Invalid email")
    u=_create_user(req.name,req.email,req.password)
    return {"access_token":_make_at(u["id"],u["email"]),"refresh_token":_make_rt(u["id"]),
            "token_type":"bearer","user":{"id":u["id"],"name":u["name"],"email":u["email"]}}

@app.post("/api/v1/auth/login")
@rate_limit("10/minute")
async def auth_login(form:OAuth2PasswordRequestForm=Depends(), request:Request=None):
    u=_user_by_email(form.username)
    if not u or not _verify(form.password,u["password"]): raise HTTPException(401,"Invalid credentials")
    if not u["is_active"]: raise HTTPException(403,"Account deactivated")
    c=sqlite3.connect(DB_PATH); c.execute("UPDATE users SET last_login=? WHERE id=?",(datetime.now(timezone.utc).isoformat(),u["id"])); c.commit(); c.close()
    return {"access_token":_make_at(u["id"],u["email"]),"refresh_token":_make_rt(u["id"]),
            "token_type":"bearer","user":{"id":u["id"],"name":u["name"],"email":u["email"]}}

@app.post("/api/v1/auth/refresh")
def auth_refresh(req:RefReq):
    c=sqlite3.connect(DB_PATH); r=c.execute("SELECT user_id,expires_at,revoked FROM refresh_tokens WHERE token=?",(req.refresh_token,)).fetchone(); c.close()
    if not r: raise HTTPException(401,"Invalid refresh token")
    if r[2]: raise HTTPException(401,"Token revoked")
    if datetime.fromisoformat(r[1])<datetime.now(timezone.utc): raise HTTPException(401,"Token expired")
    u=_user_by_id(r[0]); return {"access_token":_make_at(u["id"],u["email"]),"token_type":"bearer"}

@app.post("/api/v1/auth/logout")
def auth_logout(req:RefReq):
    c=sqlite3.connect(DB_PATH); c.execute("UPDATE refresh_tokens SET revoked=1 WHERE token=?",(req.refresh_token,)); c.commit(); c.close()
    return {"message":"Logged out"}

@app.get("/api/v1/auth/me")
def auth_me(u:Dict=Depends(cur_user)): return u

# ── Email helper ──────────────────────────────────────────────────────────────
async def send_email(to:str, subject:str, body_html:str) -> bool:
    if not (SMTP_HOST and SMTP_USER and SMTP_PASS):
        print(f"  [EMAIL not configured] To:{to} | Subject:{subject}")
        return False
    if not HAS_EMAIL:
        print("  [EMAIL] pip install aiosmtplib"); return False
    try:
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        msg = MIMEMultipart("alternative")
        msg["Subject"]=subject; msg["From"]=SMTP_FROM; msg["To"]=to
        msg.attach(MIMEText(body_html,"html"))
        await aiosmtplib.send(msg,hostname=SMTP_HOST,port=SMTP_PORT,
                              username=SMTP_USER,password=SMTP_PASS,start_tls=True)
        return True
    except Exception as e:
        print(f"  [EMAIL ERROR] {e}"); return False

def _pw_reset_email_html(name:str, token:str, base_url:str) -> str:
    link = f"{base_url}/reset-password?token={token}"
    return (f'<html><body style="font-family:sans-serif;max-width:480px;margin:40px auto">'
            f'<h2 style="color:#1a1a18">Reset your CareerAI password</h2>'
            f'<p>Hi {name},</p>'
            f'<p>Click below to reset your password. Expires in <b>1 hour</b>.</p>'
            f'<a href="{link}" style="display:inline-block;padding:12px 28px;'
            f'background:#1D9E75;color:#fff;border-radius:8px;text-decoration:none;'
            f'font-weight:600;margin:16px 0">Reset Password</a>'
            f'<p style="color:#888;font-size:12px">If you did not request this, ignore this email.<br>'
            f'Link: {link}</p></body></html>')

@app.post("/api/v1/auth/password-reset/request")
async def pw_req(req:PwReq, request:Request):
    u=_user_by_email(req.email)
    if not u: return {"message":"If that email exists a reset link was sent"}
    tok=_sec.token_urlsafe(32); exp=datetime.now(timezone.utc)+timedelta(hours=1)
    c=sqlite3.connect(DB_PATH); c.execute("INSERT INTO pw_reset_tokens(user_id,token,expires_at)VALUES(?,?,?)",(u["id"],tok,exp.isoformat())); c.commit(); c.close()
    base = str(request.base_url).rstrip("/")
    html = _pw_reset_email_html(u["name"] or u["email"], tok, base)
    sent = await send_email(u["email"], "Reset your CareerAI password", html)
    resp = {"message":"If that email exists a reset link was sent"}
    if DEBUG: resp["dev_token"] = tok
    if DEBUG: resp["email_sent"] = sent
    return resp

@app.post("/api/v1/auth/password-reset/confirm")
def pw_confirm(req:PwConf):
    c=sqlite3.connect(DB_PATH); r=c.execute("SELECT user_id,expires_at,used FROM pw_reset_tokens WHERE token=?",(req.token,)).fetchone()
    if not r or r[2]: c.close(); raise HTTPException(400,"Invalid or used token")
    if datetime.fromisoformat(r[1])<datetime.now(timezone.utc): c.close(); raise HTTPException(400,"Token expired")
    if len(req.new_password)<8: c.close(); raise HTTPException(400,"Password ≥8 characters")
    c.execute("UPDATE users SET password=? WHERE id=?",(_hash(req.new_password),r[0]))
    c.execute("UPDATE pw_reset_tokens SET used=1 WHERE token=?",(req.token,)); c.commit(); c.close()
    return {"message":"Password reset successfully"}

# ── user profile routes ───────────────────────────────────────────────────────
@app.get("/api/v1/user/profile")
def get_prof(u:Dict=Depends(cur_user)):
    c=sqlite3.connect(DB_PATH); r=c.execute("SELECT current_role,target_role,years_exp,education_level,skills,updated_at FROM user_profiles WHERE user_id=?",(u["id"],)).fetchone(); c.close()
    if not r: return {"user_id":u["id"],"current_role":None,"skills":[]}
    return {"user_id":u["id"],"current_role":r[0],"target_role":r[1],"years_exp":r[2],"education_level":r[3],"skills":json.loads(r[4]) if r[4] else [],"updated_at":r[5]}

@app.put("/api/v1/user/profile")
def upd_prof(req:ProfUpd,u:Dict=Depends(cur_user)):
    c=sqlite3.connect(DB_PATH); ex=c.execute("SELECT id FROM user_profiles WHERE user_id=?",(u["id"],)).fetchone()
    sk=json.dumps(req.skills) if req.skills is not None else None; now=datetime.now(timezone.utc).isoformat()
    if ex:
        ups,vals=[],[]
        for f,v in [("current_role",req.current_role),("target_role",req.target_role),("years_exp",req.years_exp),("education_level",req.education_level),("skills",sk),("updated_at",now)]:
            if v is not None: ups.append(f"{f}=?"); vals.append(v)
        if ups: vals.append(u["id"]); c.execute(f"UPDATE user_profiles SET {','.join(ups)} WHERE user_id=?",vals)
    else:
        c.execute("INSERT INTO user_profiles(user_id,current_role,target_role,years_exp,education_level,skills,updated_at)VALUES(?,?,?,?,?,?,?)",
                  (u["id"],req.current_role,req.target_role,req.years_exp or 0,req.education_level or 0.5,sk,now))
    c.commit(); c.close(); return {"message":"Profile updated","updated_at":now}

@app.post("/api/v1/user/analyses")
def save_ana(req:SaveReq,u:Dict=Depends(cur_user)):
    c=sqlite3.connect(DB_PATH); cur=c.execute("INSERT INTO saved_analyses(user_id,type,title,data)VALUES(?,?,?,?)",(u["id"],req.type,req.title,json.dumps(req.data))); c.commit(); aid=cur.lastrowid; c.close()
    return {"message":"Saved","id":aid}

@app.get("/api/v1/user/analyses")
def list_ana(u:Dict=Depends(cur_user)):
    c=sqlite3.connect(DB_PATH); rows=c.execute("SELECT id,type,title,created_at FROM saved_analyses WHERE user_id=? ORDER BY created_at DESC",(u["id"],)).fetchall(); c.close()
    return {"analyses":[{"id":r[0],"type":r[1],"title":r[2],"created_at":r[3]} for r in rows]}

@app.get("/api/v1/user/analyses/{aid}")
def get_ana(aid:int,u:Dict=Depends(cur_user)):
    c=sqlite3.connect(DB_PATH); r=c.execute("SELECT id,type,title,data,created_at FROM saved_analyses WHERE id=? AND user_id=?",(aid,u["id"])).fetchone(); c.close()
    if not r: raise HTTPException(404,"Not found")
    return {"id":r[0],"type":r[1],"title":r[2],"data":json.loads(r[3]),"created_at":r[4]}

@app.delete("/api/v1/user/analyses/{aid}")
def del_ana(aid:int,u:Dict=Depends(cur_user)):
    c=sqlite3.connect(DB_PATH); c.execute("DELETE FROM saved_analyses WHERE id=? AND user_id=?",(aid,u["id"])); c.commit(); c.close()
    return {"message":"Deleted"}

@app.get("/api/v1/user/dashboard-summary")
def dash_sum(u:Dict=Depends(cur_user)):
    c=sqlite3.connect(DB_PATH)
    prof=c.execute("SELECT current_role,target_role,years_exp FROM user_profiles WHERE user_id=?",(u["id"],)).fetchone()
    anas=c.execute("SELECT type,COUNT(*) FROM saved_analyses WHERE user_id=? GROUP BY type",(u["id"],)).fetchall()
    c.close()
    return {"user":{"name":u["name"],"email":u["email"]},
            "profile":{"current_role":prof[0] if prof else None,"target_role":prof[1] if prof else None,"years_exp":prof[2] if prof else None},
            "analyses":{r[0]:r[1] for r in anas},"total_saved":sum(r[1] for r in anas)}

# ── career API routes ─────────────────────────────────────────────────────────
@app.post("/api/v1/resume/parse")
@rate_limit("20/minute")
async def api_parse(request:Request, file:UploadFile=File(...), target_role:str=Form(default=""), u:Dict=Depends(cur_user)):
    if Path(file.filename).suffix.lower() not in {".pdf",".docx",".doc",".txt"}: raise HTTPException(400,"Unsupported format")
    data=await file.read()
    if len(data)>5*1024*1024: raise HTTPException(413,"Max 5 MB")
    return {"status":"success","filename":file.filename,"parsed_by":u["name"],**parse_resume(extract_text(data,file.filename),target_role)}

@app.post("/api/v1/skills/gap-analysis")
async def api_gap(req:GapReq,u:Dict=Depends(cur_user)):
    sk=await onet_skills(req.target_role); bench=sk.get("skills") or ROLE_BENCH.get(req.target_role.lower(),[])
    have={s.skill_name.lower() for s in req.current_skills}; gaps=[s for s in bench if s.lower() not in have]; matched=[s for s in bench if s.lower() in have]
    return {"target_role":req.target_role,"gaps":gaps,"matched":matched,"match_pct":round(len(matched)/max(1,len(bench))*100,1),"data_source":sk.get("source")}

@app.get("/api/v1/skills/benchmarks/{role}")
async def api_bench(role:str,u:Dict=Depends(cur_user)):
    sk=await onet_skills(role); return {"role":role,"required_skills":sk.get("skills",[]),"source":sk.get("source")}

@app.post("/api/v1/risk/predict")
@rate_limit("30/minute")
async def api_risk(request:Request, req:RiskReq, u:Dict=Depends(cur_user)):
    return await risk_predict_xgb(req.role,req.years_exp,req.n_skills,req.education_level)

@app.get("/api/v1/risk/automation-index/{role}")
async def api_auto(role:str,u:Dict=Depends(cur_user)): return await onet_auto(role)

@app.get("/api/v1/risk/model-info")
async def api_model_info(u:Dict=Depends(cur_user)):
    try:
        from ml.risk_model import META_PATH
        if META_PATH.exists(): return json.load(open(META_PATH))
        return {"status":"not_trained"}
    except Exception as e:
        return {"status":"error","error":str(e)}

@app.get("/api/v1/trends/{role}")
async def api_fc(role:str,horizon:int=5,u:Dict=Depends(cur_user)):
    return await get_forecast_prophet(role, horizon)

@app.get("/api/v1/trends/overview/all")
async def api_ov(u:Dict=Depends(cur_user)):
    roles=list(FB.keys())[:6]; res=await asyncio.gather(*[adzuna(r) for r in roles],return_exceptions=True)
    return {"roles":[{"role":r.title(),"posting_count":d.get("posting_count",0) if not isinstance(d,Exception) else 0,"source":d.get("source","error") if not isinstance(d,Exception) else "error"} for r,d in zip(roles,res)],"fetched_at":datetime.now(timezone.utc).isoformat()}

@app.get("/api/v1/trends/remote/{role}")
async def api_ro(role:str,u:Dict=Depends(cur_user)): return await remoteok(role)

@app.get("/api/v1/trends/history/{role}")
async def api_history(role:str,days:int=60,u:Dict=Depends(cur_user)):
    return {"role":role,"history":trend_history(role,days)}

@app.post("/api/v1/recommend/roadmap")
async def api_road(req:RoadReq,u:Dict=Depends(cur_user)):
    return await recommend(req.current_role,req.target_role,req.skill_gaps,req.years_exp)

@app.get("/api/v1/recommend/courses/{skill}")
async def api_ca(skill:str,limit:int=10,u:Dict=Depends(cur_user)):
    c=await coursera(skill,limit); return {"skill":skill,"count":len(c),"courses":c}

# ── New live recommendation endpoints ────────────────────────────────────────
@app.get("/api/v1/recommend/youtube/{skill}")
async def api_youtube(skill:str,u:Dict=Depends(cur_user)):
    vids=await youtube_tutorials(skill,6)
    return {"skill":skill,"count":len(vids),"videos":vids,"youtube_configured":bool(YOUTUBE_KEY)}

@app.get("/api/v1/recommend/github/{role}")
async def api_github(role:str,u:Dict=Depends(cur_user)):
    repos=await github_trending_tools(role,8)
    return {"role":role,"count":len(repos),"repos":repos}

@app.get("/api/v1/recommend/salary/{role}")
async def api_salary(role:str,u:Dict=Depends(cur_user)):
    bls=await bls_salary(role); reed=await reed_jobs(role,3)
    return {"role":role,"bls":bls,"reed":reed}

@app.get("/api/v1/recommend/pivot-roles/{role}")
async def api_pivot(role:str,u:Dict=Depends(cur_user)):
    pivots=await onet_career_paths(role)
    return {"role":role,"pivot_roles":pivots,"source":"onet_bright_outlook"}

# ── Admin routes ──────────────────────────────────────────────────────────────
@app.get("/api/v1/admin/stats")
def admin_stats(u:Dict=Depends(admin_user)):
    c=sqlite3.connect(DB_PATH)
    total_users    = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    active_users   = c.execute("SELECT COUNT(*) FROM users WHERE is_active=1").fetchone()[0]
    total_analyses = c.execute("SELECT COUNT(*) FROM saved_analyses").fetchone()[0]
    cache_entries  = c.execute("SELECT COUNT(*) FROM api_cache").fetchone()[0]
    trend_points   = c.execute("SELECT COUNT(*) FROM job_trends").fetchone()[0]
    models         = c.execute("SELECT name,version,algorithm,trained_at,is_active FROM model_registry ORDER BY trained_at DESC LIMIT 10").fetchall()
    c.close()
    return {
        "users":   {"total":total_users,"active":active_users},
        "analyses":{"total":total_analyses},
        "cache":   {"entries":cache_entries},
        "trends":  {"data_points":trend_points},
        "models":  [{"name":r[0],"version":r[1],"algorithm":r[2],"trained_at":r[3],"active":bool(r[4])} for r in models],
        "scheduler_jobs": [{"id":j.id,"name":j.name,"next_run":str(j.next_run_time)} for j in (_scheduler.get_jobs() if _scheduler else [])],
    }

@app.post("/api/v1/admin/retrain")
async def admin_retrain(u:Dict=Depends(admin_user)):
    try:
        from ml.risk_model import train_model, reload_model, MODEL_PATH, META_PATH
        result = train_model(track_with_mlflow=False)
        reload_model()
        m = result["metrics"]
        log_model_registry("risk_model","3.0.0","XGBoostClassifier",str(MODEL_PATH),m,{})
        return {"message":"Retraining complete","metrics":m}
    except Exception as e:
        raise HTTPException(500,f"Retraining failed: {e}")

@app.post("/api/v1/admin/retrain-forecaster/{role}")
async def admin_retrain_forecast(role:str,u:Dict=Depends(admin_user)):
    hist=trend_history(role,365)
    if len(hist)<14: raise HTTPException(400,f"Need ≥14 data points, have {len(hist)}")
    try:
        from ml.forecaster import train_prophet
        model=train_prophet(role,hist)
        if model: return {"message":f"Prophet retrained for '{role}'","data_points":len(hist)}
        raise HTTPException(500,"Training returned None")
    except Exception as e:
        raise HTTPException(500,f"Forecast retraining failed: {e}")

@app.get("/api/v1/admin/users")
def admin_users(u:Dict=Depends(admin_user),limit:int=50,offset:int=0):
    c=sqlite3.connect(DB_PATH)
    rows=c.execute("SELECT id,name,email,role,is_active,created_at,last_login FROM users ORDER BY created_at DESC LIMIT ? OFFSET ?",(limit,offset)).fetchall()
    total=c.execute("SELECT COUNT(*) FROM users").fetchone()[0]; c.close()
    return {"total":total,"users":[{"id":r[0],"name":r[1],"email":r[2],"role":r[3],"active":bool(r[4]),"created_at":r[5],"last_login":r[6]} for r in rows]}

@app.patch("/api/v1/admin/users/{uid}/deactivate")
def admin_deactivate(uid:int,u:Dict=Depends(admin_user)):
    c=sqlite3.connect(DB_PATH); c.execute("UPDATE users SET is_active=0 WHERE id=?",(uid,)); c.commit(); c.close()
    return {"message":f"User {uid} deactivated"}

@app.post("/api/v1/admin/make-first-admin")
def make_first_admin(u:Dict=Depends(cur_user)):
    c=sqlite3.connect(DB_PATH)
    existing=c.execute("SELECT id FROM users WHERE role='admin'").fetchone()
    if existing: c.close(); raise HTTPException(409,"An admin already exists")
    c.execute("UPDATE users SET role='admin' WHERE id=?",(u["id"],))
    c.commit(); c.close()
    return {"message":f"{u['name']} is now admin","user_id":u["id"]}

# ── WebSocket ─────────────────────────────────────────────────────────────────
@app.websocket("/ws/trends")
async def ws_trends(ws:WebSocket,token:str=""):
    await _ws.connect(ws)
    try:
        while True:
            r=await remoteok("data"); await ws.send_json({"type":"live_update","remote_jobs":r.get("total_remote",0),"timestamp":datetime.now(timezone.utc).isoformat()})
            await asyncio.sleep(60)
    except WebSocketDisconnect: _ws.disconnect(ws)

@app.websocket("/ws/risk/{role}")
async def ws_risk(ws:WebSocket,role:str,token:str=""):
    await _ws.connect(ws)
    try:
        while True:
            r=await risk_predict_xgb(role,3,10)
            r["timestamp"]=datetime.now(timezone.utc).isoformat(); await ws.send_json(r); await asyncio.sleep(30)
    except WebSocketDisconnect: _ws.disconnect(ws)

# ── SPA catch-all ─────────────────────────────────────────────────────────────
@app.get("/{full_path:path}", response_class=HTMLResponse, include_in_schema=False)
async def spa_fallback(full_path:str):
    idx=STATIC_DIR/"index.html"
    if idx.exists(): return HTMLResponse(idx.read_text(encoding="utf-8"))
    raise HTTPException(status_code=404)

# ── welcome html ──────────────────────────────────────────────────────────────
def _html():
    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"/><title>CareerAI Phase 4</title>
<style>body{{font-family:system-ui,sans-serif;max-width:640px;margin:50px auto;padding:0 20px;background:#f8f7f4}}
.hero{{background:#1a1a18;color:#fff;border-radius:12px;padding:24px;margin-bottom:14px}}
.hero h1{{font-size:20px;font-weight:700;color:#fff}}.hero p{{color:rgba(255,255,255,.55);font-size:13px;margin-top:6px}}
.card{{background:#fff;border:0.5px solid #ddd;border-radius:10px;padding:14px 16px;margin-bottom:10px}}
h3{{font-size:13px;font-weight:600;margin-bottom:7px}}.ep{{font-family:monospace;font-size:11px;background:#f5f4ef;padding:3px 8px;border-radius:4px;display:block;margin:2px 0}}
.m{{display:inline-block;padding:1px 7px;border-radius:4px;font-size:10px;font-weight:700;margin-right:5px}}
.get{{background:#E6F1FB;color:#042C53}}.post{{background:#E1F5EE;color:#085041}}
a{{color:#1D9E75;text-decoration:none;font-weight:600}}</style></head>
<body><div class="hero">
<h1>CareerAI Phase 4 <span style="background:#4ade80;color:#000;font-size:10px;padding:2px 8px;border-radius:20px;margin-left:8px">RUNNING</span></h1>
<p>Fully live recommendations · YouTube · GitHub · BLS · Reed · O*NET<br>
<a href="/docs" style="color:#4ade80">Full API docs at /docs</a></p></div>
<div class="card"><h3>Live Recommendation APIs</h3>
<span class="ep"><span class="m get">GET</span>/api/v1/recommend/youtube/{{skill}} — YouTube tutorials</span>
<span class="ep"><span class="m get">GET</span>/api/v1/recommend/github/{{role}} — GitHub trending repos</span>
<span class="ep"><span class="m get">GET</span>/api/v1/recommend/salary/{{role}} — BLS + Reed salary data</span>
<span class="ep"><span class="m get">GET</span>/api/v1/recommend/pivot-roles/{{role}} — O*NET career paths</span>
<span class="ep"><span class="m post">POST</span>/api/v1/recommend/roadmap — Full live roadmap</span></div>
</body></html>"""

# ── entry point ───────────────────────────────────────────────────────────────
def _open(): time.sleep(2); webbrowser.open(f"http://{HOST}:{PORT}")

if __name__=="__main__":
    print(f"\n{'═'*52}\n  CareerAI Phase 4 — Fully Live Recommendations\n{'═'*52}")
    print(f"\n  App  →  http://{HOST}:{PORT}")
    print(f"  Docs →  http://{HOST}:{PORT}/docs")
    print(f"\n  APIs configured:")
    print(f"    Adzuna   : {'✓' if os.getenv('ADZUNA_APP_ID') else '✗'}")
    print(f"    BLS      : {'✓' if os.getenv('BLS_API_KEY') else '✗'}")
    print(f"    O*NET    : {'✓' if os.getenv('ONET_USERNAME') else '✗'}")
    print(f"    YouTube  : {'✓' if os.getenv('YOUTUBE_API_KEY') else '✗'}")
    print(f"    Reed     : {'✓' if os.getenv('REED_API_KEY') else '✗'}")
    print(f"    GitHub   : ✓ (no key needed)")
    print(f"    Coursera : ✓ (no key needed)")
    print(f"    RemoteOK : ✓ (no key needed)")
    print(f"\n  Rate limiting : {'ON (slowapi)' if HAS_RATELIMIT else 'OFF'}")
    print(f"  Auth          : {'✓ JWT' if HAS_JWT else '✗'}")
    print(f"  Stop → Ctrl+C\n")
    threading.Thread(target=_open,daemon=True).start()
    uvicorn.run("app:app",host=HOST,port=PORT,reload=DEBUG,log_level="info")
