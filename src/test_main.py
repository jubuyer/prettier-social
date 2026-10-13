# Run with: python src/test_main.py

import asyncio
import main

LINK = "https://x.com/user/status/123"
REWRITTEN = "https://fxtwitter.com/user/status/123"


def test_append_translation():
    out = main.append_translation(REWRITTEN, "Korean", "line one\nline two")
    assert out == f"{REWRITTEN}\n> **Translated from Korean:**\n> line one\n> line two"

    long = main.append_translation(REWRITTEN, "ko", "x" * 5000)
    assert len(long) <= main.MAX_MESSAGE_LENGTH
    assert long.endswith("...")

    # No room left for a translation: content is returned untouched
    full = "y" * main.MAX_MESSAGE_LENGTH
    assert main.append_translation(full, "ko", "hi") == full


def test_handle_twitter():
    async def translated(user, tweet_id):
        assert (user, tweet_id) == ("user", "123")
        return "Korean", "hello"

    async def untranslated(user, tweet_id):
        return None

    main.fetch_translation = translated
    result = asyncio.run(main.handle_twitter(None, f"look {LINK}"))
    assert result["new_text"] == f"look {REWRITTEN}\n> **Translated from Korean:**\n> hello"
    assert result["original_url"] == LINK

    main.fetch_translation = untranslated
    result = asyncio.run(main.handle_twitter(None, f"look {LINK}"))
    assert result["new_text"] == f"look {REWRITTEN}"


if __name__ == "__main__":
    test_append_translation()
    test_handle_twitter()
    print("ok")
