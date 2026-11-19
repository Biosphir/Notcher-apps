"""LRCLIB access, conservative matching, LRC parsing, and a local lyrics cache."""
import hashlib
import json
import re
import sqlite3
import time
import unicodedata
from contextlib import closing
from difflib import SequenceMatcher
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

USER_AGENT = "Notcher Live Lyrics/1.0.0 (https://biosphir.com/notcher)"
TIMESTAMP = re.compile(r"\[(\d{1,3}):([0-5]\d)(?:[.:](\d{1,3}))?\]")


class ProviderError(Exception):
    def __init__(self, message, retry_after=0):
        super().__init__(message)
        self.retry_after = retry_after


class Cancelled(Exception):
    pass


def parse_lrc(text):
    if not isinstance(text, str):
        return []
    lines = []
    for line in (text or "").splitlines():
        stamps = list(TIMESTAMP.finditer(line))
        if not stamps:
            continue
        value = TIMESTAMP.sub("", line).strip()
        value = re.sub(r"<\d{1,3}:[0-5]\d(?:\.\d{1,3})?>", "", value)
        for stamp in stamps:
            fraction = stamp[3] or ""
            seconds = int(stamp[1]) * 60 + int(stamp[2])
            if fraction:
                seconds += int(fraction) / (10 ** len(fraction))
            lines.append((seconds, value))
    return sorted(lines, key=lambda item: item[0])


def normalize(text):
    value = unicodedata.normalize("NFKD", str(text or "").casefold())
    return "".join(char for char in value if char.isalnum())


def clean_title(title):
    value = re.sub(r"[\[(](?:official\s+)?(?:music\s+)?(?:video|audio|lyrics?|visualizer)[\])]", "", title, flags=re.I)
    return value.strip()


def track_key(track):
    signature = [
        str(track.get(name) or "").strip().casefold() for name in ("title", "artist", "album")
    ]
    signature.append(round(float(track.get("duration") or 0)))
    return hashlib.sha256(json.dumps(signature, ensure_ascii=False).encode()).hexdigest()


def usable_record(record):
    return isinstance(record, dict) and (
        record.get("instrumental") is True
        or isinstance(record.get("syncedLyrics"), str) and bool(record["syncedLyrics"].strip())
        or isinstance(record.get("plainLyrics"), str) and bool(record["plainLyrics"].strip())
    )


def match_score(track, record):
    title = SequenceMatcher(None, normalize(clean_title(track["title"])), normalize(record.get("trackName"))).ratio()
    artist = SequenceMatcher(None, normalize(track.get("artist")), normalize(record.get("artistName"))).ratio()
    duration = float(track.get("duration") or 0)
    difference = abs(duration - float(record.get("duration") or 0))
    timing = max(0, 1 - difference / 30) if duration > 0 else 0
    return title * 0.45 + artist * 0.35 + timing * 0.2


def confident_match(track, record):
    duration = float(track.get("duration") or 0)
    if not track.get("artist") or duration <= 0:
        return False
    return (
        SequenceMatcher(None, normalize(clean_title(track["title"])), normalize(record.get("trackName"))).ratio() >= 0.9
        and SequenceMatcher(None, normalize(track["artist"]), normalize(record.get("artistName"))).ratio() >= 0.9
        and abs(duration - float(record.get("duration") or 0)) <= 2
    )


def request_json(endpoint, params, cancelled):
    if cancelled():
        raise Cancelled()
    request = Request("https://lrclib.net/api/" + endpoint + "?" + urlencode(params), headers={
        "User-Agent": USER_AGENT, "Accept": "application/json",
    })
    try:
        with urlopen(request, timeout=8) as response:
            raw = response.read(4 * 1024 * 1024 + 1)
    except HTTPError as error:
        if error.code == 404:
            return None
        if error.code == 429:
            value = error.headers.get("Retry-After", "60")
            if value.isdigit():
                seconds = int(value)
            else:
                try:
                    seconds = round(parsedate_to_datetime(value).timestamp() - time.time())
                except (ValueError, TypeError, OverflowError):
                    seconds = 60
            raise ProviderError("LRCLIB is busy. Please try again later.", max(1, seconds)) from None
        raise ProviderError("The lyrics service is unavailable. Try again later.") from None
    except (URLError, OSError, TimeoutError):
        raise ProviderError("Could not reach LRCLIB. Check your connection and retry.") from None
    if cancelled():
        raise Cancelled()
    if len(raw) > 4 * 1024 * 1024:
        raise ProviderError("The lyrics response is too large.")
    try:
        return json.loads(raw)
    except (ValueError, UnicodeError):
        raise ProviderError("The lyrics service returned an unreadable response.") from None


def select_record(track, records):
    records = [record for record in records if usable_record(record)]
    if not records:
        return None
    best_score = max(match_score(track, record) for record in records)
    # LRCLIB has no revision timestamp. Prefer the newer record ID among
    # equally close song matches, without selecting an unrelated newer song.
    closest = [record for record in records if match_score(track, record) >= best_score - 0.02]
    return max(closest, key=lambda record: int(record.get("id") or 0))


def lookup(track, cancelled=lambda: False):
    params = {"track_name": track["title"], "artist_name": track.get("artist", "")}
    if track.get("album"):
        params["album_name"] = track["album"]
    duration = float(track.get("duration") or 0)
    if 1 <= duration <= 3600:
        params["duration"] = round(duration)
    direct = request_json("get", params, cancelled) if track.get("artist") else None
    if usable_record(direct) and confident_match(track, direct):
        return {"kind": "lyrics", "record": direct}
    title = clean_title(track["title"])
    if " - " in title:
        title = title.split(" - ", 1)[1].strip() or title
    results = request_json("search", {"track_name": title}, cancelled)
    candidates = [record for record in (results or []) if usable_record(record)] if isinstance(results, list) else []
    if usable_record(direct) and not any(item.get("id") == direct.get("id") for item in candidates):
        candidates.append(direct)
    selected = select_record(track, candidates)
    if selected:
        return {"kind": "lyrics", "record": selected}
    return {"kind": "missing"}


class LyricsCache:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS lyrics (key TEXT PRIMARY KEY, payload TEXT, saved REAL)")

    def get(self, key):
        try:
            with closing(sqlite3.connect(self.path)) as db:
                row = db.execute("SELECT payload, saved FROM lyrics WHERE key = ?", (key,)).fetchone()
            if row is None:
                return None
            payload = json.loads(row[0])
            if not isinstance(payload, dict) or payload.get("kind") not in ("lyrics", "missing", "candidates"):
                return None
            if payload.get("kind") == "lyrics" and not usable_record(payload.get("record")):
                return None
            if payload.get("kind") != "lyrics" and time.time() - row[1] > 600:
                return None
            return payload
        except (OSError, sqlite3.Error, ValueError):
            return None

    def put(self, key, payload):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("INSERT INTO lyrics VALUES (?, ?, ?) ON CONFLICT(key) DO UPDATE SET payload=excluded.payload, saved=excluded.saved",
                       (key, json.dumps(payload), time.time()))
            db.execute("DELETE FROM lyrics WHERE key NOT IN (SELECT key FROM lyrics ORDER BY saved DESC LIMIT 500)")
