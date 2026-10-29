import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.config import settings
from app.services.briefing_service import briefing_service
from app.services.decision_engine import decision_engine

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()

async def scheduled_morning_briefing():
    logger.info("Triggering scheduled morning briefing...")
    try:
        res = briefing_service.generate_briefing(summary_type="morning")
        logger.info(f"Morning briefing generated successfully (ID: {res['id']})")
        from app.services.notification_service import notification_service
        notification_service.notify_briefing_ready("morning", res.get("content_markdown", ""))
    except Exception as e:
        logger.error(f"Scheduled morning briefing failed: {e}")

async def scheduled_evening_briefing():
    logger.info("Triggering scheduled evening briefing...")
    try:
        res = briefing_service.generate_briefing(summary_type="evening")
        logger.info(f"Evening briefing generated successfully (ID: {res['id']})")
        from app.services.notification_service import notification_service
        notification_service.notify_briefing_ready("evening", res.get("content_markdown", ""))
    except Exception as e:
        logger.error(f"Scheduled evening briefing failed: {e}")

async def scheduled_prompt_sweep():
    logger.info("Running proactive graph prompt & anomaly sweep...")
    try:
        prompts = decision_engine.run_proactive_prompt_sweep()
        if prompts:
            logger.info(f"Generated {len(prompts)} new proactive prompts.")
            from app.services.notification_service import notification_service
            for p in prompts[:2]:
                notification_service.notify_urgent_obligation(p.get("title", "Urgent Nudge"))
    except Exception as e:
        logger.error(f"Proactive prompt sweep failed: {e}")

def start_scheduler():
    try:
        # Parse morning briefing time (e.g. "08:00")
        m_parts = settings.morning_briefing_time.split(":")
        m_hour, m_minute = int(m_parts[0]), int(m_parts[1])

        # Parse evening briefing time (e.g. "19:30")
        e_parts = settings.evening_briefing_time.split(":")
        e_hour, e_minute = int(e_parts[0]), int(e_parts[1])

        # Add Morning Briefing Job
        scheduler.add_job(
            scheduled_morning_briefing,
            CronTrigger(hour=m_hour, minute=m_minute),
            id="morning_briefing",
            replace_existing=True,
            name="Daily Morning Briefing"
        )

        # Add Evening Briefing Job
        scheduler.add_job(
            scheduled_evening_briefing,
            CronTrigger(hour=e_hour, minute=e_minute),
            id="evening_briefing",
            replace_existing=True,
            name="Daily Evening Briefing"
        )

        # Add Proactive Anomaly Sweep (every 30 minutes)
        scheduler.add_job(
            scheduled_prompt_sweep,
            IntervalTrigger(minutes=30),
            id="prompt_sweep",
            replace_existing=True,
            name="Graph Anomaly & Nudge Sweep"
        )

        scheduler.start()
        logger.info("Obrigado scheduler started successfully.")
    except Exception as e:
        logger.error(f"Failed to start scheduler: {e}")

def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Obrigado scheduler stopped.")
