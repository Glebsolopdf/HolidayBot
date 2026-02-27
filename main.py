#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import logging
import os
import re
from dotenv import load_dotenv
from datetime import datetime, time, timedelta
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message

from holidays import (
    initialize_holiday_cache,
    register_autopost_event,
    get_today_holidays,
    get_autopost_time,
    MOSCOW_TZ,
)
from holidays import get_autopost_message_id, set_autopost_message_id
from holiday_emojis import FRAGMENTS, decorate_holiday, emoji_for_holiday
from holidays import get_original_chat_title, set_original_chat_title
from inline_handlers import register_inline_handlers

LOG = logging.getLogger("holiday_bot")


def _get_env(name: str, default: str | None = None) -> str:
    val = os.getenv(name)
    if val:
        return val
    if default is not None:
        return default
    raise RuntimeError(f"Environment variable {name} is required")


async def autopost_loop(bot: Bot, chat_id: int, cache_path: Path, event: asyncio.Event):
    # Autopost loop assumes cache was initialized by the caller.
    # (Initialization is done once in main to avoid circular calls.)

    while True:
        try:
            autopost_time = get_autopost_time()
            hour, minute = [int(x) for x in autopost_time.split(":")]

            now = datetime.now(MOSCOW_TZ) if MOSCOW_TZ else datetime.now()
            today_target = datetime.combine(now.date(), time(hour, minute))
            if MOSCOW_TZ and today_target.tzinfo is None:
                today_target = today_target.replace(tzinfo=MOSCOW_TZ)

            if today_target <= now:
                next_run = today_target + timedelta(days=1)
            else:
                next_run = today_target

            seconds = (next_run - now).total_seconds()
            LOG.info("Next autopost scheduled at %s (in %.0f seconds)", next_run.isoformat(), seconds)

            # Wait for either the time to elapse or an autopost-time update event
            try:
                await asyncio.wait_for(event.wait(), timeout=seconds)
                # event set -> autopost time changed; clear and continue to recalc
                event.clear()
                LOG.info("Autopost time updated, recalculating schedule")
                continue
            except asyncio.TimeoutError:
                # time reached -> send autopost
                pass

            LOG.info("Running autopost for %s", next_run.date())
            result = await get_today_holidays()
            if result is None:
                text = "Ошибка при получении праздников."
            else:
                if result.holidays:
                    # Select a single holiday for autopost.
                    # Prefer a holiday whose emoji is present and not the generic 🎉.
                    selected = None
                    selected_emoji = None
                    for h in result.holidays:
                        em = emoji_for_holiday(h)
                        if em and em != "🎉":
                            selected = h
                            selected_emoji = em
                            break

                    if selected is None:
                        # Fall back to the first holiday; use its emoji if any, else default 🎉
                        selected = result.holidays[0]
                        selected_emoji = emoji_for_holiday(selected) or "🎉"

                    text = f"{selected_emoji} Сегодня {selected}!"
                else:
                    text = result.error or "Праздников не найдено."

            # Autopost workflow:
            # 1) unpin previous autopost message (if any)
            # 2) update chat title to prefix with selected emoji
            # 3) send new autopost message
            # 4) pin the new message
            # 5) save new pinned message id
            try:
                prev_id = get_autopost_message_id(chat_id)
                if prev_id:
                    try:
                        await bot.unpin_chat_message(chat_id, message_id=prev_id)
                    except Exception:
                        LOG.exception("Failed to unpin previous autopost message %s in chat %s", prev_id, chat_id)

                # Update chat title: preserve original title (without emoji) in cache.
                # If the chat title was changed manually (and doesn't start with
                # a known fragment emoji), treat that new title as the new original.
                try:
                    orig = get_original_chat_title()
                    chat = await bot.get_chat(chat_id)
                    current_title = chat.title or ""

                    # Remove all leading non-word characters (emojis, punctuation, etc.)
                    # Keep the first non-empty word-like portion as the canonical title.
                    cleaned = re.sub(r'^[^\w]+', '', current_title).lstrip()

                    # If no original saved yet, or the current cleaned title
                    # differs from saved original (i.e. manual change), update it.
                    if not orig or (cleaned and cleaned != orig):
                        orig = cleaned
                        set_original_chat_title(orig)

                    # Use the selected emoji (computed earlier) when setting title.
                    new_emoji = locals().get('selected_emoji')
                    if new_emoji:
                        new_title = f"{new_emoji} {orig}" if orig else new_emoji
                        try:
                            await bot.set_chat_title(chat_id, new_title)
                        except Exception:
                            LOG.exception("Failed to set chat title for %s to %s", chat_id, new_title)
                except Exception:
                    LOG.exception("Failed to update chat title for chat %s", chat_id)

                # Send new message
                try:
                    msg = await bot.send_message(chat_id, text)
                except Exception:
                    LOG.exception("Failed to send autopost message to %s", chat_id)
                    continue

                # Pin the new message
                try:
                    await bot.pin_chat_message(chat_id, msg.message_id, disable_notification=False)
                except Exception:
                    LOG.exception("Failed to pin autopost message %s in chat %s", msg.message_id, chat_id)

                # Save new pinned message id in cache
                try:
                    set_autopost_message_id(chat_id, msg.message_id)
                except Exception:
                    LOG.exception("Failed to save autopost message id for chat %s", chat_id)
            except Exception:
                LOG.exception("Autopost pinning/title flow failed for chat %s", chat_id)

        except Exception as exc:  # keep loop alive on unexpected errors
            LOG.exception("Autopost loop error: %s", exc)
            await asyncio.sleep(60)


async def cmd_today_handler(message: Message):
    result = await get_today_holidays()
    if result is None:
        await message.answer("Ошибка при получении праздников.")
        return
    if result.holidays:
        lines = [f"Праздники на {result.date.strftime('%d.%m.%Y')}"]
        for h in result.holidays:
            lines.append(f"- {decorate_holiday(h)}")
        await message.answer("\n".join(lines))
    else:
        await message.answer(result.error or "Праздников не найдено.")


async def main():
    logging.basicConfig(level=logging.INFO)
    # Load environment from .env (if present)
    load_dotenv()
    token = _get_env("BOT_TOKEN")
    # Support multiple target chats via TARGET_CHAT_IDS (comma-separated),
    # fallback to single TARGET_CHAT_ID for backward compatibility.
    raw_ids = os.getenv("TARGET_CHAT_IDS") or os.getenv("TARGET_CHAT_ID")
    if not raw_ids:
        raise RuntimeError("TARGET_CHAT_IDS or TARGET_CHAT_ID is required")
    chat_ids = [int(x.strip()) for x in raw_ids.split(",") if x.strip()]
    cache_path = Path(os.getenv("HOLIDAY_CACHE_PATH", "holiday_cache.json"))

    # Initialize holiday cache once here to avoid circular dependency
    # (do not call get_autopost_time() before cache exists)
    initialize_holiday_cache(cache_path, default_autopost_time=os.getenv("AUTOPOST_TIME", "00:00"))

    bot = Bot(token)
    dp = Dispatcher()
    dp.message.register(cmd_today_handler, Command(commands=["today"]))
    register_inline_handlers(dp)

    # Event shared between autopost tasks so updating autopost time notifies all
    autopost_event = asyncio.Event()
    register_autopost_event(autopost_event)

    # Start autopost loop tasks for each configured chat
    loops = [asyncio.create_task(autopost_loop(bot, cid, cache_path, autopost_event)) for cid in chat_ids]

    try:
        await dp.start_polling(bot)
    finally:
        for t in loops:
            t.cancel()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
