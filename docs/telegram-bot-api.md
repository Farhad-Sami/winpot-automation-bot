# Telegram Bot API Reference

Source: <https://core.telegram.org/bots/api>

## Base URL & Authentication
- Every request is an HTTPS call to:
  `https://api.telegram.org/bot<token>/METHOD_NAME`
- Supports `GET` and `POST` (`application/x-www-form-urlencoded`, `application/json`, or `multipart/form-data` for file uploads).
- Bot tokens are obtained from `@BotFather` and must be kept secret (e.g. `TELEGRAM_BOT_TOKEN` in `.env`).

## Receiving Updates
Two mutually exclusive mechanisms:
1. **Long Polling (`getUpdates`)**:
   - Bot pulls updates with `offset`, `limit` (1–100), `timeout` (seconds, e.g. 30).
   - Confirm processed updates by passing `offset = last_update_id + 1`.
   - Ideal for local/background bots (used by `python-telegram-bot`'s `app.run_polling()`).
2. **Webhooks (`setWebhook`)**:
   - Telegram pushes `Update` JSON objects to an HTTPS endpoint (ports 443, 80, 88, or 8443).

## Key Methods
- **`getMe`**: Verify bot token and retrieve bot info (`id`, `username`, `can_join_groups`).
- **`sendMessage`**:
  - `chat_id` (int or `@channelusername`), `text` (1–4096 characters after entity parsing).
  - Optional: `parse_mode` (`HTML`, `MarkdownV2`, `Markdown`), `reply_parameters`, `disable_notification`.
- **`editMessageText`**:
  - `chat_id` + `message_id` (or `inline_message_id`), `text` (1–4096 characters).
  - Useful for updating a `"Visiting..."` status message in place once the result is ready.
- **`setMyCommands`**:
  - Register bot commands (`[{"command": "profiles", "description": "List saved browser profiles"}]`) shown in the Telegram `/` menu.

## Message Limits & Formatting
- **Max text length**: `4096` UTF-8 characters per `sendMessage` / `editMessageText`. Truncate or split longer outputs.
- **Formatting**: Plain text is safest for arbitrary scraped web content; if using `HTML` or `MarkdownV2`, escape special characters (`<`, `>`, `&` for HTML).

## Rate Limits & Error Handling
- Responses return JSON: `{"ok": true, "result": ...}` or `{"ok": false, "error_code": 429, "description": "...", "parameters": {"retry_after": N}}`.
- Respect `retry_after` on `429 Too Many Requests`.
- Avoid exceeding ~30 messages/second globally or ~1 message/second per chat.
