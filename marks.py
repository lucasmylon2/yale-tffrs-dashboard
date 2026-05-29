"""Parse and normalize TFRRS marks into comparable numeric values."""
import re

# Wind-affected events where the +2.0 m/s legality limit applies (outdoor
# sprints up to 200m, sprint hurdles, and horizontal jumps).
WIND_LEGAL_LIMIT = 2.0
WIND_EVENTS = {"100", "200", "100H", "110H", "100MH", "110MH", "LJ", "TJ"}


def is_wind_aided(event, wind):
    """True only for a wind-affected event with a reading over the limit."""
    if wind is None:
        return False
    try:
        if wind != wind:  # NaN
            return False
    except TypeError:
        return False
    e = str(event).strip().upper()
    return e in WIND_EVENTS and wind > WIND_LEGAL_LIMIT


def meet_level(meet_name):
    """Classify a meet into a championship tier, or '' for a regular meet."""
    n = str(meet_name).lower()
    if "ncaa" in n:
        return "NCAA"
    if "heptagonal" in n or "ivy league" in n or "ivy heps" in n:
        return "Ivy Heps"
    if "ecac" in n or "ic4a" in n:
        return "ECAC/IC4A"
    if "regional" in n or "east region" in n or "preliminary round" in n:
        return "Regional"
    if "championship" in n or "conference" in n:
        return "Championship"
    return ""

# Field events: higher is better, value in meters. Matched against event labels.
FIELD_EVENTS = {
    "LJ", "TJ", "HJ", "PV", "SP", "DT", "HT", "JT", "WT", "SW",
}
# Multi-event scores: higher is better, value in points.
MULTI_EVENTS = {"HEP", "DEC", "PENT", "HEPT"}

# Distance/throw labels that sometimes appear spelled out.
_FIELD_KEYWORDS = (
    "long jump", "triple jump", "high jump", "pole vault", "shot put",
    "discus", "hammer", "javelin", "weight throw",
)


def event_kind(event: str):
    """Return ('time'|'distance'|'points', higher_is_better: bool)."""
    e = event.strip().upper()
    if any(k in event.lower() for k in _FIELD_KEYWORDS) or e in FIELD_EVENTS:
        return "distance", True
    if e in MULTI_EVENTS or "HEP" in e or "DEC" in e or "PENT" in e:
        return "points", True
    # Field-mark marks contain an explicit 'm'/feet notation, caught in parse.
    return "time", False


def _time_to_seconds(token: str):
    """'3:09.34' -> 189.34 ; '1:04.24' -> 64.24 ; '10.56' -> 10.56."""
    token = token.strip()
    if ":" in token:
        parts = token.split(":")
        try:
            if len(parts) == 2:
                m, s = parts
                return int(m) * 60 + float(s)
            if len(parts) == 3:
                h, m, s = parts
                return int(h) * 3600 + int(m) * 60 + float(s)
        except ValueError:
            return None
    try:
        return float(token)
    except ValueError:
        return None


def parse_mark(raw: str, event: str):
    """Return dict with normalized value, wind, and unit.

    value is a float where smaller=better for times and larger=better for
    distances/points. Returns value=None if unparseable.
    """
    if raw is None:
        return {"value": None, "wind": None, "unit": None, "raw": raw}
    text = raw.strip()
    if not text or text.upper() in {"DNF", "DNS", "DQ", "NM", "FS", "NH", "SCR"}:
        return {"value": None, "wind": None, "unit": None, "raw": text}

    # Extract wind, e.g. "10.56 (6.6)" or "21.87 (0.4)" or "(-1.2)"
    wind = None
    wm = re.search(r"\(([-+]?\d+\.?\d*)\)", text)
    if wm:
        try:
            wind = float(wm.group(1))
        except ValueError:
            wind = None
    core = re.sub(r"\([^)]*\)", "", text).strip()

    kind, higher = event_kind(event)

    # Field mark like "6.01m 19' 8.75\"" -> take leading metric value.
    mm = re.search(r"(\d+\.?\d*)\s*m\b", core)
    if mm:
        try:
            return {"value": float(mm.group(1)), "wind": wind, "unit": "m", "raw": text}
        except ValueError:
            pass

    if kind == "points":
        num = re.search(r"\d+", core)
        if num:
            return {"value": float(num.group(0)), "wind": wind, "unit": "pts", "raw": text}
        return {"value": None, "wind": wind, "unit": "pts", "raw": text}

    # Time: grab the first time-like token (mm:ss.xx or ss.xx)
    tm = re.search(r"\d+:\d+(?:\.\d+)?|\d+\.\d+", core)
    if tm:
        secs = _time_to_seconds(tm.group(0))
        if secs is not None:
            return {"value": secs, "wind": wind, "unit": "s", "raw": text}
    return {"value": None, "wind": wind, "unit": None, "raw": text}
