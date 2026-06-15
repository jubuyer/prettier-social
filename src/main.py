# Bot to monitor channels and replace social media links with prettier formatting

import os
import io
import re
import asyncio
from typing import Dict, List, Optional, Callable
from collections import defaultdict, deque
import discord
from dotenv import load_dotenv

# Load env vars
load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")

intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)

# Per-channel locks to prevent race conditions
channel_locks = defaultdict(asyncio.Lock)

# Track recently processed message IDs to avoid loops.
# Using a deque so eviction is FIFO (oldest first), not arbitrary like set.pop().
recently_processed: set = set()
recently_processed_order: deque = deque()
MAX_PROCESSED_CACHE = 1000

# Cache for webhooks
webhook_cache: Dict[int, discord.Webhook] = {}


# ==================== UTILITY FUNCTIONS ====================

async def get_or_create_webhook(channel: discord.TextChannel) -> Optional[discord.Webhook]:
    """Get a webhook from cache, or create a new one."""
    if channel.id in webhook_cache:
        return webhook_cache[channel.id]

    permissions = channel.permissions_for(channel.guild.me)
    if not permissions.manage_webhooks:
        print(f"Missing 'Manage Webhooks' permission in channel {channel.id}")
        return None

    try:
        webhooks = await channel.webhooks()
        for webhook in webhooks:
            if webhook.name == "prettier-social":
                webhook_cache[channel.id] = webhook
                return webhook

        new_webhook = await channel.create_webhook(name="prettier-social")
        webhook_cache[channel.id] = new_webhook
        return new_webhook

    except discord.Forbidden:
        print(f"Forbidden to create webhook in channel {channel.id}")
        return None
    except Exception as e:
        print(f"Error getting/creating webhook: {e}")
        return None


def is_bot_message_or_from_self(message: discord.Message) -> bool:
    """Check if message is from a bot, webhook, or self."""
    return message.author.bot or message.webhook_id is not None


def build_link_button(original_url: str, label: str) -> discord.ui.View:
    """Create a view with a link button to the original URL."""
    button = discord.ui.Button(style=discord.ButtonStyle.link, url=original_url, label=label)
    view = discord.ui.View()
    view.add_item(button)
    return view


async def can_delete_messages(channel: discord.TextChannel) -> bool:
    """Check if bot has permission to delete messages in the channel."""
    try:
        permissions = channel.permissions_for(channel.guild.me)
        return permissions.manage_messages
    except Exception:
        return False


def track_processed(message_id: int) -> None:
    """Add a message ID to the processed set, evicting the oldest if over limit."""
    recently_processed.add(message_id)
    recently_processed_order.append(message_id)
    if len(recently_processed_order) > MAX_PROCESSED_CACHE:
        oldest = recently_processed_order.popleft()
        recently_processed.discard(oldest)


async def fetch_attachments(message: discord.Message) -> List[discord.File]:
    """Download and wrap each attachment as a fresh discord.File for re-sending.

    discord.File requires a file-like object (io.BytesIO), not raw bytes.
    We always create fresh BytesIO objects so files are not consumed/exhausted
    if a send attempt fails and we need to retry.
    """
    files = []
    for attachment in message.attachments:
        try:
            data = await attachment.read()
            files.append(discord.File(fp=io.BytesIO(data), filename=attachment.filename))
        except Exception as e:
            print(f"Failed to fetch attachment '{attachment.filename}': {e}")
    return files


async def send_preserved_message(
    message: discord.Message,
    new_content: str,
    view: Optional[discord.ui.View] = None,
) -> Optional[discord.Message]:
    """Send the rewritten message, preserving author identity and reply context.

    Routing logic:
    - Non-reply messages → webhook.send() so the sender's name/avatar are shown.
    - Reply messages     → channel.send(reference=...) so Discord's native reply
                           UI is preserved.  Webhooks do NOT support 'reference'
                           at the API level, so this path always uses the bot user.
    - Webhook failure    → automatically falls back to channel.send().
    """
    # message.reference is a MessageReference if the user was replying, else None.
    reply_to = message.reference

    try:
        # ── Webhook path (non-replies only) ───────────────────────────────────
        # Webhooks impersonate the original sender's display name and avatar
        if reply_to is None:
            webhook = await get_or_create_webhook(message.channel)
            if webhook:
                files = await fetch_attachments(message)
                try:
                    send_kwargs: dict = dict(
                        content=new_content,
                        username=message.author.display_name,
                        avatar_url=message.author.display_avatar.url,
                        view=view,
                        allowed_mentions=discord.AllowedMentions.none(),
                        wait=True,  # must be True to get the Message object back
                    )
                    if files:
                        send_kwargs["files"] = files
                    return await webhook.send(**send_kwargs)
                except Exception as e:
                    print(f"Webhook send failed: {e}. Falling back to channel.send.")
                    # Fall through to the regular send path below.

        # ── Regular send path (replies, or webhook fallback) ──────────────────
        # Webhooks can't reply, so for reply messages we use the bot account and
        # manually prefix the author's display name so it's still clear who sent it.
        files = await fetch_attachments(message)
        formatted = f"**{message.author.display_name}**: {new_content}"
        if len(formatted) > 2000:
            formatted = formatted[:1997] + "..."

        send_kwargs = dict(
            content=formatted,
            view=view,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        if files:
            send_kwargs["files"] = files
        if reply_to is not None:
            # Reconstruct the reference with fail_if_not_exists=False so the send
            # still succeeds even if the original message was deleted.
            send_kwargs["reference"] = discord.MessageReference(
                message_id=reply_to.message_id,
                channel_id=reply_to.channel_id,
                guild_id=reply_to.guild_id,
                fail_if_not_exists=False,
            )

        return await message.channel.send(**send_kwargs)

    except discord.Forbidden:
        print(f"Missing permissions to send message in channel {message.channel.id}")
        return None
    except discord.HTTPException as e:
        print(f"HTTP error sending message: {e}")
        return None
    except Exception as e:
        print(f"Unexpected error sending message: {e}")
        return None


# ==================== HANDLER FUNCTIONS ====================

async def handle_twitter(message: discord.Message, content: str) -> Optional[Dict]:
    """Handle Twitter/X link rewriting."""
    if "fxtwitter.com" in content:
        return None

    if not any(domain in content for domain in [
        "https://x.com", "https://twitter.com",
        "https://www.x.com", "https://www.twitter.com",
    ]):
        return None

    pattern = r"https://(www\.)?(x|twitter)\.com/([a-zA-Z0-9_]+)/status/([0-9]+)"
    new_content = re.sub(pattern, r"https://fxtwitter.com/\3/status/\4", content)

    if new_content == content:
        return None

    match = re.search(pattern, content)
    if match:
        original_link = (
            f"https://{match.group(1) or ''}"
            f"{'x' if match.group(2) == 'x' else 'twitter'}.com"
            f"/{match.group(3)}/status/{match.group(4)}"
        )
        return {
            "new_text": new_content,
            "original_url": original_link,
            "view": build_link_button(original_link, "Open in X"),
            "delete_original": True,
        }

    return None


async def handle_reddit(message: discord.Message, content: str) -> Optional[Dict]:
    """Handle Reddit link rewriting."""
    if "vxreddit.com" in content:
        return None

    if not any(domain in content for domain in ["https://reddit.com", "https://www.reddit.com"]):
        return None

    pattern = r"https://(www\.)?reddit\.com"
    new_content = re.sub(pattern, r"https://vxreddit.com", content)

    if new_content == content:
        return None

    match = re.search(r"https://(www\.)?reddit\.com[^\s]*", content)
    if match:
        original_link = match.group(0)
        return {
            "new_text": new_content,
            "original_url": original_link,
            "view": build_link_button(original_link, "Open in Reddit"),
            "delete_original": True,
        }

    return None


async def handle_tiktok(message: discord.Message, content: str) -> Optional[Dict]:
    """Handle TikTok link rewriting."""
    if "tnktok.com" in content:
        return None

    if not any(domain in content for domain in ["https://tiktok.com", "https://www.tiktok.com"]):
        return None

    pattern = r"https://(www\.)?tiktok\.com"
    new_content = re.sub(pattern, r"https://\1tnktok.com", content)

    if new_content == content:
        return None

    match = re.search(r"https://(www\.)?tiktok\.com[^\s]*", content)
    if match:
        original_link = match.group(0)
        return {
            "new_text": new_content,
            "original_url": original_link,
            "view": build_link_button(original_link, "Open in TikTok"),
            "delete_original": True,
        }

    return None


async def handle_instagram(message: discord.Message, content: str) -> Optional[Dict]:
    """Handle Instagram link rewriting."""
    if "zzinstagram.com" in content:
        return None

    if not any(domain in content for domain in ["https://instagram.com", "https://www.instagram.com"]):
        return None

    pattern = r"https://(www\.)?instagram\.com"
    new_content = re.sub(pattern, r"https://zzinstagram.com", content)

    if new_content == content:
        return None

    match = re.search(r"https://(www\.)?instagram\.com[^\s]*", content)
    if match:
        original_link = match.group(0)
        return {
            "new_text": new_content,
            "original_url": original_link,
            "view": build_link_button(original_link, "Open in Instagram"),
            "delete_original": True,
        }

    return None


# ==================== HANDLER REGISTRY ====================

def get_handlers() -> List[Callable]:
    """Return the list of handler functions to check in order."""
    return [
        handle_twitter,
        handle_reddit,
        handle_tiktok,
        handle_instagram,
    ]


# ==================== MAIN MESSAGE HANDLER ====================

@client.event
async def on_ready():
    print(f"Bot logged in as {client.user}")
    print(f"Active in {len(client.guilds)} servers")


@client.event
async def on_message(message: discord.Message):
    if is_bot_message_or_from_self(message):
        return

    if message.id in recently_processed:
        return

    if not message.content:
        return

    async with channel_locks[message.channel.id]:
        for handler in get_handlers():
            try:
                result = await handler(message, message.content)

                if result is None:
                    continue

                new_text = result.get("new_text")
                view = result.get("view")
                delete_original = result.get("delete_original", False)

                if not new_text:
                    continue

                sent_message = await send_preserved_message(
                    message=message,
                    new_content=new_text,
                    view=view,
                )

                if sent_message:
                    track_processed(message.id)
                    track_processed(sent_message.id)

                    if delete_original and await can_delete_messages(message.channel):
                        try:
                            await message.delete()
                        except discord.NotFound:
                            pass
                        except discord.Forbidden:
                            print(f"Missing permission to delete message in channel {message.channel.id}")
                        except discord.HTTPException as e:
                            print(f"HTTP error deleting message: {e}")

                break

            except Exception as e:
                print(f"Error in handler {handler.__name__}: {e}")
                continue


client.run(TOKEN)