"""
scheduler/jobs.py — APScheduler Background Jobs

Scheduled tasks that run while the server is live:
  1. Retrain XGBoost risk model — every Sunday 02:00
  2. Retrain Prophet forecasters — every Sunday 03:00
  3. Refresh API cache — every hour
  4. Clean stale cache entries — every day at midnight
"""

import logging
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Job 1: Retrain XGBoost ────────────────────────────────────────────────────
def retrain_risk_model():
    """Retrain XGBoost on latest occupational data. Runs every Sunday at 02:00."""
    logger.info("[scheduler] Starting XGBoost risk model retraining...")
    try:
        from ml.risk_model import train_model, reload_model
        result = train_model(track_with_mlflow=True)
        reload_model()
        m = result["metrics"]
        logger.info(
            f"[scheduler] Risk model retrained. "
            f"CV accuracy: {m['cv_accuracy_mean']:.3f} ± {m['cv_accuracy_std']:.3f}"
        )
    except Exception as e:
        logger.error(f"[scheduler] Risk model retraining failed: {e}")


# ── Job 2: Retrain Prophet forecasters ───────────────────────────────────────
def retrain_forecasters(db_path: Path):
    """
    For each role with ≥14 data points in job_trends, train/update Prophet model.
    Runs every Sunday at 03:00.
    """
    logger.info("[scheduler] Starting Prophet forecaster retraining...")
    try:
        conn  = sqlite3.connect(db_path)
        roles = conn.execute(
            "SELECT role, COUNT(*) as cnt FROM job_trends GROUP BY role HAVING cnt >= 14"
        ).fetchall()
        conn.close()

        if not roles:
            logger.info("[scheduler] Not enough trend data yet for any role (need ≥14 points)")
            return

        from ml.forecaster import train_prophet
        for role, count in roles:
            try:
                conn  = sqlite3.connect(db_path)
                rows  = conn.execute(
                    "SELECT date, posting_count FROM job_trends WHERE role=? ORDER BY date DESC LIMIT 365",
                    (role,)
                ).fetchall()
                conn.close()
                history = [{"date": r[0], "posting_count": r[1]} for r in rows]
                train_prophet(role, history)
                logger.info(f"[scheduler] Prophet retrained for '{role}' ({count} points)")
            except Exception as e:
                logger.warning(f"[scheduler] Prophet retraining failed for '{role}': {e}")

    except Exception as e:
        logger.error(f"[scheduler] Forecaster retraining failed: {e}")


# ── Job 3: Hourly cache warm-up ───────────────────────────────────────────────
def warm_api_cache(db_path: Path, roles: list):
    """
    Pre-fetch live Adzuna data for top roles and store in cache.
    Runs every hour to keep cache warm before users request it.
    """
    logger.info("[scheduler] Warming API cache for top roles...")
    try:
        import asyncio
        # Import the fetchers from main app (imported at job creation time)
        try:
            from app import adzuna, remoteok, onet_auto
        except ImportError:
            logger.warning("[scheduler] Could not import app fetchers — skipping cache warm")
            return

        async def warm():
            import asyncio
            for role in roles[:4]:   # top 4 roles only to stay within rate limits
                try:
                    await adzuna(role)
                    await remoteok(role)
                    await asyncio.sleep(0.5)
                except Exception as e:
                    logger.warning(f"[scheduler] Cache warm failed for '{role}': {e}")

        asyncio.run(warm())
        logger.info("[scheduler] Cache warm-up complete")
    except Exception as e:
        logger.error(f"[scheduler] Cache warm-up error: {e}")


# ── Job 4: Clean stale cache ──────────────────────────────────────────────────
def clean_stale_cache(db_path: Path, max_age_days: int = 7):
    """
    Delete api_cache entries older than max_age_days.
    Runs every day at midnight to keep the DB lean.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).isoformat()
    try:
        conn = sqlite3.connect(db_path)
        cur  = conn.execute("DELETE FROM api_cache WHERE fetched_at < ?", (cutoff,))
        deleted = cur.rowcount
        conn.commit()
        conn.close()
        if deleted > 0:
            logger.info(f"[scheduler] Cleaned {deleted} stale cache entries (>{max_age_days}d old)")
    except Exception as e:
        logger.error(f"[scheduler] Cache cleanup failed: {e}")


# ── Scheduler setup ────────────────────────────────────────────────────────────
def create_scheduler(db_path: Path, top_roles: list):
    """
    Create and configure the APScheduler instance.
    Call scheduler.start() in the FastAPI startup event.
    Call scheduler.shutdown() in the FastAPI shutdown event.
    """
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron     import CronTrigger
    from apscheduler.triggers.interval import IntervalTrigger

    scheduler = AsyncIOScheduler(timezone="UTC")

    # Retrain risk model — every Sunday at 02:00 UTC
    scheduler.add_job(
        retrain_risk_model,
        CronTrigger(day_of_week="sun", hour=2, minute=0),
        id          = "retrain_risk",
        name        = "Retrain XGBoost risk model",
        replace_existing = True,
        misfire_grace_time = 3600,
    )

    # Retrain Prophet forecasters — every Sunday at 03:00 UTC
    scheduler.add_job(
        retrain_forecasters,
        CronTrigger(day_of_week="sun", hour=3, minute=0),
        args        = [db_path],
        id          = "retrain_forecast",
        name        = "Retrain Prophet forecasters",
        replace_existing = True,
        misfire_grace_time = 3600,
    )

    # Warm API cache — every hour
    scheduler.add_job(
        warm_api_cache,
        IntervalTrigger(hours=1),
        args        = [db_path, top_roles],
        id          = "warm_cache",
        name        = "Warm API cache",
        replace_existing = True,
    )

    # Clean stale cache — every day at midnight
    scheduler.add_job(
        clean_stale_cache,
        CronTrigger(hour=0, minute=0),
        args        = [db_path],
        id          = "clean_cache",
        name        = "Clean stale cache entries",
        replace_existing = True,
    )

    return scheduler
