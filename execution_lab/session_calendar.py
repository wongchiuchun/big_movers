"""NYSE regular-session schedules, including holidays and early closes.

Named session_calendar to avoid shadowing Python's standard calendar module
when the worker starts with this directory on its import path.
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import exchange_calendars as xcals
import pandas as pd


def schedule(date=None):
    today = datetime.now(ZoneInfo("America/New_York")).date()
    anchor = pd.Timestamp(date or today.isoformat())
    if anchor.tzinfo is not None or anchor != anchor.normalize():
        raise ValueError("Use a session date in YYYY-MM-DD format.")
    cal = xcals.get_calendar("XNYS", start=anchor - timedelta(days=370), end=anchor + timedelta(days=30))
    if date and not cal.is_session(anchor):
        raise ValueError("That date is not a US regular trading session.")
    session = cal.date_to_session(anchor, direction="previous")
    opening, closing = cal.session_open(session), cal.session_close(session)
    return {"date": session.strftime("%Y-%m-%d"), "open_ns": int(opening.value),
            "close_ns": int(closing.value),
            "open_label": opening.tz_convert("America/New_York").strftime("%H:%M"),
            "close_label": closing.tz_convert("America/New_York").strftime("%H:%M")}
