from src.fundamentals.fetchers.economic_calendar import fetch_and_store_calendar_events
from src.fundamentals.fetchers.news_fetcher import run_news_check


def register_fundamentals_jobs(scheduler) -> None:
    """
    Register all fundamentals background jobs onto the existing APScheduler instance.
    Call this from src/api/main.py in the same block where other jobs are registered.
    """
    from src.fundamentals.llm.processor import run_fundamentals_intelligence

    # Economic calendar refresh — daily at 06:00 UTC
    scheduler.add_job(
        fetch_and_store_calendar_events,
        trigger="cron",
        hour=6,
        minute=0,
        timezone="UTC",
        id="fundamentals_calendar_daily",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # Economic calendar refresh — Sunday at 02:00 UTC for ahead-of-week prep
    scheduler.add_job(
        fetch_and_store_calendar_events,
        trigger="cron",
        day_of_week="sun",
        hour=2,
        minute=0,
        timezone="UTC",
        id="fundamentals_calendar_weekly",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # Event-anchored news check — every hour
    scheduler.add_job(
        run_news_check,
        trigger="interval",
        hours=1,
        id="fundamentals_news_check_hourly",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # LLM news intelligence — daily at 07:00 UTC
    # Runs after calendar refresh (06:00) and the hourly news check.
    scheduler.add_job(
        run_fundamentals_intelligence,
        trigger="cron",
        hour=7,
        minute=0,
        timezone="UTC",
        id="fundamentals_llm_intelligence_daily",
        replace_existing=True,
        misfire_grace_time=600,
    )
