"""Inline query handlers for holiday bot.

Provides an inline handler that returns today's holidays as an
`InlineQueryResultArticle` and a `register_inline_handlers(dp)` helper
to attach handlers to a `Dispatcher`.
"""
from __future__ import annotations

import logging
from aiogram import Dispatcher
from aiogram.types import InlineQuery, InlineQueryResultArticle, InputTextMessageContent

from holidays import get_today_holidays
from holiday_emojis import decorate_holiday

LOG = logging.getLogger(__name__)


async def inline_today_handler(inline_query: InlineQuery):
    try:
        result = await get_today_holidays()
        if result is None:
            content = "Ошибка при получении праздников."
        elif result.holidays:
            lines = [f"Праздники на {result.date.strftime('%d.%m.%Y')}:"]
            for h in result.holidays:
                lines.append(f"- {decorate_holiday(h)}")
            content = "\n".join(lines)
        else:
            content = result.error or "Праздников не найдено."

        article = InlineQueryResultArticle(
            id="today_holidays",
            title="Праздники сегодня",
            input_message_content=InputTextMessageContent(message_text=content),
            description=(content.splitlines()[0] if content else "Праздники на сегодня"),
        )
        await inline_query.answer(results=[article], cache_time=30)
    except Exception:
        LOG.exception("Inline query handler failed")


def register_inline_handlers(dp: Dispatcher) -> None:
    """Register inline handlers on the given Dispatcher."""
    dp.inline_query.register(inline_today_handler)
