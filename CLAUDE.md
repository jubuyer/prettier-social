# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A stateless Discord bot (discord.py 2.x) that reposts messages containing Twitter/X, Reddit, TikTok, or Instagram links with the domain swapped for an embed-friendly proxy (`fxtwitter.com`, `vxreddit.com`, `tnktok.com`, `zzinstagram.com`), then deletes the original. The whole bot is `src/main.py`.

## Commands

```bash
# Local
pip install -r requirements.txt
python src/main.py

# Docker
docker compose up -d --build
docker compose logs -f bot

# Tests (plain asserts, no pytest)
python src/test_main.py
```

Requires `BOT_TOKEN` in `.env` (gitignored; loaded by `python-dotenv` locally and by `env_file` in compose). The bot needs the privileged **Message Content** intent enabled in the Discord developer portal.

There is no linter. Do not run the bot locally with the production `BOT_TOKEN` while it is deployed: two instances would both repost every message.

Deployment: `.github/workflows/docker-publish.yml` publishes `jubuyer/prettier-social` (`:latest` and `:sha-<commit>`, amd64 + arm64) to Docker Hub on every push to `main`, using the `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN` repo secrets. A Komodo instance pulls that image.

## Architecture

`on_message` flow:

1. Drop messages from bots/webhooks (`is_bot_message_or_from_self`) and IDs in `recently_processed` — together these prevent the bot from reprocessing its own reposts.
2. Under a per-channel `asyncio.Lock`, run handlers from `get_handlers()` in order. **The first handler returning a result wins** (`break`), so a message with links to two different platforms only has one platform rewritten.
3. `send_preserved_message` reposts, then the original is deleted if the bot has Manage Messages.

### Handler contract

Each `handle_<platform>(message, content)` returns `None` to pass, or a dict with `new_text`, `original_url`, `view` (a link button from `build_link_button`), and `delete_original`. To add a platform, write a handler and append it to `get_handlers()`; the README has a template.

Handler quirks worth knowing before editing them:

- The "already rewritten" guard is a substring check on the whole message, so a message containing both a proxy link and an un-rewritten link of the same platform is skipped entirely.
- Only `https://` links match, with or without `www.`.
- `re.sub` rewrites every matching link, but `original_url` and the button point only at the first match.
- Twitter matches only `/<user>/status/<id>` URLs; the other three rewrite any URL on the domain.
- TikTok keeps the `www.` prefix (`\1tnktok.com`); the others drop it.

### Tweet translation

`handle_twitter` calls `fetch_translation`, which hits the keyless FxTwitter API (`api.fxtwitter.com/<user>/status/<id>/en`, 5 s timeout). For a non-English tweet, `append_translation` adds the English text as a quote block under the link, trimmed to fit Discord's 2000-character limit. Any API failure returns `None` and the link is still rewritten. Only the first tweet in a message is translated. `source_lang_en` (the language name) is not always in the response, so the label falls back to the language code.

### Send routing (`send_preserved_message`)

- **Non-reply** → channel webhook named `prettier-social` (found or created, cached in `webhook_cache`), sent with the author's display name and avatar so it looks like the user posted it.
- **Reply** → `channel.send(reference=...)` as the bot user, with content prefixed `**display name**: ` and truncated to 2000 chars. Webhooks can't set a message reference, so this path is the only way to keep Discord's reply UI.
- Webhook unavailable or failing → falls back to the reply-style `channel.send` path.

Attachments are re-downloaded and re-uploaded on every send attempt (`fetch_attachments`) because `discord.File` objects are consumed by a send. All sends use `AllowedMentions.none()` so reposts don't re-ping.

### Permissions

The webhook path needs **Manage Webhooks**, which the README's permission list omits; without it the bot silently degrades to the bot-user path. Manage Messages is needed to delete the original; without it both messages remain.

### State

All state is in-process and lost on restart: `channel_locks`, `webhook_cache`, and `recently_processed` (FIFO-capped at 1000 via a paired deque).
