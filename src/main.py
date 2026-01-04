# Bot to monitor channels and replace social media links with prettier formatting

import os
import re
import asyncio
from typing import Dict, List, Tuple, Optional, Callable
from collections import defaultdict
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

# Track recently processed message IDs to avoid loops
recently_processed = set()
MAX_PROCESSED_CACHE = 1000


# ==================== UTILITY FUNCTIONS ====================

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


async def send_preserved_message(
    channel: discord.TextChannel,
    author_name: str,
    new_content: str,
    view: Optional[discord.ui.View] = None,
    attachments: Optional[List[discord.Attachment]] = None
) -> Optional[discord.Message]:
    """Send the rewritten message with preserved content and attachments."""
    try:
        # Format message with author name
        formatted_content = f"{author_name}: {new_content}"
        
        # Discord has a 2000 character limit
        if len(formatted_content) > 2000:
            formatted_content = formatted_content[:1997] + "..."
        
        # Prepare files from attachments
        files = []
        if attachments:
            for attachment in attachments:
                try:
                    # Download and re-attach files
                    file_data = await attachment.read()
                    files.append(discord.File(fp=file_data, filename=attachment.filename))
                except Exception as e:
                    print(f"Failed to re-attach file {attachment.filename}: {e}")
        
        # Send the message
        return await channel.send(content=formatted_content, view=view, files=files if files else None)
    
    except discord.Forbidden:
        print(f"Missing permissions to send message in channel {channel.id}")
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
    # Skip if already rewritten
    if "fxtwitter.com" in content:
        return None
    
    # Check if Twitter/X link exists
    if not any(domain in content for domain in ["https://x.com", "https://twitter.com", "https://www.x.com", "https://www.twitter.com"]):
        return None
    
    # Regex pattern from pingbot
    pattern = r"https://(www\.)?(x|twitter)\.com/([a-zA-Z0-9_]+)/status/([0-9]+)"
    
    new_content = re.sub(
        pattern,
        r"https://fxtwitter.com/\3/status/\4",
        content
    )
    
    if new_content == content:
        return None
    
    # Find original link for the button
    match = re.search(pattern, content)
    if match:
        original_link = f"https://{match.group(1) or ''}{'x' if match.group(2) == 'x' else 'twitter'}.com/{match.group(3)}/status/{match.group(4)}"
        view = build_link_button(original_link, "Open in X")
        
        return {
            "new_text": new_content,
            "original_url": original_link,
            "view": view,
            "delete_original": True
        }
    
    return None


async def handle_reddit(message: discord.Message, content: str) -> Optional[Dict]:
    """Handle Reddit link rewriting."""
    # Skip if already rewritten
    if "vxreddit.com" in content:
        return None
    
    # Check if Reddit link exists
    if not any(domain in content for domain in ["https://reddit.com", "https://www.reddit.com"]):
        return None
    
    # Regex pattern from pingbot
    pattern = r"https://(www\.)?reddit\.com"
    
    new_content = re.sub(
        pattern,
        r"https://vxreddit.com",
        content
    )
    
    if new_content == content:
        return None
    
    # Find original link for the button
    match = re.search(r"https://(www\.)?reddit\.com[^\s]*", content)
    if match:
        original_link = match.group(0)
        view = build_link_button(original_link, "Open in Reddit")
        
        return {
            "new_text": new_content,
            "original_url": original_link,
            "view": view,
            "delete_original": True
        }
    
    return None


async def handle_tiktok(message: discord.Message, content: str) -> Optional[Dict]:
    """Handle TikTok link rewriting."""
    # Skip if already rewritten
    if "tnktok.com" in content:
        return None
    
    # Check if TikTok link exists
    if not any(domain in content for domain in ["https://tiktok.com", "https://www.tiktok.com"]):
        return None
    
    # Regex pattern from pingbot
    pattern = r"https://(www\.)?tiktok\.com"
    
    new_content = re.sub(
        pattern,
        r"https://\1tnktok.com",
        content
    )
    
    if new_content == content:
        return None
    
    # Find original link for the button
    match = re.search(r"https://(www\.)?tiktok\.com[^\s]*", content)
    if match:
        original_link = match.group(0)
        view = build_link_button(original_link, "Open in TikTok")
        
        return {
            "new_text": new_content,
            "original_url": original_link,
            "view": view,
            "delete_original": True
        }
    
    return None


# ==================== HANDLER REGISTRY ====================

def get_handlers() -> List[Callable]:
    """Return the list of handler functions to check in order."""
    return [
        handle_twitter,
        handle_reddit,
        handle_tiktok,
    ]


# ==================== MAIN MESSAGE HANDLER ====================

@client.event
async def on_ready():
    print(f"Bot logged in as {client.user}")
    print(f"Active in {len(client.guilds)} servers")


@client.event
async def on_message(message: discord.Message):
    # Ignore bot messages, webhooks, and self
    if is_bot_message_or_from_self(message):
        return
    
    # Ignore recently processed messages to avoid loops
    if message.id in recently_processed:
        return
    
    # Ignore empty messages
    if not message.content:
        return
    
    # Acquire per-channel lock to prevent race conditions
    async with channel_locks[message.channel.id]:
        # Try each handler in order
        handlers = get_handlers()
        
        for handler in handlers:
            try:
                result = await handler(message, message.content)
                
                if result is None:
                    continue
                
                # Handler matched and returned a result
                new_text = result.get("new_text")
                view = result.get("view")
                delete_original = result.get("delete_original", False)
                
                if not new_text:
                    continue
                
                # Send the preserved message
                sent_message = await send_preserved_message(
                    channel=message.channel,
                    author_name=message.author.display_name,
                    new_content=new_text,
                    view=view,
                    attachments=message.attachments if message.attachments else None
                )
                
                if sent_message:
                    # Track that message was processed
                    recently_processed.add(message.id)
                    recently_processed.add(sent_message.id)
                    
                    # Maintain cache size
                    if len(recently_processed) > MAX_PROCESSED_CACHE:
                        # Remove oldest
                        recently_processed.pop()
                    
                    # Delete original if requested
                    if delete_original and await can_delete_messages(message.channel):
                        try:
                            await message.delete()
                        except discord.NotFound:
                            pass
                        except discord.Forbidden:
                            print(f"Missing permission to delete message in channel {message.channel.id}")
                        except discord.HTTPException as e:
                            print(f"HTTP error deleting message: {e}")
                
                # Only process first matching handler
                break
            
            except Exception as e:
                print(f"Error in handler {handler.__name__}: {e}")
                continue


client.run(TOKEN)