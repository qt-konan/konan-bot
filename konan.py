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

# ─── Imports for Dummy HTTP Server ──────────────────────────────────────────
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

# Load environment variables
load_dotenv()
API_TOKEN = os.getenv("BOT_TOKEN", "your_bot_token_here")

# Logging configuration
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Bot initialization
bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

# Constants
NHENTAI_RANDOM = "https://nhentai.net/random"
NHENTAI_API = "https://nhentai.net/api/gallery/"
NHENTAI_SEARCH = "https://nhentai.net/search/?q="
RESULTS_PER_PAGE = 5
MAX_RETRIES = 3
RATE_LIMIT_DELAY = 2.0
REQUEST_TIMEOUT = 15

# Session storage for user states
user_sessions: Dict[int, Dict] = {}

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

def get_user_agent():
    """Get a random user agent to avoid detection"""
    user_agents = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    ]
    return random.choice(user_agents)

async def create_session() -> aiohttp.ClientSession:
    """Create an aiohttp session with proper configuration"""
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
    """Make HTTP request with retry logic and proper error handling"""
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
    """Get page content with proper error handling"""
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
    """Get random doujin ID from nhentai with improved error handling"""
    try:
        async with await create_session() as session:
            async with session.get(NHENTAI_RANDOM, allow_redirects=False) as resp:
                logger.info(f"Random request status: {resp.status}")
                # Handle both 301 and 302 redirects
                if resp.status in [301, 302]:
                    location = resp.headers.get("Location", "")
                    logger.info(f"Redirect location: {location}")
                    # Extract ID from URL like /g/123456/
                    match = re.search(r'/g/(\d+)/?', location)
                    if match:
                        doujin_id = match.group(1)
                        logger.info(f"Extracted doujin ID: {doujin_id}")
                        return doujin_id
                    else:
                        logger.warning(f"Could not extract ID from location: {location}")
                elif resp.status == 200:
                    # Sometimes nhentai returns 200 with direct content
                    content = await resp.text()
                    # Try to extract ID from page content
                    match = re.search(r'/g/(\d+)/?', content)
                    if match:
                        doujin_id = match.group(1)
                        logger.info(f"Extracted doujin ID from content: {doujin_id}")
                        return doujin_id
                else:
                    logger.warning(f"Unexpected status code for random: {resp.status}")
                    # Try to get response text for debugging
                    try:
                        content = await resp.text()
                        logger.warning(f"Response content: {content[:200]}")
                    except:
                        pass
    except Exception as e:
        logger.error(f"Error getting random doujin: {e}")
    
    # Fallback: try getting a random ID from a known range
    logger.info("Trying fallback method for random doujin")
    try:
        # Use a range of known working IDs (this is a fallback)
        random_id = str(random.randint(100000, 400000))
        logger.info(f"Generated fallback random ID: {random_id}")
        return random_id
    except Exception as e:
        logger.error(f"Fallback method also failed: {e}")
    
    return None

async def get_doujin_by_id(doujin_id: str) -> Optional[dict]:
    """Get doujin data by ID from nhentai API with improved error handling"""
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
                        return None  # Don't retry for 404
                    elif resp.status == 429:
                        # Rate limited
                        wait_time = 2 ** attempt
                        logger.warning(f"Rate limited, waiting {wait_time}s before retry")
                        await asyncio.sleep(wait_time)
                        continue
                    else:
                        logger.warning(f"API request failed with status {resp.status}")
                        # Try to get response text for debugging
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
    """Search nhentai and return list of doujin IDs with improved parsing and multi-page support"""
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
            
            # Check if this page has results
            if "No results found" in content or not soup.select("a[href*='/g/']"):
                logger.info(f"No more results found on page {page}")
                break
            
            # Try multiple selectors to find gallery links
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
                        # Extract ID from href like /g/123456/ or /g/123456
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
            
            # Add a small delay between pages to be respectful
            if page < max_pages:
                await asyncio.sleep(0.5)
        
        logger.info(f"Found {len(all_doujin_ids)} total doujin IDs for query: {query}")
        
        # Sort doujin IDs in ascending order to show earliest chapters first
        doujin_ids_sorted = sorted(all_doujin_ids, key=lambda x: int(x))
        logger.info(f"Sorted {len(doujin_ids_sorted)} doujin IDs from earliest to latest")
        logger.info(f"First 10 doujin IDs: {doujin_ids_sorted[:10]}")
        
        # Return all results sorted chronologically - let user choose what they want to read
        # The "chapter progression" issue is actually normal for serialized manga
        logger.info(f"Returning {len(doujin_ids_sorted)} chronologically sorted results")
        return doujin_ids_sorted  # No limit - return all results
        
    except Exception as e:
        logger.error(f"Error searching nhentai: {e}")
    return []

def create_doujin_markup(doujin_id: str, show_navigation: bool = False, 
                        current_page: int = 0, total_pages: int = 1, 
                        search_query: str = "", page_mode: bool = False,
                        manga_current_page: int = 1, manga_total_pages: int = 1,
                        search_results: Optional[List[str]] = None, search_index: int = -1) -> InlineKeyboardMarkup:
    """Create inline keyboard markup for doujin"""
    buttons = []
    
    if page_mode:
        # Page navigation mode - show manga pages
        
        # First row: First page, -10 pages, current page, +10 pages, last page
        first_row = []
        
        # First page button
        if manga_current_page > 1:
            first_row.append(InlineKeyboardButton(
                text="⏪",
                callback_data=f"page:first:{doujin_id}:{manga_current_page}"
            ))
        
        # Previous 10 pages button
        if manga_current_page > 10:
            first_row.append(InlineKeyboardButton(
                text="⬅️10",
                callback_data=f"page:prev10:{doujin_id}:{manga_current_page}"
            ))
        
        # Page indicator (removed per user request)
        
        # Next 10 pages button
        if manga_current_page + 10 <= manga_total_pages:
            first_row.append(InlineKeyboardButton(
                text="10➡️",
                callback_data=f"page:next10:{doujin_id}:{manga_current_page}"
            ))
        
        # Last page button
        if manga_current_page < manga_total_pages:
            first_row.append(InlineKeyboardButton(
                text="⏩",
                callback_data=f"page:last:{doujin_id}:{manga_current_page}"
            ))
        
        if first_row:
            buttons.append(first_row)
            
        # Second row: Previous page, Next page
        second_row = []
        
        # Previous page button
        if manga_current_page > 1:
            second_row.append(InlineKeyboardButton(
                text="⬅️",
                callback_data=f"page:prev:{doujin_id}:{manga_current_page}"
            ))
        
        # Next page button
        if manga_current_page < manga_total_pages:
            second_row.append(InlineKeyboardButton(
                text="➡️",
                callback_data=f"page:next:{doujin_id}:{manga_current_page}"
            ))
        
        if second_row:
            buttons.append(second_row)
            

        
        # Fourth row: Chapter navigation (if we have search results)
        if search_results and search_index >= 0:
            # First row of chapter navigation
            chapter_row_1 = []
            
            # First chapter button
            if search_index > 0:
                first_chapter_id = search_results[0]
                chapter_row_1.append(InlineKeyboardButton(
                    text="⏪",
                    callback_data=f"next_chapter:{first_chapter_id}:0"
                ))
            
            # Previous 10 chapters button
            if search_index >= 10:
                prev_10_index = max(0, search_index - 10)
                prev_10_chapter_id = search_results[prev_10_index]
                chapter_row_1.append(InlineKeyboardButton(
                    text="⬅️10",
                    callback_data=f"next_chapter:{prev_10_chapter_id}:{prev_10_index}"
                ))
            
            # Next 10 chapters button
            if search_index + 10 < len(search_results):
                next_10_index = min(len(search_results) - 1, search_index + 10)
                next_10_chapter_id = search_results[next_10_index]
                chapter_row_1.append(InlineKeyboardButton(
                    text="10➡️",
                    callback_data=f"next_chapter:{next_10_chapter_id}:{next_10_index}"
                ))
            
            # Last chapter button
            if search_index < len(search_results) - 1:
                last_chapter_id = search_results[-1]
                chapter_row_1.append(InlineKeyboardButton(
                    text="⏩",
                    callback_data=f"next_chapter:{last_chapter_id}:{len(search_results) - 1}"
                ))
            
            if chapter_row_1:
                buttons.append(chapter_row_1)
                
            # Second row of chapter navigation (single step)
            chapter_row_2 = []
            
            # Previous chapter button
            if search_index > 0:
                prev_chapter_id = search_results[search_index - 1]
                chapter_row_2.append(InlineKeyboardButton(
                    text="⬅️",
                    callback_data=f"next_chapter:{prev_chapter_id}:{search_index - 1}"
                ))
            
            # Next chapter button
            if search_index < len(search_results) - 1:
                next_chapter_id = search_results[search_index + 1]
                chapter_row_2.append(InlineKeyboardButton(
                    text="➡️",
                    callback_data=f"next_chapter:{next_chapter_id}:{search_index + 1}"
                ))
            
            if chapter_row_2:
                buttons.append(chapter_row_2)
                
            # Back to Search button in page mode (shorter name) - only if from search
            if search_results:  # Only show if we have search results context
                # We'll use a generic callback and get the search query from session in handler
                buttons.append([
                    InlineKeyboardButton(
                        text="🔍",
                        callback_data="back_to_search_page"
                    )
                ])
    else:
        # Info mode - show doujin info
        # Read pages button
        buttons.append([
            InlineKeyboardButton(
                text="📖",
                callback_data=f"read:{doujin_id}:1"
            )
        ])
        

        
        # Navigation buttons for search results
        if show_navigation and total_pages > 1:
            # First row: First result, -10 results, current position, +10 results, last result
            first_row = []
            
            # First result button
            if current_page > 0:
                first_row.append(InlineKeyboardButton(
                    text="⏪",
                    callback_data=f"nav:first:{current_page}:{search_query}"
                ))
            
            # Previous 10 results button
            if current_page >= 10:
                first_row.append(InlineKeyboardButton(
                    text="⬅️10",
                    callback_data=f"nav:prev10:{current_page}:{search_query}"
                ))
            
            # Next 10 results button
            if current_page + 10 < total_pages:
                first_row.append(InlineKeyboardButton(
                    text="10➡️",
                    callback_data=f"nav:next10:{current_page}:{search_query}"
                ))
            
            # Last result button
            if current_page < total_pages - 1:
                first_row.append(InlineKeyboardButton(
                    text="⏩",
                    callback_data=f"nav:last:{current_page}:{search_query}"
                ))
            
            if first_row:
                buttons.append(first_row)
            
            # Second row: Previous result, page indicator, next result
            second_row = []
            
            if current_page > 0:
                second_row.append(InlineKeyboardButton(
                    text="⬅️",
                    callback_data=f"nav:prev:{current_page}:{search_query}"
                ))
            
            # Page indicator
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
    """Format doujin information for display with better error handling"""
    if not data:
        return "❌ Error: Invalid doujin data"
    
    try:
        # Get title with fallback options
        title_obj = data.get("title", {})
        title = (title_obj.get("english") or 
                title_obj.get("japanese") or 
                title_obj.get("pretty") or 
                "No Title Available")
        
        # Extract tags by type
        all_tags = data.get("tags", [])
        tags = [tag.get("name", "") for tag in all_tags if tag.get("type") == "tag"]
        artists = [tag.get("name", "") for tag in all_tags if tag.get("type") == "artist"]
        languages = [tag.get("name", "") for tag in all_tags if tag.get("type") == "language"]
        categories = [tag.get("name", "") for tag in all_tags if tag.get("type") == "category"]
        
        pages = data.get("num_pages", 0)
        doujin_id = data.get("id", "Unknown")
        
        # Format tags with limits
        def format_tag_list(tag_list, limit=6):
            if not tag_list:
                return "None"
            display_tags = [tag for tag in tag_list if tag][:limit]
            result = ", ".join(display_tags)
            if len(tag_list) > limit:
                result += f" (+{len(tag_list) - limit} more)"
            return result
        
        # Truncate title if too long
        if len(title) > 80:
            title = title[:77] + "..."
        
        # Build formatted text
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
    """Get cover image URL with multiple fallback strategies"""
    try:
        media_id = data.get("media_id")
        if not media_id:
            return None
        
        # Try to get cover info
        images = data.get("images", {})
        cover_info = images.get("cover", {})
        
        # Determine extension
        ext_map = {"j": "jpg", "p": "png", "g": "gif"}
        ext = ext_map.get(cover_info.get("t"), "jpg")
        
        # Try different CDN URLs in order of reliability
        possible_urls = [
            f"https://t.nhentai.net/galleries/{media_id}/cover.{ext}",
            f"https://t.nhentai.net/galleries/{media_id}/thumb.{ext}",
            f"https://i.nhentai.net/galleries/{media_id}/cover.{ext}"
        ]
        
        # Return the first URL (simple fallback strategy)
        return possible_urls[0]
        
    except Exception as e:
        logger.error(f"Error getting cover image URL: {e}")
        return None

def get_page_image_url(data: dict, page_num: int) -> Optional[str]:
    """Get page image URL for a specific page"""
    try:
        media_id = data.get("media_id")
        if not media_id:
            return None
        
        # Get page info
        images = data.get("images", {})
        pages = images.get("pages", [])
        
        if page_num < 1 or page_num > len(pages):
            return None
            
        page_info = pages[page_num - 1]  # Pages are 0-indexed in API
        
        # Determine extension
        ext_map = {"j": "jpg", "p": "png", "g": "gif"}
        ext = ext_map.get(page_info.get("t"), "jpg")
        
        # Try different CDN URLs
        possible_urls = [
            f"https://i.nhentai.net/galleries/{media_id}/{page_num}.{ext}",
            f"https://t.nhentai.net/galleries/{media_id}/{page_num}.{ext}",
            f"https://i.doujins.com/galleries/{media_id}/{page_num}.{ext}"
        ]
        
        logger.info(f"Generated page URL for doujin {data.get('id', 'unknown')}, media_id {media_id}, page {page_num}: {possible_urls[0]}")
        return possible_urls[0]  # Return the primary URL
        
    except Exception as e:
        logger.error(f"Error getting page image URL: {e}")
        return None

async def edit_doujin_info(message, doujin_id: str, show_navigation: bool = False,
                          current_page: int = 0, total_pages: int = 1, 
                          search_query: str = "") -> bool:
    """Edit existing message with doujin information"""
    try:
        data = await get_doujin_by_id(doujin_id)
        if not data:
            return False
        
        caption = format_doujin_info(data)
        markup = create_doujin_markup(doujin_id, show_navigation, current_page, total_pages, search_query)
        
        # Try to edit with cover image
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
                    return True  # Message is already showing the same content
                logger.warning(f"Failed to edit with image: {e}")
                # Try to edit text only
                try:
                    await message.edit_text(
                        text=f"🖼 <i>Image unavailable</i>\n\n{caption}",
                        reply_markup=markup
                    )
                    return True
                except TelegramBadRequest:
                    return False
        else:
            # Edit text only
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
    """Send doujin information with cover image and improved error handling"""
    try:
        logger.info(f"Sending doujin info for ID: {doujin_id}")
        data = await get_doujin_by_id(doujin_id)
        if not data:
            await bot.send_message(chat_id, f"🌙 <b>Oops! That story seems to be missing...</b>\n\n<i>ID {doujin_id} isn't available right now. Try another adventure!</i>")
            return False
        
        caption = format_doujin_info(data)
        markup = create_doujin_markup(doujin_id, show_navigation, current_page, total_pages, search_query)
        
        # Try to send with cover image
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
                # Fallback to text message
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
            # No image available, send text only
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
    """Get or create user session"""
    if user_id not in user_sessions:
        user_sessions[user_id] = {
            'current_search': '',
            'search_results': [],
            'current_page': 0,
            'reading_chapter_index': -1
        }
    return user_sessions[user_id]

async def send_message(message: types.Message, text: str, **kwargs):
    """Send message with reply in groups, regular message in private chats"""
    if message.chat.type == "private":
        return await message.answer(text, **kwargs)
    else:
        return await message.reply(text, **kwargs)

# Command handlers
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    """Handle /start command"""
    try:
        user_name = message.from_user.first_name or "User"
        user_mention = f'<a href="tg://user?id={message.from_user.id}">{user_name}</a>'

        welcome_text = (
            f"🌸 <b>Hey {user_mention}! Welcome to Konan!</b>\n\n"
            f"<i>Your personal guide to endless manga adventures</i> ✨\n\n"
            "🎭 Whether you're seeking romance, action, or drama - I'm here to help you discover incredible stories that speak to your soul.\n\n"
            "💝 <b>Start your journey:</b>\n"
            "├─ <code>/random</code> for surprise discoveries\n"
            "├─ <code>/search</code> to find specific content\n"
            "└─ <code>/help</code> for the complete guide\n\n"
            "🌟 <i>Ready to explore amazing stories?</i>"
        )

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

        # List of images
        image_urls = [
            "https://i.postimg.cc/x841BwFW/New-Project-235-FFA9646.png",
            "https://i.postimg.cc/5NC7HwSV/New-Project-235-A06-DD7-A.png",
            "https://i.postimg.cc/HnPqpdm9/New-Project-235-9-E45-B87.png",
            "https://i.postimg.cc/1tSPTmRg/New-Project-235-AB394-C0.png",
            "https://i.postimg.cc/8ct1M2S7/New-Project-235-9-CAE309.png",
            "https://i.postimg.cc/TYtwDDdt/New-Project-235-2-F658-B0.png",
            "https://i.postimg.cc/xdwqdVfY/New-Project-235-68-BAF06.png",
            "https://i.postimg.cc/hPczxn9t/New-Project-235-9-E9-A004.png",
            "https://i.postimg.cc/jjFPQ1Rk/New-Project-235-A1-E7-CC1.png",
            "https://i.postimg.cc/TPqJV0pz/New-Project-235-CA65155.png",
            "https://i.postimg.cc/wBh0WHbb/New-Project-235-89799-CD.png",
            "https://i.postimg.cc/FKdQ1fzk/New-Project-235-C377613.png",
            "https://i.postimg.cc/rpKqWnnm/New-Project-235-CFD2548.png",
            "https://i.postimg.cc/g0kn7HMF/New-Project-235-C4-A32-AC.png",
            "https://i.postimg.cc/XY6jRkY1/New-Project-235-28-DCBC9.png",
            "https://i.postimg.cc/SN32J9Nc/New-Project-235-99-D1478.png",
            "https://i.postimg.cc/8C86n62T/New-Project-235-F1556-B9.png",
            "https://i.postimg.cc/RCGwVqHT/New-Project-235-5-BBB339.png",
            "https://i.postimg.cc/pTfYBZyN/New-Project-235-17-D796-A.png",
            "https://i.postimg.cc/zGgdgJJc/New-Project-235-165-FE5-A.png"
        ]

        selected_image = random.choice(image_urls)

        # Send the welcome image with caption
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
    """Handle /help command"""
    try:
        user_name = message.from_user.first_name or "User"
        user_mention = f'<a href="tg://user?id={message.from_user.id}">{user_name}</a>'
        
        help_text = (
            f"📚 <b>Complete Guide</b>\n"
            f"<i>Hello {user_mention}! Here's everything:</i>\n\n"
            
            "🎯 <b>COMMANDS</b>\n\n"
            
            "🎲 <b><code>/random</code></b>\n"
            "├─ Get instant random content\n"
            "└─ Perfect for discovery\n\n"
            
            "🔢 <b><code>/id &lt;number&gt;</code></b>\n"
            "├─ Direct access by ID\n"
            "└─ Example: <code>/id 123456</code>\n\n"
            
            "🔍 <b><code>/search &lt;keywords&gt;</code></b>\n"
            "├─ Find specific content\n"
            "├─ <code>/search vanilla</code>\n"
            "├─ <code>/search english</code>\n"
            "└─ <code>/search artist:name</code>\n\n"
            
            "🎮 <b>NAVIGATION</b>\n\n"
            
            "📖 <b>Reading Mode:</b>\n"
            "├─ Click <code>📖</code> to start\n"
            "├─ ⬅️➡️ Previous/Next page\n"
            "├─ ⬅️10 / 10➡️ Jump 10 pages\n"
            "└─ ⏪⏩ First/Last page\n\n"
            
            "📚 <b>Chapter Navigation:</b>\n"
            "├─ Same controls for chapters\n"
            "└─ Seamless reading\n\n"
            
            "🔍 <b>Search Results:</b>\n"
            "├─ Browse unlimited results\n"
            "└─ Intuitive button controls\n\n"
            
            "💡 <b>PRO TIPS</b>\n\n"
            
            "🎯 <b>Search Better:</b>\n"
            "├─ Use specific tags\n"
            "├─ Combine keywords\n"
            "├─ Try: english, japanese\n"
            "└─ Try: vanilla, romance\n\n"
            
            "🚀 <b>Navigate Faster:</b>\n"
            "├─ Bookmark interesting IDs\n"
            "├─ Use 10-page jumps\n"
            "└─ Touch-friendly buttons\n\n"
            
            "✨ <b>Ready to explore?</b>\n"
            "<i>Try any command above!</i>"
        )
        await send_message(message, help_text)
    except Exception as e:
        logger.error(f"Error in help command: {e}")
        await send_message(message, "❌ An error occurred. Please try again.")

@dp.message(Command("random"))
async def cmd_random(message: types.Message):
    """Handle /random command"""
    user_id = message.from_user.id
    try:
        await rate_limiter.wait_if_needed(user_id)
        
        status_msg = await send_message(message, "🎲 Finding a random doujin...")
        
        doujin_id = await get_random_doujin_id()
        if doujin_id:
            await status_msg.delete()
            success = await send_doujin_info(message.chat.id, doujin_id, reply_to_message=message)
            if not success:
                await send_message(message,
                    "🎲 <b>Let's try another roll!</b>\n\n<i>That one didn't work out, but there are thousands more waiting to be discovered!</i>"
                )
        else:
            await status_msg.edit_text(
                "🌟 <b>The magic didn't work this time...</b>\n\n<i>Let's give it another try! Sometimes the best discoveries take a moment to find.</i>"
            )
    except Exception as e:
        logger.error(f"Error in random command: {e}")
        await send_message(message, "❌ An error occurred. Please try again.")

@dp.message(Command("id"))
async def cmd_id(message: types.Message, command: CommandObject):
    """Handle /id command"""
    user_id = message.from_user.id
    try:
        await rate_limiter.wait_if_needed(user_id)
        
        if not command.args:
            await send_message(message, 
                "🔢 <b>Need an ID to get started!</b>\n\n"
                "💡 <i>Just add the number after the command:</i>\n"
                "<code>/id 123456</code>"
            )
            return
        
        doujin_id = command.args.strip()
        if not doujin_id.isdigit():
            await send_message(message, "❌ Please provide a valid numeric ID.\nExample: <code>/id 123456</code>")
            return
        
        status_msg = await send_message(message, f"🔍 Fetching doujin {doujin_id}...")
        
        success = await send_doujin_info(message.chat.id, doujin_id, reply_to_message=message)
        await status_msg.delete()
        
        if not success:
            await send_message(message, f"❌ Doujin {doujin_id} not found or unavailable.")
    except Exception as e:
        logger.error(f"Error in id command: {e}")
        await send_message(message, "❌ An error occurred. Please try again.")

@dp.message(Command("search"))
async def cmd_search(message: types.Message, command: CommandObject):
    """Handle /search command"""
    user_id = message.from_user.id
    try:
        await rate_limiter.wait_if_needed(user_id)
        
        if not command.args:
            await send_message(message,
                "🔍 <b>What would you like to find?</b>\n\n"
                "💡 <i>Just tell me what you're looking for:</i>\n"
                "├─ <code>/search vanilla</code>\n"
                "├─ <code>/search romance</code>\n"
                "└─ <code>/search english</code>"
            )
            return
        
        query = command.args.strip()
        if len(query) < 2:
            await send_message(message, "❌ Search query must be at least 2 characters long.")
            return
        
        status_msg = await send_message(message, f"🔍 Searching for: <b>{query}</b>...")
        
        doujin_ids = await search_nhentai(query)
        if not doujin_ids:
            await status_msg.edit_text(f"❌ No results found for: <b>{query}</b>")
            return
        
        # Store search results in session
        session = get_user_session(user_id)
        session['current_search'] = query
        session['search_results'] = doujin_ids
        session['current_page'] = 0
        
        await status_msg.delete()
        
        # Send first result - each result is now one page (no grouping)
        total_pages = len(doujin_ids)  # Each doujin is one page
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
    """Handle plain text messages as search queries (private chats only)"""
    user_id = message.from_user.id
    try:
        await rate_limiter.wait_if_needed(user_id)
        
        query = message.text.strip()
        if len(query) < 2:
            await send_message(message, "❌ Search query must be at least 2 characters long.")
            return
        
        # Ignore very short common words or single characters
        if len(query) == 1 or query.lower() in ['hi', 'hey', 'ok', 'yes', 'no']:
            await send_message(message,
                "💡 To search, use longer terms like:\n"
                "<code>hinata hyuga</code>\n"
                "<code>english vanilla</code>\n"
                "Or use /help for all commands."
            )
            return
        
        status_msg = await send_message(message, f"🔍 Searching for: <b>{query}</b>...")
        
        doujin_ids = await search_nhentai(query)
        if not doujin_ids:
            await status_msg.edit_text(f"❌ No results found for: <b>{query}</b>")
            return
        
        # Store search results in session
        session = get_user_session(user_id)
        session['current_search'] = query
        session['search_results'] = doujin_ids
        session['current_page'] = 0
        
        await status_msg.delete()
        
        # Send first result
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
    """Handle navigation callbacks"""
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
        
        # Update session
        session['current_page'] = new_page
        
        # Get doujin for new page
        doujin_id = search_results[new_page]
        total_pages = len(search_results)  # Each doujin is one page
        
        # Get doujin data
        data = await get_doujin_by_id(doujin_id)
        if not data:
            await callback.answer("❌ Failed to load doujin")
            return
        
        # Format new content
        caption = format_doujin_info(data)
        markup = create_doujin_markup(doujin_id, True, new_page, total_pages, search_query)
        
        # Try to edit with new image
        cover_url = get_cover_image_url(data)
        try:
            if cover_url and callback.message.photo:
                # Edit with new photo
                await callback.message.edit_media(
                    InputMediaPhoto(media=cover_url, caption=caption),
                    reply_markup=markup
                )
            elif cover_url and not callback.message.photo:
                # Edit to photo message
                await callback.message.edit_media(
                    InputMediaPhoto(media=cover_url, caption=caption),
                    reply_markup=markup
                )
            else:
                # Edit text only
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
    """Handle read callbacks"""
    user_id = callback.from_user.id
    try:
        await rate_limiter.wait_if_needed(user_id)
        
        data_parts = callback.data.split(":")
        doujin_id = data_parts[1]
        page_num = int(data_parts[2]) if len(data_parts) > 2 else 1
        
        # Get doujin data
        data = await get_doujin_by_id(doujin_id)
        if not data:
            await callback.answer("❌ Failed to load doujin")
            return
        
        total_pages = data.get("num_pages", 1)
        if page_num < 1 or page_num > total_pages:
            page_num = 1
        
        # Get page image URL
        page_url = get_page_image_url(data, page_num)
        if not page_url:
            await callback.answer("❌ Failed to get page image")
            return
        
        # Get user session to check for search context
        session = get_user_session(user_id)
        search_results = session.get('search_results', [])
        search_index = -1
        
        # Find current doujin index in search results
        if search_results and doujin_id in search_results:
            search_index = search_results.index(doujin_id)
        
        # Create navigation markup for page reading
        markup = create_doujin_markup(
            doujin_id=doujin_id,
            page_mode=True,
            manga_current_page=page_num,
            manga_total_pages=total_pages,
            search_results=search_results,
            search_index=search_index
        )
        
        # Caption with page info
        title = data.get("title", {}).get("english") or data.get("title", {}).get("pretty") or f"Doujin {doujin_id}"
        if len(title) > 50:
            title = title[:47] + "..."
        
        caption = f"<b>{title}</b>\nPage {page_num}/{total_pages}"
        
        try:
            # Edit message with new page image
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
    """Handle page navigation within doujin"""
    user_id = callback.from_user.id
    try:
        await rate_limiter.wait_if_needed(user_id)
        
        data_parts = callback.data.split(":")
        action = data_parts[1]
        doujin_id = data_parts[2]
        current_page = int(data_parts[3])
        
        # Get doujin data
        data = await get_doujin_by_id(doujin_id)
        if not data:
            await callback.answer("❌ Failed to load doujin")
            return
        
        total_pages = data.get("num_pages", 1)
        
        # Calculate new page based on action
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
        
        # Get new page image
        page_url = get_page_image_url(data, new_page)
        if not page_url:
            await callback.answer("❌ Failed to get page image")
            return
        
        # Get user session for search context
        session = get_user_session(user_id)
        search_results = session.get('search_results', [])
        search_index = -1
        
        if search_results and doujin_id in search_results:
            search_index = search_results.index(doujin_id)
        
        # Create updated markup
        markup = create_doujin_markup(
            doujin_id=doujin_id,
            page_mode=True,
            manga_current_page=new_page,
            manga_total_pages=total_pages,
            search_results=search_results,
            search_index=search_index
        )
        
        # Updated caption
        title = data.get("title", {}).get("english") or data.get("title", {}).get("pretty") or f"Doujin {doujin_id}"
        if len(title) > 50:
            title = title[:47] + "..."
        
        caption = f"<b>{title}</b>\nPage {new_page}/{total_pages}"
        
        try:
            # Edit the image
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
    """Handle chapter navigation within search results"""
    user_id = callback.from_user.id
    try:
        await rate_limiter.wait_if_needed(user_id)
        
        data_parts = callback.data.split(":")
        doujin_id = data_parts[1]
        chapter_index = int(data_parts[2])
        
        # Get user session
        session = get_user_session(user_id)
        search_results = session.get('search_results', [])
        
        if not search_results or chapter_index < 0 or chapter_index >= len(search_results):
            await callback.answer("❌ Invalid chapter")
            return
        
        # Update session
        session['current_page'] = chapter_index
        session['reading_chapter_index'] = chapter_index
        
        # Get new doujin data
        data = await get_doujin_by_id(doujin_id)
        if not data:
            await callback.answer("❌ Failed to load chapter")
            return
        
        total_pages = data.get("num_pages", 1)
        
        # Get first page of new chapter
        page_url = get_page_image_url(data, 1)
        if not page_url:
            await callback.answer("❌ Failed to get chapter image")
            return
        
        # Create markup for new chapter
        markup = create_doujin_markup(
            doujin_id=doujin_id,
            page_mode=True,
            manga_current_page=1,
            manga_total_pages=total_pages,
            search_results=search_results,
            search_index=chapter_index
        )
        
        # Updated caption
        title = data.get("title", {}).get("english") or data.get("title", {}).get("pretty") or f"Doujin {doujin_id}"
        if len(title) > 50:
            title = title[:47] + "..."
        
        caption = f"<b>{title}</b>\nPage 1/{total_pages}\nChapter {chapter_index + 1}/{len(search_results)}"
        
        try:
            # Edit to new chapter
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
    """Handle back to search button"""
    user_id = callback.from_user.id
    try:
        await rate_limiter.wait_if_needed(user_id)
        
        # Extract search query from callback data
        search_query = callback.data.split(":", 1)[1]
        
        # Get user session
        session = get_user_session(user_id)
        search_results = session.get('search_results', [])
        current_page = session.get('current_page', 0)
        
        if not search_results:
            await callback.answer("❌ No search results available")
            return
        
        # Edit current message with search result
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
    """Handle back to search button from page mode"""
    user_id = callback.from_user.id
    try:
        await rate_limiter.wait_if_needed(user_id)
        
        # Get user session
        session = get_user_session(user_id)
        search_results = session.get('search_results', [])
        current_page = session.get('current_page', 0)
        search_query = session.get('current_search', '')
        
        if not search_results or not search_query:
            await callback.answer("❌ No search results available")
            return
        
        # Edit current message with search result
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

 # ─── Dummy HTTP Server to Keep Render Happy ─────────────────────────────────
class DummyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"AFK bot is alive!")

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

def start_dummy_server():
    port = int(os.environ.get("PORT", 10000))  # Render injects this
    server = HTTPServer(("0.0.0.0", port), DummyHandler)
    print(f"Dummy server listening on port {port}")
    server.serve_forever()

# Main function
async def main():
    """Main function to start the bot"""
    try:
        logger.info("Starting bot...")
        
        # Set bot commands for the menu
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
    # Start dummy HTTP server (needed for Render health check)
    threading.Thread(target=start_dummy_server, daemon=True).start()
    
    asyncio.run(main())
