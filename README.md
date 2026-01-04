# Prettier Social - Discord Link Rewriter Bot

A stateless Discord bot that automatically rewrites social media links to use prettier preview services. Works across all servers, channels, and users without any configuration.

## Features

- **Twitter/X Links** → `fxtwitter.com` for better embeds
- **Reddit Links** → `vxreddit.com` for video/media previews
- **TikTok Links** → `tnktok.com` for improved previews

## Required Bot Permissions

- **Read Messages** - To monitor channels
- **Send Messages** - To post rewritten links
- **Manage Messages** - To delete original messages
- **Attach Files** - To re-attach files from original messages
- **Embed Links** - For link previews

## Supported Link Patterns

### Twitter/X
- `https://twitter.com/user/status/123456`
- `https://x.com/user/status/123456`
- `https://www.twitter.com/user/status/123456`
- `https://www.x.com/user/status/123456`

**Rewrites to:** `https://fxtwitter.com/user/status/123456`

### Reddit
- `https://reddit.com/r/subreddit/comments/...`
- `https://www.reddit.com/r/subreddit/comments/...`

**Rewrites to:** `https://vxreddit.com/r/subreddit/comments/...`

### TikTok
- `https://tiktok.com/@user/video/123456`
- `https://www.tiktok.com/@user/video/123456`

**Rewrites to:** `https://tnktok.com/@user/video/123456`


## Extending the Bot

To add a new social platform:

1. Create a handler function following the pattern:
   ```python
   async def handle_newplatform(message: discord.Message, content: str) -> Optional[Dict]:
       # Skip if already rewritten
       if "newservice.com" in content:
           return None
       
       # Check if link exists
       if "originalservice.com" not in content:
           return None
       
       # Perform replacement
       new_content = re.sub(r"pattern", r"replacement", content)
       
       if new_content == content:
           return None
       
       # Build result
       return {
           "new_text": new_content,
           "original_url": original_link,
           "view": build_link_button(original_link, "Open in Original"),
           "delete_original": True
       }
   ```

2. Add the handler to `get_handlers()`:
   ```python
   def get_handlers() -> List[Callable]:
       return [
           handle_twitter,
           handle_reddit,
           handle_tiktok,
           handle_newplatform,  # Add here
       ]
   ```

## Troubleshooting

**Bot doesn't delete original messages:**
- Check that bot has "Manage Messages" permission
- Ensure bot role is higher than the message author's role

**Attachments not preserved:**
- Verify bot has "Attach Files" permission
- Check file size limits (Discord max is 25MB for most servers)
