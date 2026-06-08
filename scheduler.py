"""
Scheduler — runs background jobs automatically
Uses APScheduler (free, no external broker needed)
"""
import asyncio
import logging
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)
scheduler = BackgroundScheduler()

ROLES_TO_TRACK = [
    "data analyst", "data engineer", "ml engineer",
    "software engineer", "devops engineer", "product manager",
    "qa tester", "data entry specialist",
]

# ── Job functions ─────────────────────────────────────────────────────────────

def job_fetch_live_postings():
    """Fetch fresh job postings from all free APIs every 6 hours."""
    from data.live_feeds import get_all_live_data
    from models.db_session import SessionLocal
    from models.database import JobTrend

    logger.info(f"[Scheduler] Fetching live job postings at {datetime.utcnow()}")
    db = SessionLocal()
    try:
        for role in ROLES_TO_TRACK:
            data = asyncio.run(get_all_live_data(role))
            adzuna = data.get("adzuna", {})
            if adzuna.get("total_postings"):
                trend = JobTrend(
                    role          = role,
                    date          = datetime.utcnow(),
                    posting_count = adzuna["total_postings"],
                    median_salary = adzuna.get("avg_salary", 0),
                    source        = "adzuna+remoteok",
                )
                db.add(trend)
        db.commit()
        logger.info(f"[Scheduler] Saved postings for {len(ROLES_TO_TRACK)} roles.")
    except Exception as e:
        logger.error(f"[Scheduler] Error fetching postings: {e}")
        db.rollback()
    finally:
        db.close()


def job_retrain_prophet():
    """Retrain Prophet model every Sunday at 2am on latest DB data."""
    logger.info(f"[Scheduler] Retraining Prophet at {datetime.utcnow()}")
    try:
        from ml.trend_forecaster import retrain_from_db
        retrain_from_db()
        logger.info("[Scheduler] Prophet retrain complete.")
    except Exception as e:
        logger.error(f"[Scheduler] Prophet retrain failed: {e}")


def job_retrain_xgboost():
    """Retrain XGBoost risk model on the 1st of every month."""
    logger.info(f"[Scheduler] Retraining XGBoost at {datetime.utcnow()}")
    try:
        from ml.risk_model import retrain_from_db
        retrain_from_db()
        logger.info("[Scheduler] XGBoost retrain complete.")
    except Exception as e:
        logger.error(f"[Scheduler] XGBoost retrain failed: {e}")


def job_refresh_courses():
    """Refresh Coursera course catalogue every Monday."""
    logger.info(f"[Scheduler] Refreshing Coursera catalogue at {datetime.utcnow()}")
    try:
        from data.live_feeds import fetch_coursera_courses
        from models.db_session import SessionLocal
        from models.database import Course

        db = SessionLocal()
        skills_to_fetch = ["python", "machine learning", "aws", "spark", "mlops", "docker"]
        for skill in skills_to_fetch:
            data = asyncio.run(fetch_coursera_courses(skill, limit=10))
            for c in data.get("courses", []):
                existing = db.query(Course).filter(Course.url == c["url"]).first()
                if not existing:
                    db.add(Course(
                        title      = c["name"],
                        platform   = "Coursera",
                        url        = c["url"],
                        skill_tags = [skill],
                        source     = "coursera_api",
                    ))
        db.commit()
        db.close()
        logger.info("[Scheduler] Course catalogue refreshed.")
    except Exception as e:
        logger.error(f"[Scheduler] Course refresh failed: {e}")


# ── Register jobs ─────────────────────────────────────────────────────────────

def start_scheduler():
    """Call this once on app startup."""
    if scheduler.running:
        return

    # Every 6 hours — fetch live job postings
    scheduler.add_job(
        job_fetch_live_postings,
        trigger=CronTrigger(hour="*/6"),
        id="fetch_postings",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # Every Sunday at 2am — retrain Prophet
    scheduler.add_job(
        job_retrain_prophet,
        trigger=CronTrigger(day_of_week="sun", hour=2),
        id="retrain_prophet",
        replace_existing=True,
    )

    # 1st of every month at 3am — retrain XGBoost
    scheduler.add_job(
        job_retrain_xgboost,
        trigger=CronTrigger(day=1, hour=3),
        id="retrain_xgboost",
        replace_existing=True,
    )

    # Every Monday at 4am — refresh course catalogue
    scheduler.add_job(
        job_refresh_courses,
        trigger=CronTrigger(day_of_week="mon", hour=4),
        id="refresh_courses",
        replace_existing=True,
    )

    scheduler.start()
    logger.info("[Scheduler] All jobs registered and running.")


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown()
