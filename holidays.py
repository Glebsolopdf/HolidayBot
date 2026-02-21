from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable, Sequence

from aiohttp import ClientError, ClientSession, ClientTimeout

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

CALEND_RU_URL = "https://www.calend.ru/day/"
MOSCOW_TZ = ZoneInfo("Europe/Moscow") if ZoneInfo else None

@dataclass(slots=True)
class HolidayResult:
    date: date
    holidays: tuple[str, ...]
    source_url: str
    fetched_at: datetime
    error: str | None = None

    @property
    def has_data(self) -> bool:
        return bool(self.holidays)


class _HolidayAnchorParser(HTMLParser):
    __slots__ = ("_target_div_id", "_inside_target", "_target_depth", "_capture", "_buffer", "_holidays")

    def __init__(self, target_div_id: str) -> None:
        super().__init__(convert_charrefs=True)
        self._target_div_id = target_div_id
        self._inside_target = False
        self._target_depth = 0
        self._capture = False
        self._buffer: list[str] = []
        self._holidays: list[str] = []
        logger.debug("Initialized parser for div_id: %s", target_div_id)

    def feed(self, data: str) -> Sequence[str]:  # type: ignore[override]
        super().feed(data)
        result = tuple(self._holidays)
        if not result:
            logger.warning("Parser found no holidays for div_id=%s (inside_target=%s, target_depth=%d)", 
                          self._target_div_id, self._inside_target, self._target_depth)
            if not self._inside_target:
                logger.warning("Parser never entered target div with id=%s - div might not exist in HTML", 
                             self._target_div_id)
        else:
            logger.info("Parser found %d holidays for div_id=%s", len(result), self._target_div_id)
        return result

    def handle_starttag(self, tag: str, attrs: Iterable[tuple[str, str | None]]) -> None:
        if tag == "div":
            attr_map = dict(attrs)
            div_id = attr_map.get("id")
            if self._inside_target:
                self._target_depth += 1
            elif div_id == self._target_div_id:
                self._inside_target = True
                self._target_depth = 1
                logger.debug("Found target div with id=%s", self._target_div_id)
            return

        if not self._inside_target:
            return

        if tag == "a":
            href = dict(attrs).get("href") or ""
            if "/holidays/0/0/" in href:
                self._capture = True
                self._buffer.clear()
                logger.debug("Found holiday link: %s", href)

    def handle_endtag(self, tag: str) -> None:
        if self._inside_target and tag == "div":
            self._target_depth -= 1
            if self._target_depth <= 0:
                self._inside_target = False
                self._target_depth = 0
        elif tag == "a" and self._capture:
            text = "".join(self._buffer).strip()
            if text:
                self._holidays.append(text)
                logger.debug("Parsed holiday: %s", text)
            self._capture = False
            self._buffer.clear()

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._buffer.append(data)


_cached_result: HolidayResult | None = None
_cache_file: Path | None = None
_cache_payload: dict[str, Any] | None = None
_refresh_lock = asyncio.Lock()
_autopost_event: asyncio.Event | None = None


def initialize_holiday_cache(cache_path: Path, default_autopost_time: str) -> None:
    """Bind the persistent cache file and load existing data."""

    global _cache_file, _cache_payload
    _cache_file = cache_path
    _cache_payload = _load_or_init_payload(cache_path, default_autopost_time)
    entry = (_cache_payload or {}).get("today", {})
    result = _payload_entry_to_result(entry)
    if result:
        _cache_store(result)


def register_autopost_event(event: asyncio.Event) -> None:
    global _autopost_event
    _autopost_event = event


def get_autopost_time() -> str:
    payload = _ensure_payload()
    return str(payload.get("autopost_time", "00:00"))


def update_autopost_time(value: str) -> str:
    normalized = _normalize_time(value)
    payload = _ensure_payload()
    if payload.get("autopost_time") == normalized:
        return normalized
    payload["autopost_time"] = normalized
    _write_payload(payload)
    _notify_autopost_update()
    return normalized


async def ensure_holidays_for_date(target_date: date, *, session: ClientSession | None = None) -> HolidayResult | None:
    """Ensure holidays are available for a specific date.
    
    First checks cache, then tries to refresh cache.
    If the date is not today or tomorrow, fetches it directly.
    """
    logger.info("ensure_holidays_for_date called for date: %s", target_date)
    cached = get_cached_holiday_result(target_date)
    if cached:
        logger.info("Found cached holidays for %s: %d holidays", target_date, len(cached.holidays))
        return cached
    
    logger.debug("No cached holidays found for %s, checking if date is in cache range", target_date)
    # Check if target_date is today or tomorrow (within cache range)
    now = _normalize_now(None)
    current_date = now.date()
    tomorrow_date = current_date + timedelta(days=1)
    
    # If target_date is today or tomorrow, refresh cache normally
    if target_date == current_date or target_date == tomorrow_date:
        logger.info("Date %s is today or tomorrow, refreshing cache", target_date)
        await refresh_holiday_cache(session=session)
        result = get_cached_holiday_result(target_date)
        if result:
            logger.info("After cache refresh, found %d holidays for %s", len(result.holidays), target_date)
        else:
            logger.warning("After cache refresh, still no holidays found for %s", target_date)
        return result
    
    # For other dates, fetch directly
    logger.info("Fetching holidays directly for date %s (not in cache range)", target_date)
    try:
        html = await _download_html(target_date=target_date, session=session)
        logger.debug("HTML downloaded, length: %d bytes", len(html))
        holidays = tuple(_parse_holidays(html, target_date))
        logger.info("Fetched %d holidays for date %s", len(holidays), target_date)
        fetched_at = _normalize_now(None)
        
        error_msg = None
        if not holidays:
            now_date = _normalize_now(None).date()
            if target_date == now_date:
                error_msg = "Не найдено праздников на сегодня."
            else:
                error_msg = f"Не найдено праздников на {target_date.strftime('%d.%m.%Y')}."
            logger.warning("No holidays found for %s", target_date)
        
        result = HolidayResult(
            date=target_date,
            holidays=holidays,
            source_url=f"{CALEND_RU_URL}{target_date:%Y-%m-%d}/",
            fetched_at=fetched_at,
            error=error_msg,
        )
        return result
    except Exception as exc:
        logger.error("Failed to fetch holidays for %s: %s", target_date, exc, exc_info=True)
        return None


def get_cached_holiday_result(target_date: date) -> HolidayResult | None:
    """Get cached holidays for a specific date.
    
    Checks both "today" and "tomorrow" entries in cache.
    This allows autopost at 00:00 to work correctly:
    - Cache is updated at 23:50 MSK, fetching tomorrow's holidays and saving them as "today"
    - At 00:00 MSK, when autopost runs for the new day, it finds holidays in "today" entry
    - The function searches both "today" and "tomorrow" entries to find the matching date
    """
    payload = _ensure_payload()
    logger.debug("Checking cache for date %s", target_date)
    for key in ("today", "tomorrow"):
        entry = payload.get(key) or {}
        raw_date = entry.get("date")
        if not raw_date:
            logger.debug("Cache entry '%s' has no date", key)
            continue
        try:
            entry_date = date.fromisoformat(raw_date)
            logger.debug("Cache entry '%s' has date %s, holidays count: %d", 
                        key, entry_date, len(entry.get("holidays", [])))
        except ValueError:
            logger.warning("Cache entry '%s' has invalid date: %s", key, raw_date)
            continue
        if entry_date == target_date:
            logger.info("Found cached holidays for %s in '%s' entry: %d holidays", 
                       target_date, key, len(entry.get("holidays", [])))
            return _payload_entry_to_result(entry)
    logger.debug("No cached holidays found for %s (checked today and tomorrow entries)", target_date)
    return None


async def get_today_holidays(
    *,
    now: datetime | None = None,
    force_refresh: bool = False,
    session: ClientSession | None = None,
) -> HolidayResult:
    """Fetch and parse today's holidays from calend.ru with caching to disk."""

    moment = _normalize_now(now)
    target_date = moment.date()

    if not force_refresh:
        cached = get_cached_holiday_result(target_date)
        # If cache contains actual holiday data, return it immediately.
        # If cache exists but has no holidays, attempt to refresh instead
        # (prevents returning empty results from default payload).
        if cached and cached.has_data:
            _cache_store(cached)
            return cached

    try:
        result = await refresh_holiday_cache(now=moment, session=session)
        if result:
            return result
    except Exception as exc:  # pragma: no cover
        logger.warning("Failed to refresh holiday cache: %s", exc)

    cached = get_cached_holiday_result(target_date)
    if cached:
        cached = cached.__class__(
            date=cached.date,
            holidays=cached.holidays,
            source_url=cached.source_url,
            fetched_at=cached.fetched_at,
            error="Не удалось обновить данные о праздниках, показаны сохранённые ранее.",
        )
        _cache_store(cached)
        return cached

    fallback = HolidayResult(
        date=target_date,
        holidays=(),
        source_url=CALEND_RU_URL,
        fetched_at=moment,
        error="Не удалось получить данные о праздниках.",
    )
    _cache_store(fallback)
    return fallback


async def refresh_holiday_cache(
    *,
    now: datetime | None = None,
    session: ClientSession | None = None,
) -> HolidayResult | None:
    """Refresh the JSON cache for today and tomorrow.
    
    Behavior depends on current time:
    - If called at 23:50 MSK (or 23:45-23:59): Fetches holidays for tomorrow (for 00:00)
    - Otherwise: Fetches holidays for today (normal refresh)
    
    This ensures:
    - At 23:50 MSK, tomorrow's holidays are cached for 00:00 autopost
    - At other times, today's holidays are cached normally
    - calend.ru updates at 00:05 MSK, but we fetch at 23:50 to have data ready at 00:00
    """

    moment = _normalize_now(now)
    async with _refresh_lock:
        current_date = moment.date()
        
        # Check if we're close to midnight (23:45-23:59) - fetch for tomorrow
        # Otherwise fetch for today
        hour = moment.hour
        minute = moment.minute
        is_near_midnight = hour == 23 and minute >= 45
        
        if is_near_midnight:
            # At 23:50, fetch holidays for tomorrow (which becomes today at 00:00)
            today_date = current_date + timedelta(days=1)
            tomorrow_date = current_date + timedelta(days=2)
            logger.info("Refreshing cache for tomorrow (23:50 logic): today=%s, tomorrow=%s", today_date, tomorrow_date)
        else:
            # Normal refresh: fetch holidays for today
            today_date = current_date
            tomorrow_date = current_date + timedelta(days=1)
            logger.info("Refreshing cache for today (normal refresh): today=%s, tomorrow=%s", today_date, tomorrow_date)

        # Download HTML for each date separately to ensure correct data
        logger.info("Downloading HTML for today=%s and tomorrow=%s", today_date, tomorrow_date)
        today_html = await _download_html(target_date=today_date, session=session)
        tomorrow_html = await _download_html(target_date=tomorrow_date, session=session)
        
        # Parse holidays
        logger.info("Parsing holidays for today=%s", today_date)
        today_holidays = tuple(_parse_holidays(today_html, today_date))
        logger.info("Parsed %d holidays for today=%s", len(today_holidays), today_date)
        
        logger.info("Parsing holidays for tomorrow=%s", tomorrow_date)
        tomorrow_holidays = tuple(_parse_holidays(tomorrow_html, tomorrow_date))
        logger.info("Parsed %d holidays for tomorrow=%s", len(tomorrow_holidays), tomorrow_date)

        payload = _ensure_payload()
        # Update cache
        payload["today"] = _serialize_day(today_date, today_holidays, moment)
        payload["tomorrow"] = _serialize_day(tomorrow_date, tomorrow_holidays, moment)
        payload["updated_at"] = _format_datetime(moment)
        _write_payload(payload)

        logger.info("Holiday cache refreshed at %s: today=%s (%d holidays), tomorrow=%s (%d holidays)",
                   moment.strftime("%Y-%m-%d %H:%M:%S"),
                   today_date, len(today_holidays),
                   tomorrow_date, len(tomorrow_holidays))
        
        if len(today_holidays) == 0:
            logger.warning("WARNING: No holidays found for today=%s! This might indicate a parsing issue.", today_date)
        if len(tomorrow_holidays) == 0:
            logger.warning("WARNING: No holidays found for tomorrow=%s! This might indicate a parsing issue.", tomorrow_date)

        result = _payload_entry_to_result(payload["today"])
        if result:
            _cache_store(result)
        return result


def _serialize_day(target_date: date, holidays: Sequence[str], fetched_at: datetime) -> dict[str, Any]:
    return {
        "date": target_date.isoformat(),
        "holidays": list(holidays),
        "fetched_at": _format_datetime(fetched_at),
        "source_url": CALEND_RU_URL,
    }


def _normalize_now(value: datetime | None) -> datetime:
    if value is None:
        if MOSCOW_TZ:
            return datetime.now(MOSCOW_TZ)
        return datetime.now()
    if MOSCOW_TZ and value.tzinfo is None:
        return value.replace(tzinfo=MOSCOW_TZ)
    if MOSCOW_TZ:
        return value.astimezone(MOSCOW_TZ)
    return value


def _cache_store(result: HolidayResult) -> None:
    global _cached_result
    _cached_result = result


async def _download_html(*, target_date: date | None = None, session: ClientSession | None = None, timeout: float = 10.0) -> str:
    """Download HTML from calend.ru for a specific date.
    
    If target_date is None, downloads the main page (today's holidays).
    Otherwise, downloads the page for the specific date.
    """
    if session is None:
        client_timeout = ClientTimeout(total=timeout)
        async with ClientSession(timeout=client_timeout) as owned_session:
            return await _download_html(target_date=target_date, session=owned_session, timeout=timeout)

    # Build URL: https://www.calend.ru/day/YYYY-MM-DD/ for specific date
    # or https://www.calend.ru/day/ for today
    if target_date:
        url = f"{CALEND_RU_URL}{target_date:%Y-%m-%d}/"
    else:
        url = CALEND_RU_URL

    logger.info("Downloading HTML from: %s", url)
    try:
        browser_headers = {
            "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/123.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }

        async with session.get(url, headers=browser_headers) as response:
            response.raise_for_status()
            html = await response.text()
            logger.info("Downloaded HTML: %d bytes, status=%d", len(html), response.status)
            return html
    except asyncio.TimeoutError as exc:
        logger.error("Timeout downloading from %s: %s", url, exc)
        raise RuntimeError("Превышено время ожидания ответа calend.ru") from exc
    except ClientError as exc:
        logger.error("Network error downloading from %s: %s", url, exc)
        raise RuntimeError("Ошибка сети при обращении к calend.ru") from exc


def _parse_holidays(html: str, target_date: date) -> Sequence[str]:
    # calend.ru uses format without leading zeros: div_2025-12-2 instead of div_2025-12-02
    # Format: div_{year}-{month}-{day} where day and month don't have leading zeros
    div_id = f"div_{target_date.year}-{target_date.month}-{target_date.day}"
    logger.debug("Parsing holidays for date %s, looking for div_id=%s", target_date, div_id)
    parser = _HolidayAnchorParser(div_id)
    holidays = parser.feed(html)
    logger.info("Parsed %d holidays for date %s", len(holidays), target_date)
    if not holidays:
        # Log a sample of HTML to help debug
        div_id_in_html = div_id in html
        logger.warning("No holidays found for %s. div_id '%s' found in HTML: %s", 
                      target_date, div_id, div_id_in_html)
        if not div_id_in_html:
            # Try to find similar div IDs in HTML (both with and without leading zeros)
            similar_divs = re.findall(r'id="(div_\d{4}-\d{1,2}-\d{1,2})"', html)
            if similar_divs:
                logger.info("Found similar div IDs in HTML: %s", similar_divs[:10])
    return holidays


def _payload_entry_to_result(entry: dict[str, Any]) -> HolidayResult | None:
    raw_date = entry.get("date")
    if not raw_date:
        return None
    try:
        parsed_date = date.fromisoformat(raw_date)
    except ValueError:
        return None

    holidays = tuple(entry.get("holidays", ()))
    fetched_at = _parse_datetime(entry.get("fetched_at")) or _normalize_now(None)
    source_url = entry.get("source_url") or CALEND_RU_URL
    # Use appropriate error message based on date
    if holidays:
        error = None
    else:
        now = _normalize_now(None).date()
        if parsed_date == now:
            error = "Не найдено праздников на сегодня."
        else:
            error = f"Не найдено праздников на {parsed_date.strftime('%d.%m.%Y')}."
    return HolidayResult(
        date=parsed_date,
        holidays=holidays,
        source_url=source_url,
        fetched_at=fetched_at,
        error=error,
    )


def _load_or_init_payload(cache_path: Path, default_autopost_time: str) -> dict[str, Any]:
    if cache_path.exists():
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Holiday cache corrupted (%s), recreating.", exc)
            payload = _default_payload(default_autopost_time)
    else:
        payload = _default_payload(default_autopost_time)

    if not payload.get("autopost_time"):
        payload["autopost_time"] = default_autopost_time
    if not payload.get("today"):
        payload["today"] = _serialize_day(date.today(), (), _normalize_now(None))
    if not payload.get("tomorrow"):
        payload["tomorrow"] = _serialize_day(date.today() + timedelta(days=1), (), _normalize_now(None))
    # Migrate old autopost_message_id to new structure if needed
    if "autopost_message_id" in payload and "autopost_message_ids" not in payload:
        old_id = payload.get("autopost_message_id")
        if old_id is not None:
            # Try to get target_chat_id from config if available
            try:
                from ..config import config
                chat_id_str = str(config.target_chat_id)
                payload["autopost_message_ids"] = {chat_id_str: old_id}
            except Exception:
                # If config not available, just create empty dict
                payload["autopost_message_ids"] = {}
        else:
            payload["autopost_message_ids"] = {}
        # Remove old field
        payload.pop("autopost_message_id", None)
    if "autopost_message_ids" not in payload:
        payload["autopost_message_ids"] = {}
    # original_chat_title is optional, don't initialize it

    _write_payload(payload, cache_path=cache_path)
    return payload


def _default_payload(autopost_time: str) -> dict[str, Any]:
    moment = _normalize_now(None)
    return {
        "autopost_time": autopost_time,
        "updated_at": _format_datetime(moment),
        "today": _serialize_day(moment.date(), (), moment),
        "tomorrow": _serialize_day(moment.date() + timedelta(days=1), (), moment),
        "autopost_message_ids": {},
    }


def _ensure_payload() -> dict[str, Any]:
    global _cache_payload
    if _cache_payload is None:
        if _cache_file is None:
            raise RuntimeError("Holiday cache is not initialized")
        _cache_payload = _load_or_init_payload(_cache_file, "00:00")
    return _cache_payload


def _write_payload(payload: dict[str, Any], *, cache_path: Path | None = None) -> None:
    target_path = cache_path or _cache_file
    if target_path is None:
        return
    try:
        target_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as exc:  # pragma: no cover
        logger.warning("Failed to persist holiday cache: %s", exc)


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None and MOSCOW_TZ:
        parsed = parsed.replace(tzinfo=MOSCOW_TZ)
    return parsed


def _format_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return _normalize_now(value).isoformat()


def _normalize_time(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("Время должно быть в формате ЧЧ:ММ")
    valuestrip = value.strip()
    if not valuestrip:
        raise ValueError("Время должно быть в формате ЧЧ:ММ")
    parts = valuestrip.split(":" )
    if len(parts) != 2:
        raise ValueError("Время должно быть в формате ЧЧ:ММ")
    hour, minute = parts
    try:
        hour_int = int(hour)
        minute_int = int(minute)
    except ValueError as exc:
        raise ValueError("Время должно быть в формате ЧЧ:ММ") from exc
    if not (0 <= hour_int <= 23 and 0 <= minute_int <= 59):
        raise ValueError("Недопустимое значение часов или минут")
    return f"{hour_int:02d}:{minute_int:02d}"


def _notify_autopost_update() -> None:
    if _autopost_event is not None:
        _autopost_event.set()


def select_autopost_holiday(holidays: Sequence[str]) -> str | None:
    """Select a single holiday for autopost, prioritizing those without 'Россия'."""
    if not holidays:
        return None
    
    # First, try to find holidays without "Россия" (case-insensitive)
    without_russia = [
        h for h in holidays
        if "россия" not in h.lower() and "russia" not in h.lower()
    ]
    
    if without_russia:
        return without_russia[0]
    
    # If all contain "Россия", return the first one
    return holidays[0]


def get_autopost_message_id(chat_id: int) -> int | None:
    """Get the stored autopost message ID for a specific chat."""
    payload = _ensure_payload()
    message_ids = payload.get("autopost_message_ids", {})
    if not isinstance(message_ids, dict):
        return None
    chat_id_str = str(chat_id)
    msg_id = message_ids.get(chat_id_str)
    if msg_id is None:
        return None
    try:
        return int(msg_id)
    except (ValueError, TypeError):
        return None


def set_autopost_message_id(chat_id: int, message_id: int | None) -> None:
    """Store the autopost message ID for a specific chat."""
    payload = _ensure_payload()
    if "autopost_message_ids" not in payload or not isinstance(payload.get("autopost_message_ids"), dict):
        payload["autopost_message_ids"] = {}
    chat_id_str = str(chat_id)
    if message_id is None:
        payload["autopost_message_ids"].pop(chat_id_str, None)
    else:
        payload["autopost_message_ids"][chat_id_str] = message_id
    _write_payload(payload)


def get_original_chat_title() -> str | None:
    """Get the stored original chat title (without emoji)."""
    payload = _ensure_payload()
    return payload.get("original_chat_title")


def set_original_chat_title(title: str | None) -> None:
    """Store the original chat title (without emoji)."""
    payload = _ensure_payload()
    if title is None:
        payload.pop("original_chat_title", None)
    else:
        payload["original_chat_title"] = title
    _write_payload(payload)
