from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

CHICAGO = ZoneInfo("America/Chicago")

def add_months(year: int, month: int, delta: int) -> tuple[int, int]:
    m = month + delta
    y = year
    while m > 12:
        m -= 12
        y += 1
    while m < 1:
        m += 12
        y -= 1
    return y, m

def first_moment_of_month(year: int, month: int, hour: int) -> datetime:
    return datetime(year, month, 1, hour, 0, 0, tzinfo=CHICAGO)

def compute_opens_at(target_year: int, target_month: int, opens_hour_chicago: int) -> datetime:
    first_m = first_moment_of_month(target_year, target_month, opens_hour_chicago)
    return first_m - timedelta(days=14)

def compute_closes_at(target_year: int, target_month: int) -> datetime:
    first_m = datetime(target_year, target_month, 1, 0, 0, 0, tzinfo=CHICAGO)
    return first_m - timedelta(hours=24)

def find_target_month_in_open_window(now_chi: datetime, opens_hour: int) -> tuple[int, int] | None:
    ty, tm = add_months(now_chi.year, now_chi.month, 1)
    for i in range(0, 14):
        y, m = add_months(ty, tm, i)
        opens = compute_opens_at(y, m, opens_hour)
        closes = compute_closes_at(y, m)
        if opens <= now_chi < closes:
            return y, m
    return None

def chicago_to_utc_iso(dt_chi: datetime) -> str:
    return dt_chi.astimezone(timezone.utc).isoformat()

def parse_utc_iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace('Z', '+00:00'))