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
    """Click 'load more comments' buttons until all loaded"""
    print("Loading comments: ", end="", flush=True)
    
    while True:
        try:
            # Try to find and click "load more comments" button
            load_more_btn = page.locator('button:has-text("Show more comments"), button:has-text("Load more comments")').first
            
            if await load_more_btn.is_visible(timeout=2000):
                await load_more_btn.scroll_into_view_if_needed()
                await load_more_btn.click()
                print(".", end="", flush=True)
                await page.wait_for_timeout(1500)
            else:
                break
        except:
            break
    
    print(" Done!")
    
    if show_replies:
        print("Loading replies: ", end="", flush=True)
        # Click all "show more replies" buttons
        reply_buttons = page.locator('button:has-text("replies"), button:has-text("reply")')
        count = await reply_buttons.count()
        
        for i in range(count):
            try:
                btn = reply_buttons.nth(i)
                if await btn.is_visible():
                    await btn.scroll_into_view_if_needed()
                    await btn.click()
                    print(".", end="", flush=True)
                    await page.wait_for_timeout(500)
            except:
                continue
        
        print(" Done!")

async def extract_data_from_html(html_content, config):
    """Extract comment data from HTML using BeautifulSoup"""
    soup = BSoup(html_content, "html.parser")
    
    # Extract comments
    comment_elements = soup.find_all("span", {"class": config.get("comment_class", "comments-comment-item__main-content")})
    comments = [elem.get_text(strip=True) for elem in comment_elements]
    
    # Extract names
    name_elements = soup.find_all("span", {"class": config.get("name_class", "comments-post-meta__name-text")})
    names = [elem.get_text(strip=True).split("\n")[0] for elem in name_elements]
    
    # Extract headlines
    headline_elements = soup.find_all("span", {"class": config.get("headline_class", "comments-post-meta__headline")})
    headlines = [elem.get_text(strip=True) for elem in headline_elements]
    
    # Extract profile links and avatars
    BASE_URL = "https://www.linkedin.com/"
    profile_link_elements = soup.find_all("a", {"class": config.get("avatar_class", "comments-post-meta__profile-link")})
    
    profile_links = []
    avatars = []
    
    for elem in profile_link_elements:
        # Get profile URL
        href = elem.get("href", "")
        profile_links.append(urljoin(BASE_URL, href))
        
        # Get avatar image
        img_tag = elem.find("img")
        avatar_url = img_tag.get("src", "") if img_tag else ""
        avatars.append(avatar_url)
    
    # Extract emails from comments (if any)
    import re
    email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
    emails = []
    for comment in comments:
        found_emails = re.findall(email_pattern, comment)
        emails.append(found_emails[0] if found_emails else "")
    
    # Normalize lengths
    max_len = max(len(names), len(profile_links), len(avatars), len(headlines), len(comments))
    
    names += [""] * (max_len - len(names))
    profile_links += [""] * (max_len - len(profile_links))
    avatars += [""] * (max_len - len(avatars))
    headlines += [""] * (max_len - len(headlines))
    emails += [""] * (max_len - len(emails))
    comments += [""] * (max_len - len(comments))
    
    return {
        "names": names,
        "profile_links": profile_links,
        "avatars": avatars,
        "headlines": headlines,
        "emails": emails,
        "comments": comments
    }

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
    with open(filename, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Name", "Profile Link", "Profile Picture", "Headline", "Email", "Comment"])
        
        for i in range(len(data["names"])):
            writer.writerow([
                data["names"][i],
                data["profile_links"][i],
                data["avatars"][i],
                data["headlines"][i],
                data["emails"][i],
                data["comments"][i]
            ])
    
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
        print(f"Found {len(data['names'])} comments")
        write_to_csv(data, output_file)
        print(f"\n✓ Scraping complete!")
    else:
        print("\n✗ Scraping failed")

if __name__ == "__main__":
    asyncio.run(main())
