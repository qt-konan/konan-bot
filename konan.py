import os
import logging
import aiohttp
import asyncio
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.filters.command import CommandObject
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, InputMediaPhoto, Message
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter, TelegramBadRequest
import json
from typing import Dict, List, Optional
import time
import re
import random
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

# Config and constants
load_dotenv()
API_TOKEN = os.getenv("BOT_TOKEN", "your_bot_token_here")
NHENTAI_RANDOM = "https://nhentai.net/random"
NHENTAI_API = "https://nhentai.net/api/gallery/"
NHENTAI_SEARCH = "https://nhentai.net/search/?q="
RESULTS_PER_PAGE = 5
MAX_RETRIES = 3
RATE_LIMIT_DELAY = 2.0
REQUEST_TIMEOUT = 15

# Message dictionaries
MESSAGES = {
    'welcome': f"""🌸 <b>Hey {{user_mention}}! Welcome to Konan!</b>

<i>Your personal guide to endless manga adventures</i> ✨

<blockquote>🎭 Whether you're seeking romance, action, or drama - I'm here to help you discover incredible stories that speak to your soul.

💝 <b>Start your journey:</b>
├─ <code>/random</code> for surprise discoveries
├─ <code>/search</code> to find specific content
└─ <code>/help</code> for the complete guide</blockquote>

🌟 <i>Ready to explore amazing stories?</i>""",

    'help_short': f"""📚 <b>Complete Guide</b>
<i>Hello {{user_mention}}! Here's everything:</i>

🎯 <b>COMMANDS</b>

🎲 <b><code>/random</code></b>
├─ Get instant random content
└─ Perfect for discovery

🔢 <b><code>/id &lt;number&gt;</code></b>
├─ Direct access by ID
└─ Example: <code>/id 123456</code>

🔍 <b><code>/search &lt;keywords&gt;</code></b>
├─ Find specific content
├─ <code>/search vanilla</code>
├─ <code>/search english</code>
└─ <code>/search artist:name</code>

✨ <b>Ready to explore?</b>
<i>Try any command above!</i>""",

    'help_full': f"""📚 <b>Complete Guide</b>
<i>Hello {{user_mention}}! Here's everything:</i>

🎯 <b>COMMANDS</b>

🎲 <b><code>/random</code></b>
├─ Get instant random content
└─ Perfect for discovery

🔢 <b><code>/id &lt;number&gt;</code></b>
├─ Direct access by ID
└─ Example: <code>/id 123456</code>

🔍 <b><code>/search &lt;keywords&gt;</code></b>
├─ Find specific content
├─ <code>/search vanilla</code>
├─ <code>/search english</code>
└─ <code>/search artist:name</code>

🎮 <b>NAVIGATION</b>

📖 <b>Reading Mode:</b>
├─ Click <code>📖</code> to start
├─ ⬅️➡️ Previous/Next page
├─ ⬅️10 / 10➡️ Jump 10 pages
└─ ⏪⏩ First/Last page

📚 <b>Chapter Navigation:</b>
├─ Same controls for chapters
└─ Seamless reading

🔍 <b>Search Results:</b>
├─ Browse unlimited results
└─ Intuitive button controls

💡 <b>PRO TIPS</b>

🎯 <b>Search Better:</b>
├─ Use specific tags
├─ Combine keywords
├─ Try: english, japanese
└─ Try: vanilla, romance

🚀 <b>Navigate Faster:</b>
├─ Bookmark interesting IDs
├─ Use 10-page jumps
└─ Touch-friendly buttons

✨ <b>Ready to explore?</b>
<i>Try any command above!</i>""",

    'search_prompt': f"""🔍 <b>What would you like to find?</b>

💡 <i>Just tell me what you're looking for:</i>
├─ <code>/search vanilla</code>
├─ <code>/search romance</code>
└─ <code>/search english</code>""",

    'id_prompt': f"""🔢 <b>Need an ID to get started!</b>

💡 <i>Just add the number after the command:</i>
<code>/id 123456</code>""",

    'random_search': "🎲 Finding a random doujin...",
    'id_fetch': "🔍 Fetching doujin {doujin_id}...",
    'search_working': "🔍 Searching for: <b>{query}</b>...",
    'doujin_missing': f"""🌙 <b>Oops! That story seems to be missing...</b>

<i>ID {{doujin_id}} isn't available right now. Try another adventure!</i>""",
    'random_retry': f"""🎲 <b>Let's try another roll!</b>

<i>That one didn't work out, but there are thousands more waiting to be discovered!</i>""",
    'magic_failed': f"""🌟 <b>The magic didn't work this time...</b>

<i>Let's give it another try! Sometimes the best discoveries take a moment to find.</i>""",
    'no_results': "❌ No results found for: <b>{query}</b>",
    'search_tip': f"""💡 To search, use longer terms like:
<code>hinata hyuga</code>
<code>english vanilla</code>
Or use /help for all commands."""
}

# Image lists
WELCOME_IMAGES = [
    "https://files.catbox.moe/kas0r4.png",
    "https://files.catbox.moe/ml47fn.png",
    "https://files.catbox.moe/0492u7.png",
    "https://files.catbox.moe/411ks8.png",
    "https://files.catbox.moe/oihku5.png",
    "https://files.catbox.moe/6w3pjs.png",
    "https://files.catbox.moe/zab0e6.png",
    "https://files.catbox.moe/5badpd.png",
    "https://files.catbox.moe/dzg683.png",
    "https://files.catbox.moe/2am6s9.png",
    "https://files.catbox.moe/a3hddu.png",
    "https://files.catbox.moe/268cjb.png",
    "https://files.catbox.moe/jbvcq4.png",
    "https://files.catbox.moe/3aahua.png",
    "https://files.catbox.moe/qb4mx1.png",
    "https://files.catbox.moe/besatg.png",
    "https://files.catbox.moe/wrzmuw.png",
    "https://files.catbox.moe/rr7lej.png",
    "https://files.catbox.moe/7qf6mz.png",
    "https://files.catbox.moe/wj1id4.png",
    "https://files.catbox.moe/cx2lvu.png",
    "https://files.catbox.moe/0q2yaa.png",
    "https://files.catbox.moe/7wjc94.png",
    "https://files.catbox.moe/9tw25m.png",
    "https://files.catbox.moe/5uokng.png",
    "https://files.catbox.moe/7ye2sk.png",
    "https://files.catbox.moe/w9y650.png",
    "https://files.catbox.moe/4gcmuh.png",
    "https://files.catbox.moe/j9c5dy.png",
    "https://files.catbox.moe/zzgdib.png",
    "https://files.catbox.moe/f98a9f.png",
    "https://files.catbox.moe/p61aq2.png",
    "https://files.catbox.moe/9qkaov.png",
    "https://files.catbox.moe/8tvtjm.png",
    "https://files.catbox.moe/hd9105.png",
    "https://files.catbox.moe/jycqms.png",
    "https://files.catbox.moe/gtqmw9.png",
    "https://files.catbox.moe/v79vcg.png",
    "https://files.catbox.moe/kl5xbq.png",
    "https://files.catbox.moe/6vr4vw.png"
]

USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
]

# Bot setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

# Session storage
user_sessions: Dict[int, Dict] = {}

# Rate limiter
class RateLimiter:
    def __init__(self, delay: float = RATE_LIMIT_DELAY):
        self.delay = delay
        self.last_request = {}
    
    async def wait_if_needed(self, user_id: int):
        current_time = time.time()
        if user_id in self.last_request:
            time_passed = current_time - self.last_request[user_id]
            if time_passed < self.delay:
                sleep_time = self.delay - time_passed
                logger.info(f"Rate limiting user {user_id}, waiting {sleep_time:.2f}s")
                await asyncio.sleep(sleep_time)
        self.last_request[user_id] = time.time()

rate_limiter = RateLimiter()

# Helper functions
def get_user_agent():
    return random.choice(USER_AGENTS)

async def create_session() -> aiohttp.ClientSession:
    headers = {
        'User-Agent': get_user_agent(),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Accept-Encoding': 'gzip, deflate',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
    }
    
    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT, connect=10)
    connector = aiohttp.TCPConnector(limit=10, limit_per_host=5)
    
    return aiohttp.ClientSession(
        timeout=timeout,
        headers=headers,
        connector=connector
    )

async def make_request_with_retry(url: str, retries: int = MAX_RETRIES) -> Optional[aiohttp.ClientResponse]:
    for attempt in range(retries):
        try:
            async with await create_session() as session:
                logger.info(f"Making request to {url} (attempt {attempt + 1})")
                async with session.get(url, allow_redirects=False) as resp:
                    logger.info(f"Response status: {resp.status} for {url}")
                    return resp
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            logger.warning(f"Request attempt {attempt + 1} failed for {url}: {e}")
            if attempt < retries - 1:
                await asyncio.sleep(2 ** attempt)
            else:
                logger.error(f"All retry attempts failed for {url}")
        except Exception as e:
            logger.error(f"Unexpected error in request to {url}: {e}")
            if attempt < retries - 1:
                await asyncio.sleep(2 ** attempt)
    return None

async def get_page_content(url: str) -> Optional[str]:
    try:
        async with await create_session() as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    return await resp.text()
                else:
                    logger.warning(f"Failed to get page content: {resp.status}")
    except Exception as e:
        logger.error(f"Error getting page content from {url}: {e}")
    return None

async def get_random_doujin_id() -> Optional[str]:
    try:
        async with await create_session() as session:
            async with session.get(NHENTAI_RANDOM, allow_redirects=False) as resp:
                logger.info(f"Random request status: {resp.status}")
                if resp.status in [301, 302]:
                    location = resp.headers.get("Location", "")
                    logger.info(f"Redirect location: {location}")
                    match = re.search(r'/g/(\d+)/?', location)
                    if match:
                        doujin_id = match.group(1)
                        logger.info(f"Extracted doujin ID: {doujin_id}")
                        return doujin_id
                    else:
                        logger.warning(f"Could not extract ID from location: {location}")
                elif resp.status == 200:
                    content = await resp.text()
                    match = re.search(r'/g/(\d+)/?', content)
                    if match:
                        doujin_id = match.group(1)
                        logger.info(f"Extracted doujin ID from content: {doujin_id}")
                        return doujin_id
                else:
                    logger.warning(f"Unexpected status code for random: {resp.status}")
                    try:
                        content = await resp.text()
                        logger.warning(f"Response content: {content[:200]}")
                    except:
                        pass
    except Exception as e:
        logger.error(f"Error getting random doujin: {e}")
    
    # Fallback random ID
    logger.info("Trying fallback method for random doujin")
    try:
        random_id = str(random.randint(100000, 400000))
        logger.info(f"Generated fallback random ID: {random_id}")
        return random_id
    except Exception as e:
        logger.error(f"Fallback method also failed: {e}")
    
    return None

async def get_doujin_by_id(doujin_id: str) -> Optional[dict]:
    for attempt in range(MAX_RETRIES):
        try:
            api_url = f"{NHENTAI_API}{doujin_id}"
            logger.info(f"Fetching doujin data from: {api_url} (attempt {attempt + 1})")
            
            async with await create_session() as session:
                async with session.get(api_url) as resp:
                    logger.info(f"API response status: {resp.status}")
                    if resp.status == 200:
                        data = await resp.json()
                        logger.info(f"Successfully fetched doujin {doujin_id}")
                        return data
                    elif resp.status == 404:
                        logger.info(f"Doujin {doujin_id} not found")
                        return None
                    elif resp.status == 429:
                        wait_time = 2 ** attempt
                        logger.warning(f"Rate limited, waiting {wait_time}s before retry")
                        await asyncio.sleep(wait_time)
                        continue
                    else:
                        logger.warning(f"API request failed with status {resp.status}")
                        try:
                            error_text = await resp.text()
                            logger.warning(f"Error response: {error_text[:200]}")
                        except:
                            pass
                        
                        if attempt < MAX_RETRIES - 1:
                            await asyncio.sleep(2 ** attempt)
                            continue
                            
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            logger.warning(f"Network error fetching doujin {doujin_id} (attempt {attempt + 1}): {e}")
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(2 ** attempt)
                continue
        except Exception as e:
            logger.error(f"Unexpected error fetching doujin {doujin_id}: {e}")
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(2 ** attempt)
                continue
    
    logger.error(f"Failed to fetch doujin {doujin_id} after {MAX_RETRIES} attempts")
    return None

async def search_nhentai(query: str, max_pages: int = 5) -> List[str]:
    all_doujin_ids = []
    
    try:
        for page in range(1, max_pages + 1):
            url = f"{NHENTAI_SEARCH}{query.replace(' ', '+')}&page={page}"
            logger.info(f"Searching page {page} with URL: {url}")
            
            content = await get_page_content(url)
            if not content:
                logger.warning(f"Failed to get search page {page} content")
                break
            
            soup = BeautifulSoup(content, "html.parser")
            
            if "No results found" in content or not soup.select("a[href*='/g/']"):
                logger.info(f"No more results found on page {page}")
                break
            
            selectors = [
                "a.gallery",
                "a[href*='/g/']",
                ".gallery a",
                ".container a[href*='/g/']"
            ]
            
            page_doujin_ids = []
            for selector in selectors:
                links = soup.select(selector)
                logger.info(f"Page {page}: Found {len(links)} links with selector: {selector}")
                
                for link in links:
                    href_attr = link.get("href")
                    if href_attr:
                        match = re.search(r'/g/(\d+)/?', str(href_attr))
                        if match:
                            doujin_id = match.group(1)
                            if doujin_id not in page_doujin_ids and doujin_id not in all_doujin_ids:
                                page_doujin_ids.append(doujin_id)
                
                if page_doujin_ids:
                    break
            
            if not page_doujin_ids:
                logger.info(f"No new results on page {page}, stopping search")
                break
                
            all_doujin_ids.extend(page_doujin_ids)
            logger.info(f"Page {page}: Added {len(page_doujin_ids)} new doujin IDs")
            
            if page < max_pages:
                await asyncio.sleep(0.5)
        
        logger.info(f"Found {len(all_doujin_ids)} total doujin IDs for query: {query}")
        
        doujin_ids_sorted = sorted(all_doujin_ids, key=lambda x: int(x))
        logger.info(f"Sorted {len(doujin_ids_sorted)} doujin IDs from earliest to latest")
        logger.info(f"First 10 doujin IDs: {doujin_ids_sorted[:10]}")
        
        logger.info(f"Returning {len(doujin_ids_sorted)} chronologically sorted results")
        return doujin_ids_sorted
        
    except Exception as e:
        logger.error(f"Error searching nhentai: {e}")
    return []

def create_doujin_markup(doujin_id: str, show_navigation: bool = False, 
                        current_page: int = 0, total_pages: int = 1, 
                        search_query: str = "", page_mode: bool = False,
                        manga_current_page: int = 1, manga_total_pages: int = 1,
                        search_results: Optional[List[str]] = None, search_index: int = -1) -> InlineKeyboardMarkup:
    buttons = []
    
    if page_mode:
        # First row: Jump navigation
        first_row = []
        
        if manga_current_page > 1:
            first_row.append(InlineKeyboardButton(
                text="⏪",
                callback_data=f"page:first:{doujin_id}:{manga_current_page}"
            ))
        
        if manga_current_page > 10:
            first_row.append(InlineKeyboardButton(
                text="⬅️10",
                callback_data=f"page:prev10:{doujin_id}:{manga_current_page}"
            ))
        
        if manga_current_page + 10 <= manga_total_pages:
            first_row.append(InlineKeyboardButton(
                text="10➡️",
                callback_data=f"page:next10:{doujin_id}:{manga_current_page}"
            ))
        
        if manga_current_page < manga_total_pages:
            first_row.append(InlineKeyboardButton(
                text="⏩",
                callback_data=f"page:last:{doujin_id}:{manga_current_page}"
            ))
        
        if first_row:
            buttons.append(first_row)
            
        # Second row: Single page navigation
        second_row = []
        
        if manga_current_page > 1:
            second_row.append(InlineKeyboardButton(
                text="⬅️",
                callback_data=f"page:prev:{doujin_id}:{manga_current_page}"
            ))
        
        if manga_current_page < manga_total_pages:
            second_row.append(InlineKeyboardButton(
                text="➡️",
                callback_data=f"page:next:{doujin_id}:{manga_current_page}"
            ))
        
        if second_row:
            buttons.append(second_row)

        # Chapter navigation if available
        if search_results and search_index >= 0:
            chapter_row_1 = []
            
            if search_index > 0:
                first_chapter_id = search_results[0]
                chapter_row_1.append(InlineKeyboardButton(
                    text="⏪",
                    callback_data=f"next_chapter:{first_chapter_id}:0"
                ))
            
            if search_index >= 10:
                prev_10_index = max(0, search_index - 10)
                prev_10_chapter_id = search_results[prev_10_index]
                chapter_row_1.append(InlineKeyboardButton(
                    text="⬅️10",
                    callback_data=f"next_chapter:{prev_10_chapter_id}:{prev_10_index}"
                ))
            
            if search_index + 10 < len(search_results):
                next_10_index = min(len(search_results) - 1, search_index + 10)
                next_10_chapter_id = search_results[next_10_index]
                chapter_row_1.append(InlineKeyboardButton(
                    text="10➡️",
                    callback_data=f"next_chapter:{next_10_chapter_id}:{next_10_index}"
                ))
            
            if search_index < len(search_results) - 1:
                last_chapter_id = search_results[-1]
                chapter_row_1.append(InlineKeyboardButton(
                    text="⏩",
                    callback_data=f"next_chapter:{last_chapter_id}:{len(search_results) - 1}"
                ))
            
            if chapter_row_1:
                buttons.append(chapter_row_1)
                
            chapter_row_2 = []
            
            if search_index > 0:
                prev_chapter_id = search_results[search_index - 1]
                chapter_row_2.append(InlineKeyboardButton(
                    text="⬅️",
                    callback_data=f"next_chapter:{prev_chapter_id}:{search_index - 1}"
                ))
            
            if search_index < len(search_results) - 1:
                next_chapter_id = search_results[search_index + 1]
                chapter_row_2.append(InlineKeyboardButton(
                    text="➡️",
                    callback_data=f"next_chapter:{next_chapter_id}:{search_index + 1}"
                ))
            
            if chapter_row_2:
                buttons.append(chapter_row_2)
                
            if search_results:
                buttons.append([
                    InlineKeyboardButton(
                        text="🔍",
                        callback_data="back_to_search_page"
                    )
                ])
    else:
        # Info mode
        buttons.append([
            InlineKeyboardButton(
                text="📖",
                callback_data=f"read:{doujin_id}:1"
            )
        ])

        # Navigation buttons for search
        if show_navigation and total_pages > 1:
            first_row = []
            
            if current_page > 0:
                first_row.append(InlineKeyboardButton(
                    text="⏪",
                    callback_data=f"nav:first:{current_page}:{search_query}"
                ))
            
            if current_page >= 10:
                first_row.append(InlineKeyboardButton(
                    text="⬅️10",
                    callback_data=f"nav:prev10:{current_page}:{search_query}"
                ))
            
            if current_page + 10 < total_pages:
                first_row.append(InlineKeyboardButton(
                    text="10➡️",
                    callback_data=f"nav:next10:{current_page}:{search_query}"
                ))
            
            if current_page < total_pages - 1:
                first_row.append(InlineKeyboardButton(
                    text="⏩",
                    callback_data=f"nav:last:{current_page}:{search_query}"
                ))
            
            if first_row:
                buttons.append(first_row)
            
            second_row = []
            
            if current_page > 0:
                second_row.append(InlineKeyboardButton(
                    text="⬅️",
                    callback_data=f"nav:prev:{current_page}:{search_query}"
                ))
            
            second_row.append(InlineKeyboardButton(
                text=f"{current_page + 1}/{total_pages}",
                callback_data="nav:page_info"
            ))
            
            if current_page < total_pages - 1:
                second_row.append(InlineKeyboardButton(
                    text="➡️",
                    callback_data=f"nav:next:{current_page}:{search_query}"
                ))
            
            if second_row:
                buttons.append(second_row)
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def format_doujin_info(data: dict) -> str:
    if not data:
        return "❌ Error: Invalid doujin data"
    
    try:
        title_obj = data.get("title", {})
        title = (title_obj.get("english") or 
                title_obj.get("japanese") or 
                title_obj.get("pretty") or 
                "No Title Available")
        
        all_tags = data.get("tags", [])
        tags = [tag.get("name", "") for tag in all_tags if tag.get("type") == "tag"]
        artists = [tag.get("name", "") for tag in all_tags if tag.get("type") == "artist"]
        languages = [tag.get("name", "") for tag in all_tags if tag.get("type") == "language"]
        categories = [tag.get("name", "") for tag in all_tags if tag.get("type") == "category"]
        
        pages = data.get("num_pages", 0)
        doujin_id = data.get("id", "Unknown")
        
        def format_tag_list(tag_list, limit=6):
            if not tag_list:
                return "None"
            display_tags = [tag for tag in tag_list if tag][:limit]
            result = ", ".join(display_tags)
            if len(tag_list) > limit:
                result += f" (+{len(tag_list) - limit} more)"
            return result
        
        if len(title) > 80:
            title = title[:77] + "..."
        
        text_parts = [
            f"<b>{title}</b>",
            "",
            f"🆔 <b>ID:</b> {doujin_id}",
            f"📄 <b>Pages:</b> {pages}"
        ]
        
        if artists:
            text_parts.append(f"👨‍🎨 <b>Artist(s):</b> {format_tag_list(artists, 3)}")
        
        if categories:
            text_parts.append(f"📂 <b>Category:</b> {format_tag_list(categories, 2)}")
        
        if languages:
            text_parts.append(f"🌐 <b>Language(s):</b> {format_tag_list(languages, 3)}")
        
        if tags:
            text_parts.append(f"🏷 <b>Tags:</b> {format_tag_list(tags, 8)}")
        
        return "\n".join(text_parts)
        
    except Exception as e:
        logger.error(f"Error formatting doujin info: {e}")
        return "❌ Error formatting doujin information"

def get_cover_image_url(data: dict) -> Optional[str]:
    try:
        media_id = data.get("media_id")
        if not media_id:
            return None
        
        images = data.get("images", {})
        cover_info = images.get("cover", {})
        
        ext_map = {"j": "jpg", "p": "png", "g": "gif"}
        ext = ext_map.get(cover_info.get("t"), "jpg")
        
        possible_urls = [
            f"https://t.nhentai.net/galleries/{media_id}/cover.{ext}",
            f"https://t.nhentai.net/galleries/{media_id}/thumb.{ext}",
            f"https://i.nhentai.net/galleries/{media_id}/cover.{ext}"
        ]
        
        return possible_urls[0]
        
    except Exception as e:
        logger.error(f"Error getting cover image URL: {e}")
        return None

def get_page_image_url(data: dict, page_num: int) -> Optional[str]:
    try:
        media_id = data.get("media_id")
        if not media_id:
            return None
        
        images = data.get("images", {})
        pages = images.get("pages", [])
        
        if page_num < 1 or page_num > len(pages):
            return None
            
        page_info = pages[page_num - 1]
        
        ext_map = {"j": "jpg", "p": "png", "g": "gif"}
        ext = ext_map.get(page_info.get("t"), "jpg")
        
        possible_urls = [
            f"https://i.nhentai.net/galleries/{media_id}/{page_num}.{ext}",
            f"https://t.nhentai.net/galleries/{media_id}/{page_num}.{ext}",
            f"https://i.doujins.com/galleries/{media_id}/{page_num}.{ext}"
        ]
        
        logger.info(f"Generated page URL for doujin {data.get('id', 'unknown')}, media_id {media_id}, page {page_num}: {possible_urls[0]}")
        return possible_urls[0]
        
    except Exception as e:
        logger.error(f"Error getting page image URL: {e}")
        return None

async def edit_doujin_info(message, doujin_id: str, show_navigation: bool = False,
                          current_page: int = 0, total_pages: int = 1, 
                          search_query: str = "") -> bool:
    try:
        data = await get_doujin_by_id(doujin_id)
        if not data:
            return False
        
        caption = format_doujin_info(data)
        markup = create_doujin_markup(doujin_id, show_navigation, current_page, total_pages, search_query)
        
        cover_url = get_cover_image_url(data)
        if cover_url:
            try:
                await message.edit_media(
                    InputMediaPhoto(media=cover_url, caption=caption),
                    reply_markup=markup
                )
                return True
            except TelegramBadRequest as e:
                if "message is not modified" in str(e).lower():
                    return True
                logger.warning(f"Failed to edit with image: {e}")
                try:
                    await message.edit_text(
                        text=f"🖼 <i>Image unavailable</i>\n\n{caption}",
                        reply_markup=markup
                    )
                    return True
                except TelegramBadRequest:
                    return False
        else:
            try:
                await message.edit_text(
                    text=f"🖼 <i>Image unavailable</i>\n\n{caption}",
                    reply_markup=markup
                )
                return True
            except TelegramBadRequest:
                return False
    except Exception as e:
        logger.error(f"Error editing doujin info: {e}")
        return False

async def send_doujin_info(chat_id: int, doujin_id: str, show_navigation: bool = False,
                          current_page: int = 0, total_pages: int = 1, 
                          search_query: str = "", reply_to_message: types.Message = None) -> bool:
    try:
        logger.info(f"Sending doujin info for ID: {doujin_id}")
        data = await get_doujin_by_id(doujin_id)
        if not data:
            await bot.send_message(chat_id, MESSAGES['doujin_missing'].format(doujin_id=doujin_id))
            return False
        
        caption = format_doujin_info(data)
        markup = create_doujin_markup(doujin_id, show_navigation, current_page, total_pages, search_query)
        
        cover_url = get_cover_image_url(data)
        if cover_url:
            try:
                if reply_to_message and reply_to_message.chat.type != "private":
                    await reply_to_message.reply_photo(
                        photo=cover_url,
                        caption=caption,
                        reply_markup=markup
                    )
                else:
                    await bot.send_photo(
                        chat_id=chat_id,
                        photo=cover_url,
                        caption=caption,
                        reply_markup=markup
                    )
                logger.info(f"Successfully sent doujin {doujin_id} with image")
                return True
            except (TelegramAPIError, TelegramBadRequest) as e:
                logger.warning(f"Failed to send with image, sending text only: {e}")
                if reply_to_message and reply_to_message.chat.type != "private":
                    await reply_to_message.reply(
                        text=f"🖼 <i>Image unavailable</i>\n\n{caption}",
                        reply_markup=markup
                    )
                else:
                    await bot.send_message(
                        chat_id=chat_id,
                        text=f"🖼 <i>Image unavailable</i>\n\n{caption}",
                        reply_markup=markup
                    )
                return True
        else:
            if reply_to_message and reply_to_message.chat.type != "private":
                await reply_to_message.reply(
                    text=caption,
                    reply_markup=markup
                )
            else:
                await bot.send_message(
                    chat_id=chat_id,
                    text=caption,
                    reply_markup=markup
                )
            return True
        
    except TelegramRetryAfter as e:
        logger.warning(f"Rate limited, waiting {e.retry_after} seconds")
        await asyncio.sleep(e.retry_after)
        return False
    except TelegramAPIError as e:
        logger.error(f"Telegram API error: {e}")
        await bot.send_message(chat_id, "❌ Error sending doujin information. Please try again.")
        return False
    except Exception as e:
        logger.error(f"Unexpected error sending doujin info: {e}")
        await bot.send_message(chat_id, "❌ An unexpected error occurred. Please try again.")
        return False

def get_user_session(user_id: int) -> dict:
    if user_id not in user_sessions:
        user_sessions[user_id] = {
            'current_search': '',
            'search_results': [],
            'current_page': 0,
            'reading_chapter_index': -1
        }
    return user_sessions[user_id]

async def send_message(message: types.Message, text: str, **kwargs):
    if message.chat.type == "private":
        return await message.answer(text, **kwargs)
    else:
        return await message.reply(text, **kwargs)

# Command handlers
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    try:
        user_name = message.from_user.first_name or "User"
        user_mention = f'<a href="tg://user?id={message.from_user.id}">{user_name}</a>'

        welcome_text = MESSAGES['welcome'].format(user_mention=user_mention)

        welcome_buttons = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="Updates", url="https://t.me/WorkGlows"),
                InlineKeyboardButton(text="Support", url="https://t.me/SoulMeetsHQ")
            ],
            [
                InlineKeyboardButton(
                    text="Add Me To Your Group",
                    url=f"https://t.me/{(await bot.get_me()).username}?startgroup=true"
                )
            ]
        ])

        selected_image = random.choice(WELCOME_IMAGES)

        await message.answer_photo(
            photo=selected_image,
            caption=welcome_text,
            parse_mode="HTML",
            reply_markup=welcome_buttons
        )

    except Exception as e:
        logger.error(f"Error in start command: {e}")
        await send_message(message, "❌ An error occurred. Please try again.")

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    try:
        user_name = message.from_user.first_name or "User"
        user_mention = f'<a href="tg://user?id={message.from_user.id}">{user_name}</a>'
        
        # Inline button with expand/minimize
        help_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📖 Expand Guide", callback_data="help_expand")]
        ])
        
        help_text = MESSAGES['help_short'].format(user_mention=user_mention)
        await send_message(message, help_text, reply_markup=help_keyboard)
    except Exception as e:
        logger.error(f"Error in help command: {e}")
        await send_message(message, "❌ An error occurred. Please try again.")

@dp.callback_query(F.data == "help_expand")
async def help_expand(callback: CallbackQuery):
    try:
        user_name = callback.from_user.first_name or "User"
        user_mention = f'<a href="tg://user?id={callback.from_user.id}">{user_name}</a>'
        
        help_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📚 Minimize Guide", callback_data="help_minimize")]
        ])
        
        help_text = MESSAGES['help_full'].format(user_mention=user_mention)
        await callback.message.edit_text(help_text, reply_markup=help_keyboard)
        await callback.answer("Expanded guide")
    except Exception as e:
        logger.error(f"Error in help expand: {e}")
        await callback.answer("❌ Error expanding guide")

@dp.callback_query(F.data == "help_minimize")
async def help_minimize(callback: CallbackQuery):
    try:
        user_name = callback.from_user.first_name or "User"
        user_mention = f'<a href="tg://user?id={callback.from_user.id}">{user_name}</a>'
        
        help_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📖 Expand Guide", callback_data="help_expand")]
        ])
        
        help_text = MESSAGES['help_short'].format(user_mention=user_mention)
        await callback.message.edit_text(help_text, reply_markup=help_keyboard)
        await callback.answer("Minimized guide")
    except Exception as e:
        logger.error(f"Error in help minimize: {e}")
        await callback.answer("❌ Error minimizing guide")

@dp.message(Command("random"))
async def cmd_random(message: types.Message):
    user_id = message.from_user.id
    try:
        await rate_limiter.wait_if_needed(user_id)
        
        status_msg = await send_message(message, MESSAGES['random_search'])
        
        doujin_id = await get_random_doujin_id()
        if doujin_id:
            await status_msg.delete()
            success = await send_doujin_info(message.chat.id, doujin_id, reply_to_message=message)
            if not success:
                await send_message(message, MESSAGES['random_retry'])
        else:
            await status_msg.edit_text(MESSAGES['magic_failed'])
    except Exception as e:
        logger.error(f"Error in random command: {e}")
        await send_message(message, "❌ An error occurred. Please try again.")

@dp.message(Command("id"))
async def cmd_id(message: types.Message, command: CommandObject):
    user_id = message.from_user.id
    try:
        await rate_limiter.wait_if_needed(user_id)
        
        if not command.args:
            await send_message(message, MESSAGES['id_prompt'])
            return
        
        doujin_id = command.args.strip()
        if not doujin_id.isdigit():
            await send_message(message, "❌ Please provide a valid numeric ID.\nExample: <code>/id 123456</code>")
            return
        
        status_msg = await send_message(message, MESSAGES['id_fetch'].format(doujin_id=doujin_id))
        
        success = await send_doujin_info(message.chat.id, doujin_id, reply_to_message=message)
        await status_msg.delete()
        
        if not success:
            await send_message(message, f"❌ Doujin {doujin_id} not found or unavailable.")
    except Exception as e:
        logger.error(f"Error in id command: {e}")
        await send_message(message, "❌ An error occurred. Please try again.")

@dp.message(Command("search"))
async def cmd_search(message: types.Message, command: CommandObject):
    user_id = message.from_user.id
    try:
        await rate_limiter.wait_if_needed(user_id)
        
        if not command.args:
            await send_message(message, MESSAGES['search_prompt'])
            return
        
        query = command.args.strip()
        if len(query) < 2:
            await send_message(message, "❌ Search query must be at least 2 characters long.")
            return
        
        status_msg = await send_message(message, MESSAGES['search_working'].format(query=query))
        
        doujin_ids = await search_nhentai(query)
        if not doujin_ids:
            await status_msg.edit_text(MESSAGES['no_results'].format(query=query))
            return
        
        session = get_user_session(user_id)
        session['current_search'] = query
        session['search_results'] = doujin_ids
        session['current_page'] = 0
        
        await status_msg.delete()
        
        total_pages = len(doujin_ids)
        first_doujin_id = doujin_ids[0]
        
        await send_doujin_info(
            message.chat.id, 
            first_doujin_id, 
            show_navigation=True,
            current_page=0, 
            total_pages=total_pages, 
            search_query=query,
            reply_to_message=message
        )
        
    except Exception as e:
        logger.error(f"Error in search command: {e}")
        await send_message(message, "❌ An error occurred during search. Please try again.")

@dp.message(F.text & ~F.text.startswith("/") & F.chat.type == "private")
async def handle_text_search(message: types.Message):
    user_id = message.from_user.id
    try:
        await rate_limiter.wait_if_needed(user_id)
        
        query = message.text.strip()
        if len(query) < 2:
            await send_message(message, "❌ Search query must be at least 2 characters long.")
            return
        
        if len(query) == 1 or query.lower() in ['hi', 'hey', 'ok', 'yes', 'no']:
            await send_message(message, MESSAGES['search_tip'])
            return
        
        status_msg = await send_message(message, MESSAGES['search_working'].format(query=query))
        
        doujin_ids = await search_nhentai(query)
        if not doujin_ids:
            await status_msg.edit_text(MESSAGES['no_results'].format(query=query))
            return
        
        session = get_user_session(user_id)
        session['current_search'] = query
        session['search_results'] = doujin_ids
        session['current_page'] = 0
        
        await status_msg.delete()
        
        total_pages = len(doujin_ids)
        first_doujin_id = doujin_ids[0]
        
        await send_doujin_info(
            message.chat.id, 
            first_doujin_id, 
            show_navigation=True,
            current_page=0, 
            total_pages=total_pages, 
            search_query=query,
            reply_to_message=message
        )
        
    except Exception as e:
        logger.error(f"Error in text search: {e}")
        await send_message(message, "❌ An error occurred during search. Please try again.")

# Callback handlers
@dp.callback_query(F.data.startswith("nav:"))
async def handle_navigation(callback: CallbackQuery):
    user_id = callback.from_user.id
    try:
        await rate_limiter.wait_if_needed(user_id)
        
        data_parts = callback.data.split(":")
        action = data_parts[1]
        
        if action == "page_info":
            await callback.answer("Page information")
            return
        
        current_page = int(data_parts[2])
        search_query = data_parts[3] if len(data_parts) > 3 else ""
        
        session = get_user_session(user_id)
        search_results = session.get('search_results', [])
        
        if not search_results:
            await callback.answer("❌ No search results available")
            return
        
        if action == "prev":
            new_page = max(0, current_page - 1)
        elif action == "next":
            new_page = min(len(search_results) - 1, current_page + 1)
        elif action == "first":
            new_page = 0
        elif action == "last":
            new_page = len(search_results) - 1
        elif action == "prev10":
            new_page = max(0, current_page - 10)
        elif action == "next10":
            new_page = min(len(search_results) - 1, current_page + 10)
        else:
            await callback.answer("❌ Invalid navigation action")
            return
        
        if new_page == current_page:
            await callback.answer("Already at the boundary")
            return
        
        session['current_page'] = new_page
        
        doujin_id = search_results[new_page]
        total_pages = len(search_results)
        
        data = await get_doujin_by_id(doujin_id)
        if not data:
            await callback.answer("❌ Failed to load doujin")
            return
        
        caption = format_doujin_info(data)
        markup = create_doujin_markup(doujin_id, True, new_page, total_pages, search_query)
        
        cover_url = get_cover_image_url(data)
        try:
            if cover_url and callback.message.photo:
                await callback.message.edit_media(
                    InputMediaPhoto(media=cover_url, caption=caption),
                    reply_markup=markup
                )
            elif cover_url and not callback.message.photo:
                await callback.message.edit_media(
                    InputMediaPhoto(media=cover_url, caption=caption),
                    reply_markup=markup
                )
            else:
                await callback.message.edit_text(
                    text=caption,
                    reply_markup=markup
                )
            
            await callback.answer(f"Showing result {new_page + 1} of {len(search_results)}")
            
        except TelegramBadRequest as e:
            if "message is not modified" in str(e).lower():
                await callback.answer("Already showing this result")
            else:
                logger.error(f"Error editing message: {e}")
                await callback.answer("❌ Error updating content")
        
    except Exception as e:
        logger.error(f"Error in navigation handler: {e}")
        await callback.answer("❌ Navigation error occurred")

@dp.callback_query(F.data.startswith("read:"))
async def handle_read(callback: CallbackQuery):
    user_id = callback.from_user.id
    try:
        await rate_limiter.wait_if_needed(user_id)
        
        data_parts = callback.data.split(":")
        doujin_id = data_parts[1]
        page_num = int(data_parts[2]) if len(data_parts) > 2 else 1
        
        data = await get_doujin_by_id(doujin_id)
        if not data:
            await callback.answer("❌ Failed to load doujin")
            return
        
        total_pages = data.get("num_pages", 1)
        if page_num < 1 or page_num > total_pages:
            page_num = 1
        
        page_url = get_page_image_url(data, page_num)
        if not page_url:
            await callback.answer("❌ Failed to get page image")
            return
        
        session = get_user_session(user_id)
        search_results = session.get('search_results', [])
        search_index = -1
        
        if search_results and doujin_id in search_results:
            search_index = search_results.index(doujin_id)
        
        markup = create_doujin_markup(
            doujin_id=doujin_id,
            page_mode=True,
            manga_current_page=page_num,
            manga_total_pages=total_pages,
            search_results=search_results,
            search_index=search_index
        )
        
        title = data.get("title", {}).get("english") or data.get("title", {}).get("pretty") or f"Doujin {doujin_id}"
        if len(title) > 50:
            title = title[:47] + "..."
        
        caption = f"<b>{title}</b>\nPage {page_num}/{total_pages}"
        
        try:
            await callback.message.edit_media(
                InputMediaPhoto(media=page_url, caption=caption),
                reply_markup=markup
            )
            await callback.answer(f"Reading page {page_num}")
            
        except TelegramBadRequest as e:
            if "message is not modified" in str(e).lower():
                await callback.answer("Already on this page")
            else:
                logger.error(f"Error editing page: {e}")
                await callback.answer("❌ Error loading page")
        except TelegramAPIError as e:
            logger.error(f"Error editing page: {e}")
            await callback.answer("❌ Error loading page")
            
    except Exception as e:
        logger.error(f"Error in read handler: {e}")
        await callback.answer("❌ Read error occurred")

@dp.callback_query(F.data.startswith("page:"))
async def handle_page_navigation(callback: CallbackQuery):
    user_id = callback.from_user.id
    try:
        await rate_limiter.wait_if_needed(user_id)
        
        data_parts = callback.data.split(":")
        action = data_parts[1]
        doujin_id = data_parts[2]
        current_page = int(data_parts[3])
        
        data = await get_doujin_by_id(doujin_id)
        if not data:
            await callback.answer("❌ Failed to load doujin")
            return
        
        total_pages = data.get("num_pages", 1)
        
        if action == "prev":
            new_page = max(1, current_page - 1)
        elif action == "next":
            new_page = min(total_pages, current_page + 1)
        elif action == "first":
            new_page = 1
        elif action == "last":
            new_page = total_pages
        elif action == "prev10":
            new_page = max(1, current_page - 10)
        elif action == "next10":
            new_page = min(total_pages, current_page + 10)
        else:
            await callback.answer("❌ Invalid page action")
            return
        
        if new_page == current_page:
            await callback.answer("Already at the boundary")
            return
        
        page_url = get_page_image_url(data, new_page)
        if not page_url:
            await callback.answer("❌ Failed to get page image")
            return
        
        session = get_user_session(user_id)
        search_results = session.get('search_results', [])
        search_index = -1
        
        if search_results and doujin_id in search_results:
            search_index = search_results.index(doujin_id)
        
        markup = create_doujin_markup(
            doujin_id=doujin_id,
            page_mode=True,
            manga_current_page=new_page,
            manga_total_pages=total_pages,
            search_results=search_results,
            search_index=search_index
        )
        
        title = data.get("title", {}).get("english") or data.get("title", {}).get("pretty") or f"Doujin {doujin_id}"
        if len(title) > 50:
            title = title[:47] + "..."
        
        caption = f"<b>{title}</b>\nPage {new_page}/{total_pages}"
        
        try:
            await callback.message.edit_media(
                InputMediaPhoto(media=page_url, caption=caption),
                reply_markup=markup
            )
            await callback.answer(f"Page {new_page}")
            
        except TelegramBadRequest as e:
            if "message is not modified" in str(e).lower():
                await callback.answer("Already on this page")
            else:
                logger.error(f"Error editing page: {e}")
                await callback.answer("❌ Error loading page")
                
    except Exception as e:
        logger.error(f"Error in page navigation: {e}")
        await callback.answer("❌ Page navigation error")

@dp.callback_query(F.data.startswith("next_chapter:"))
async def handle_chapter_navigation(callback: CallbackQuery):
    user_id = callback.from_user.id
    try:
        await rate_limiter.wait_if_needed(user_id)
        
        data_parts = callback.data.split(":")
        doujin_id = data_parts[1]
        chapter_index = int(data_parts[2])
        
        session = get_user_session(user_id)
        search_results = session.get('search_results', [])
        
        if not search_results or chapter_index < 0 or chapter_index >= len(search_results):
            await callback.answer("❌ Invalid chapter")
            return
        
        session['current_page'] = chapter_index
        session['reading_chapter_index'] = chapter_index
        
        data = await get_doujin_by_id(doujin_id)
        if not data:
            await callback.answer("❌ Failed to load chapter")
            return
        
        total_pages = data.get("num_pages", 1)
        
        page_url = get_page_image_url(data, 1)
        if not page_url:
            await callback.answer("❌ Failed to get chapter image")
            return
        
        markup = create_doujin_markup(
            doujin_id=doujin_id,
            page_mode=True,
            manga_current_page=1,
            manga_total_pages=total_pages,
            search_results=search_results,
            search_index=chapter_index
        )
        
        title = data.get("title", {}).get("english") or data.get("title", {}).get("pretty") or f"Doujin {doujin_id}"
        if len(title) > 50:
            title = title[:47] + "..."
        
        caption = f"<b>{title}</b>\nPage 1/{total_pages}\nChapter {chapter_index + 1}/{len(search_results)}"
        
        try:
            await callback.message.edit_media(
                InputMediaPhoto(media=page_url, caption=caption),
                reply_markup=markup
            )
            await callback.answer(f"Chapter {chapter_index + 1}")
            
        except TelegramBadRequest as e:
            if "message is not modified" in str(e).lower():
                await callback.answer("Already on this chapter")
            else:
                logger.error(f"Error editing chapter: {e}")
                await callback.answer("❌ Error loading chapter")
                
    except Exception as e:
        logger.error(f"Error in chapter navigation: {e}")
        await callback.answer("❌ Chapter navigation error")

@dp.callback_query(F.data.startswith("back_to_search:"))
async def handle_back_to_search(callback: CallbackQuery):
    user_id = callback.from_user.id
    try:
        await rate_limiter.wait_if_needed(user_id)
        
        search_query = callback.data.split(":", 1)[1]
        
        session = get_user_session(user_id)
        search_results = session.get('search_results', [])
        current_page = session.get('current_page', 0)
        
        if not search_results:
            await callback.answer("❌ No search results available")
            return
        
        doujin_id = search_results[current_page]
        total_pages = len(search_results)
        
        success = await edit_doujin_info(
            callback.message,
            doujin_id,
            show_navigation=True,
            current_page=current_page,
            total_pages=total_pages,
            search_query=search_query
        )
        
        if success:
            await callback.answer(f"Back to search: {search_query}")
        else:
            await callback.answer("❌ Failed to load search results")
            
    except Exception as e:
        logger.error(f"Error in back to search: {e}")
        await callback.answer("❌ Error returning to search")

@dp.callback_query(F.data == "back_to_search_page")
async def handle_back_to_search_page(callback: CallbackQuery):
    user_id = callback.from_user.id
    try:
        await rate_limiter.wait_if_needed(user_id)
        
        session = get_user_session(user_id)
        search_results = session.get('search_results', [])
        current_page = session.get('current_page', 0)
        search_query = session.get('current_search', '')
        
        if not search_results or not search_query:
            await callback.answer("❌ No search results available")
            return
        
        doujin_id = search_results[current_page]
        total_pages = len(search_results)
        
        success = await edit_doujin_info(
            callback.message,
            doujin_id,
            show_navigation=True,
            current_page=current_page,
            total_pages=total_pages,
            search_query=search_query
        )
        
        if success:
            await callback.answer("Back to search")
        else:
            await callback.answer("❌ Failed to load search results")
            
    except Exception as e:
        logger.error(f"Error in back to search page: {e}")
        await callback.answer("❌ Error returning to search")

# Dummy HTTP server
class DummyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"AFK bot is alive!")

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

def start_dummy_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), DummyHandler)
    print(f"Dummy server listening on port {port}")
    server.serve_forever()

# Main function
async def main():
    try:
        logger.info("Starting bot...")
        
        from aiogram.types import BotCommand
        commands = [
            BotCommand(command="start", description="🌸 Welcome Home"),
            BotCommand(command="help", description="📚 Complete Guide"),
            BotCommand(command="random", description="🎲 Random Discovery"),
            BotCommand(command="search", description="🔍 Advanced Search"),
            BotCommand(command="id", description="🔢 Direct Access"),
        ]
        await bot.set_my_commands(commands)
        logger.info("Bot commands registered successfully")
        
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Critical error: {e}")
    finally:
        await bot.session.close()

if __name__ == "__main__":
    threading.Thread(target=start_dummy_server, daemon=True).start()
    asyncio.run(main())