"""Time zone helpers for the opt-in ``tz_aware_v1`` bridge feature.

Odoo stores datetimes as naive UTC. These helpers convert between that storage
and a local IANA time zone. They are plain functions (no model) shared by the
service and the ORM layer, and work on every supported Odoo series:

  * Odoo 15-19 always ship ``pytz``; it is preferred when present.
  * Odoo 20 no longer depends on ``pytz``; ``zoneinfo`` (Python 3.9+) is used.
"""
import datetime
import re

try:
    import pytz
except ImportError:  # Odoo 20 dropped the pytz dependency.
    pytz = None

try:
    from zoneinfo import ZoneInfo
except ImportError:  # Python < 3.9 (Odoo 15 / 16 servers).
    ZoneInfo = None

SERVER_DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"

DATE_ONLY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DATETIME_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2}(\.\d{3}(\d{3})?)?)?(Z|[+-]\d{2}:\d{2})?$"
)


def get_tzinfo(name):
    """Return a tzinfo for an IANA name, or None if the name is not valid."""
    if not isinstance(name, str) or not name or len(name) > 64:
        return None
    if pytz is not None:
        try:
            return pytz.timezone(name)
        except Exception:
            return None
    if ZoneInfo is not None:
        try:
            return ZoneInfo(name)
        except Exception:
            return None
    return None


def is_valid_tz(name):
    return get_tzinfo(name) is not None


def localize(naive, tzinfo):
    # pytz zones must be attached with localize(); zoneinfo zones with replace().
    if hasattr(tzinfo, "localize"):
        return tzinfo.localize(naive)
    return naive.replace(tzinfo=tzinfo)


def local_to_utc(naive, tz_name):
    """Naive local wall time in ``tz_name`` -> naive UTC datetime."""
    aware = localize(naive, get_tzinfo(tz_name))
    return aware.astimezone(datetime.timezone.utc).replace(tzinfo=None)


def utc_to_local(naive_utc, tz_name):
    """Naive UTC datetime -> aware datetime in ``tz_name``."""
    aware = naive_utc.replace(tzinfo=datetime.timezone.utc)
    return aware.astimezone(get_tzinfo(tz_name))


def parse_datetime_value(value):
    """Parse a domain value written as a date or a datetime.

    Returns ``(naive_or_aware_datetime, is_date_only)`` or ``None`` when the
    string is not a date/datetime literal (so it is left to Odoo untouched).
    Raises ValueError for strings that look like dates but are not valid ones.
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    if DATE_ONLY_RE.match(text):
        return datetime.datetime.strptime(text, "%Y-%m-%d"), True
    if DATETIME_RE.match(text):
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.datetime.fromisoformat(text.replace(" ", "T", 1)), False
    return None


def format_utc(naive_utc):
    return naive_utc.strftime(SERVER_DATETIME_FORMAT)


def parse_server_datetime(value):
    """Datetime value as returned by the ORM (datetime or server string)."""
    if isinstance(value, datetime.datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.datetime.strptime(value[:19], SERVER_DATETIME_FORMAT)
        except ValueError:
            return None
    return None
