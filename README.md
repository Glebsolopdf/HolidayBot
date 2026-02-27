# Holiday Bot

This repository contains a small Telegram bot that fetches daily holidays from calend.ru, exposes a `/today` command, supports inline queries, and posts a daily autopost message with emoji and chat-title updates.

See language-specific documentation in the repository root:

- English: `README.md` (this file)
- Russian: `README_ru.md`

Highlights

- `/today` — lists holidays for today; each holiday is decorated with an emoji when a fragment matches.
- Autopost — bot sends a single prioritized holiday message each day (`<emoji> Сегодня <holiday>!`), pins it, and unpins the previous autopost.
- Chat title emoji — bot prefixes the chat title with the autopost emoji while preserving the original title when possible.

New: emoji mapping loaded from JSON

The mapping of substring fragments to emojis is now stored in `holiday_emojis.json` (next to `holiday_emojis.py`). On import the module attempts to load that file:

- If the JSON file does not exist, the module will create a bootstrap `holiday_emojis.json` with default fragment→emoji pairs.
- If the JSON file exists and is valid it will be used. If it is invalid, the module logs a warning and falls back to built-in defaults.
- Format expected: a JSON array of pairs: `[ ["frag","emoji"], ... ]`. The fragment is matched as a lowercase substring.

Requirements

- Python 3.13
- See `requirements.txt` for runtime dependencies (`aiogram`, `aiohttp`, `python-dotenv`).

Notes

- The bot must have admin rights in target chat(s) to pin messages and change chat title for autopost features to work.
- Emoji selection is a simple substring match; unmatched holidays get the default emoji 🎉.
