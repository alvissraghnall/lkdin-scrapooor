import asyncio
import csv
import json
import argparse
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
from bs4 import BeautifulSoup as BSoup

# Install with: pip install playwright beautifulsoup4
# Then run: playwright install chromium

SESSION_FILE = "linkedin_session.json"

async def save_session(context, filepath=SESSION_FILE):
    """Save browser session (cookies + storage)"""
    await context.storage_state(path=filepath)
    print(f"✓ Session saved to {filepath}")

async def load_session(context, filepath=SESSION_FILE):
    """Check if session file exists"""
    return Path(filepath).exists()

async def wait_for_manual_login(page, timeout=300000):
    """Wait for user to manually log in"""
    print("\n" + "="*60)
    print("MANUAL LOGIN REQUIRED")
    print("="*60)
    print("Please log in to LinkedIn in the browser window.")
    print("After logging in, you should see your feed.")
    print("="*60)
    
    try:
        # Wait for feed URL or timeout
        await page.wait_for_url("**/feed/**", timeout=timeout)
        print("✓ Login detected!")
        return True
    except PlaywrightTimeout:
        # Check if we're somewhere logged in
        if "login" not in page.url:
            print("✓ Appears to be logged in")
            return True
        print("✗ Login timeout")
        return False

async def login_with_credentials(page, username, password):
    """Programmatic login (may trigger verification)"""
    try:
        await page.goto("https://www.linkedin.com/login", wait_until="networkidle")
        
        # Fill credentials
        await page.fill('input[name="session_key"]', username)
        await page.fill('input[name="session_password"]', password)
        
        # Click login
        await page.click('button[type="submit"]')
        
        # Wait a bit
        await page.wait_for_timeout(15000)
        
        # Check if verification needed
        if "checkpoint" in page.url or "challenge" in page.url:
            print("⚠ Verification required - waiting for manual completion...")
            return await wait_for_manual_login(page)
        
        # Check if logged in
        await page.wait_for_timeout(2000)
        if "feed" in page.url or ("login" not in page.url and "linkedin.com" in page.url):
            print("✓ Login successful!")
            return True
        
        return False
        
    except Exception as e:
        print(f"Login error: {e}")
        return False

async def load_all_comments(page, show_replies=False):
    """Click 'load more' and 'show replies' buttons until all are loaded."""
    print("Loading comments: ", end="", flush=True)
    
    # Click "load more comments" button
    while True:
        try:
            load_more_btn = page.locator('button.comments-comments-list__load-more-comments-button--cr').first
            if await load_more_btn.is_visible(timeout=2000):
                await load_more_btn.scroll_into_view_if_needed()
                await load_more_btn.click()
                print(".", end="", flush=True)
                await page.wait_for_timeout(1500)
            else:
                break
        except Exception:
            break
    print(" Done!")

    if show_replies:
        print("Loading replies: ", end="", flush=True)
        
        # Click "see previous replies" buttons
        while True:
            try:
                previous_replies_btn = page.locator('button.comments-replies-list__replies-button:has-text("See previous replies")').first
                if await previous_replies_btn.is_visible(timeout=2000):
                    await previous_replies_btn.scroll_into_view_if_needed()
                    await previous_replies_btn.click()
                    print(".", end="", flush=True)
                    await page.wait_for_timeout(1000)
                else:
                    break
            except Exception:
                break

        # Click on "X replies" to expand them
        while True:
            try:
                # Find buttons that contain the text "replies" but not "previous"
                reply_buttons = page.locator('button.comments-comment-social-bar__reply-action-button--cr:has-text("replies")')
                count = await reply_buttons.count()
                if count == 0:
                    break

                # Click them starting from the last to avoid stale elements
                for i in range(count - 1, -1, -1):
                    btn = reply_buttons.nth(i)
                    if await btn.is_visible():
                        await btn.scroll_into_view_if_needed()
                        await btn.click()
                        print(".", end="", flush=True)
                        await page.wait_for_timeout(500)
                
                # After clicking, the buttons might be gone, so we re-check
                await page.wait_for_timeout(2000) # wait for replies to load
                if await reply_buttons.count() == 0:
                    break

            except Exception:
                break
        
        print(" Done!")


async def extract_data_from_html(html_content, config):
    """Extract comment data from HTML using BeautifulSoup"""
    soup = BSoup(html_content, "html.parser")
    
    data = []
    email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
    
    # Find all comment articles
    comment_articles = soup.find_all("article", class_="comments-comment-entity")
    
    for article in comment_articles:
        name = ""
        headline = ""
        profile_link = ""
        avatar = ""
        comment_text = ""
        emails = []

        # Extract Name
        name_elem = article.select_one("span.comments-comment-meta__description-title")
        if name_elem:
            name = name_elem.get_text(strip=True)

        # Extract Headline
        headline_elem = article.select_one("div.comments-comment-meta__description-subtitle")
        if headline_elem:
            headline = headline_elem.get_text(strip=True)
            
        # Extract Profile Link and Avatar
        profile_link_elem = article.select_one("a.comments-comment-meta__image-link")
        if profile_link_elem:
            profile_link = urljoin("https://www.linkedin.com/", profile_link_elem.get("href", ""))
            avatar_elem = profile_link_elem.find("img")
            if avatar_elem:
                avatar = avatar_elem.get("src", "")

        # Extract Comment Text
        comment_elem = article.select_one("span.comments-comment-item__main-content")
        if comment_elem:
            comment_text = comment_elem.get_text(strip=True)
            
        # Extract Emails from comment
        if comment_text:
            emails = re.findall(email_pattern, comment_text)

        # Only add if we have at least a name or a comment
        if name or comment_text:
            data.append({
                "name": name,
                "profile_link": profile_link,
                "avatar": avatar,
                "headline": headline,
                "email": ", ".join(emails), # Join multiple emails found in one comment
                "comment": comment_text
            })
            
    return data

async def scrape_post_comments(post_url, config, args):
    """Main scraping function"""
    
    async with async_playwright() as p:
        # Launch browser
        browser = await p.chromium.launch(
            headless=args.headless,
            args=['--no-sandbox', '--disable-setuid-sandbox']
        )
        
        # Create context with or without saved session
        if Path(SESSION_FILE).exists() and args.use_session:
            print(f"Loading session from {SESSION_FILE}")
            context = await browser.new_context(storage_state=SESSION_FILE)
        else:
            context = await browser.new_context()
        
        page = await context.new_page()
        
        try:
            # Check if we need to log in
            if not Path(SESSION_FILE).exists() or not args.use_session:
                if args.manual_login:
                    # Manual login
                    await page.goto("https://www.linkedin.com/login")
                    logged_in = await wait_for_manual_login(page)
                    
                    if not logged_in:
                        print("Login failed")
                        return None
                    
                    # Save session
                    await save_session(context)
                
                elif args.username and args.password:
                    # Programmatic login
                    logged_in = await login_with_credentials(page, args.username, args.password)
                    
                    if not logged_in:
                        print("Login failed")
                        return None
                    
                    # Save session
                    await save_session(context)
                
                else:
                    print("No session found. Use --manual-login or provide credentials")
                    return None
            
            # Navigate to post
            print(f"\nNavigating to: {post_url}")
            await page.goto(post_url, wait_until="networkidle")
            await page.wait_for_timeout(2000)
            
            # Load all comments
            await load_all_comments(page, args.show_replies)
            
            # Get page content
            html_content = await page.content()
            
            # Save if requested
            if args.save_page_source:
                with open("page_source.html", "w", encoding="utf-8") as f:
                    f.write(html_content)
                print("Page source saved to page_source.html")
            
            # Extract data
            print("Extracting data...")
            data = await extract_data_from_html(html_content, config)
            
            return data
        
        finally:
            await context.close()
            await browser.close()

def write_to_csv(data, filename):
    """Write extracted data to CSV"""
    if not data:
        print("No data to write.")
        return

    with open(filename, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=data[0].keys())
        writer.writeheader()
        writer.writerows(data)
    
    print(f"✓ Data written to {filename}")

async def main():
    parser = argparse.ArgumentParser(description="LinkedIn Post Comment Scraper (Playwright)")
    
    parser.add_argument("--headless", action="store_true", help="Run in headless mode")
    parser.add_argument("--show-replies", action="store_true", help="Load all replies")
    parser.add_argument("--save-page-source", action="store_true", help="Save HTML for debugging")
    parser.add_argument("--use-session", action="store_true", default=True, help="Use saved session")
    parser.add_argument("--manual-login", action="store_true", help="Perform manual login")
    parser.add_argument("--username", type=str, help="LinkedIn username/email")
    parser.add_argument("--password", type=str, help="LinkedIn password")
    
    args = parser.parse_args()
    
    # Load config
    try:
        with open("config.json") as f:
            config = json.load(f)
    except FileNotFoundError:
        print("Error: config.json not found")
        return
    
    post_url = config.get("post_url", "")
    if not post_url:
        print("Error: post_url not found in config.json")
        return
    
    # Generate filename
    now = datetime.now()
    unique_suffix = now.strftime("-%m-%d-%Y--%H-%M")
    output_file = config.get("filename", "linkedin_comments") + unique_suffix + ".csv"
    
    # Scrape
    print("Starting LinkedIn scraper...")
    data = await scrape_post_comments(post_url, config, args)
    
    if data:
        print(f"Found {len(data)} comments")
        write_to_csv(data, output_file)
        print(f"\n✓ Scraping complete!")
    else:
        print("\n✗ Scraping failed")

if __name__ == "__main__":
    asyncio.run(main())
