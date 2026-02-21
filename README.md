# Holiday-only bot

This small bot posts daily holidays (from calend.ru) and exposes a `/today` command.


Configuration (preferred):

- Copy `.env.example` → `.env` and fill `BOT_TOKEN` and `TARGET_CHAT_ID`.
- Or set environment variables `BOT_TOKEN`, `TARGET_CHAT_ID`, and optionally `HOLIDAY_CACHE_PATH`.
 - Copy `.env.example` → `.env` and fill `BOT_TOKEN` and `TARGET_CHAT_IDS`.
 - You can specify multiple chats in `.env` using `TARGET_CHAT_IDS` as a comma-separated list.
 - Or set environment variables `BOT_TOKEN`, `TARGET_CHAT_IDS`, and optionally `HOLIDAY_CACHE_PATH`.

Run:

# Holiday Bot — English / Русский

- Quick links: [Русская документация](#русская-документация) · [English documentation](#english-documentation)

---

## English documentation

This bot fetches holidays (from calend.ru), provides `/today`, supports inline queries, and posts a daily autopost with optional pinning and chat-title emoji.

Features

- `/today` — list all holidays for today (each decorated with an emoji when possible).
- Autopost — sends a single prioritized holiday each day in format: `<emoji> Сегодня <holiday>!`, pins it and unpins previous autopost.
- Chat title emoji — the bot prefixes the chat title with the autopost emoji (preserving the original title and respecting manual title changes).
- Inline mode — type `@YourBot <query>` to get today's holidays as an inline result.

Requirements

- Python 3.11+
- See `requirements.txt` for runtime dependencies (aiogram, aiohttp, ...).

Configuration

1. Copy `env.example` to `.env` and set at least `BOT_TOKEN` and `TARGET_CHAT_ID` (or `TARGET_CHAT_IDS` for multiple chats).
2. Optional environment variables:
	- `HOLIDAY_CACHE_PATH` — path to cache JSON (default: `holiday_cache.json`).
	- `AUTOPOST_TIME` — autopost time in MSK `HH:MM` (default stored in cache or `00:00`).

Run

```bash
pip install -r requirements.txt
cp .env.example .env
# edit .env -> set BOT_TOKEN and TARGET_CHAT_ID(S)
python main.py
```

Notes

- The bot must be admin in the target chat(s) with permissions to pin messages and change chat title for autopost features to work.
- Emoji selection is a simple substring match; unmatched holidays get the default emoji 🎉.

---

## Русская документация

Коротко: бот получает праздники с calend.ru, предоставляет команду `/today`, поддерживает inline‑режим и ежедневно делает автопост с опциональным закреплением и префиксом эмодзи в названии чата.

Возможности

- `/today` — перечисляет все праздники на сегодня (каждый с эмодзи, если совпадает фрагмент).
- Автопост — отправляет один выбранный праздник в формате: `<emoji> Сегодня <праздник>!`, закрепляет его и открепляет предыдущий автопост.
- Эмодзи в названии чата — бот префиксит эмодзи к названию чата, при этом сохраняет и уважает ручные изменения названия (если админ изменил текст, бот примет его как новый «оригинал»).
- Inline‑режим — введите `@YourBot` в любом чате и выберите результат «Праздники сегодня».

Требования

- Python 3.11 или выше.
- См. `requirements.txt` для зависимостей (`aiogram`, `aiohttp` и т.д.).

Настройка

1. Скопируйте `env.example` → `.env` и укажите `BOT_TOKEN` и `TARGET_CHAT_ID` (или `TARGET_CHAT_IDS`).
2. Опционные переменные окружения:
	- `HOLIDAY_CACHE_PATH` — путь к файлу кеша (по умолчанию `holiday_cache.json`).
	- `AUTOPOST_TIME` — время автопоста в Московском часовом поясе в формате `HH:MM`.

Запуск

```bash
pip install -r requirements.txt
cp .env.example .env
# отредактируйте .env -> укажите BOT_TOKEN и TARGET_CHAT_ID(S)
python main.py
```

Примечания

- Для работы автопоста, закрепления и изменения названия бот должен быть администратором с соответствующими правами.
- Сопоставление эмодзи осуществляется по подстрокам (фрагментам); если нет подходящего эмодзи — используется 🎉.

---
