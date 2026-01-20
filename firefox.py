import csv
import json
import argparse
from time import time, sleep
from datetime import datetime
from urllib.parse import urljoin

from selenium import webdriver
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.common.by import By
from bs4 import BeautifulSoup as BSoup

from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

import undetected_geckodriver as ug


from utils import (
    check_post_url,
    login_details,
    load_more,
    extract_emails,
    download_avatars,
    write_data2csv,
)

parser = argparse.ArgumentParser(description="Linkedin Scraping.")

parser.add_argument(
    "--headless", dest="headless", action="store_true", help="Go headless browsing"
)
parser.set_defaults(headless=False)
parser.add_argument(
    "--show-replies", dest="show_replies", action="store_true", help="Load all replies to comments"
)
parser.set_defaults(show_replies=False)

parser.add_argument(
    "--download-pfp",
    dest="download_avatars",
    action="store_true",
    help="Download profile pictures of commentors",
)
parser.set_defaults(download_avatars=False)

parser.add_argument(
    "--save-page-source",
    dest="save_page_source",
    action="store_true",
    help="Save page source for debugging",
)
parser.set_defaults(save_page_source=False)

parser.add_argument(
    "--firefox-binary",
    dest="firefox_binary",
    type=str,
    default=None,
    help="Path to Firefox binary (e.g., /usr/bin/firefox or C:\\Program Files\\Mozilla Firefox\\firefox.exe)",
)

args = parser.parse_args()

now = datetime.now()
unique_suffix = now.strftime("-%m-%d-%Y--%H-%M")

# Load config with error handling
try:
    with open("config.json") as f:
        Config: dict[str, str] = json.load(f)
except FileNotFoundError:
    print("Error: config.json not found. Please create a config file.")
    exit(1)
except json.JSONDecodeError:
    print("Error: config.json is not valid JSON.")
    exit(1)

post_url = check_post_url(Config["post_url"])

# Create CSV writer
try:
    csv_file = open(
        Config["filename"] + unique_suffix + ".csv",
        "w",
        encoding="utf-8",
        newline=""  # Added to prevent blank lines in CSV
    )
    writer = csv.writer(csv_file)
    writer.writerow(["Name", "Profile Link", "Profile Picture", "Headline", "Email", "Comment"])
except Exception as e:
    print(f"Error creating CSV file: {e}")
    exit(1)

linkedin_username, linkedin_password = login_details()

start = time()
print("Initiating the process....")

# Selenium Firefox Driver setup
options = Options()

if args.headless:
    options.add_argument("--headless")

# Additional options for stability and stealth
options.set_preference("dom.webdriver.enabled", False)
options.set_preference("useAutomationExtension", False)
options.set_preference("general.useragent.override", "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0")

# Set Firefox binary path if provided
if args.firefox_binary:
    options.binary_location = args.firefox_binary
    print(f"Using Firefox binary at: {args.firefox_binary}")

try:
    # Use undetected-geckodriver
    driver = ug.Firefox(options=options)
    driver.maximize_window()
except Exception as e:
    print(f"Error initializing Firefox driver: {e}")
    print("\nTroubleshooting tips:")
    print("1. Install undetected-geckodriver: pip install undetected-geckodriver")
    print("2. Specify Firefox binary path with --firefox-binary flag")
    print("3. Example: python script.py --firefox-binary 'C:\\Program Files\\Mozilla Firefox\\firefox.exe'")
    csv_file.close()
    exit(1)

try:
    # Navigate to LinkedIn
    driver.get("https://www.linkedin.com/login?lipi=urn%3Ali%3Apage%3Adeeplink_linkedinmobileapp%3BCe3UA3pGRFeaE6JvJSnLow%3D%3D&destType=web&fromSignIn=true&trk=guest_homepage-basic_nav-header-signin")
    
    wait = WebDriverWait(driver, 20)
    
    print(f"Current URL: {driver.current_url}")
    driver.save_screenshot("login_page.png")
    
    # Login process with better error handling
    try:
        username_field = wait.until(
            EC.presence_of_element_located((By.ID, "username"))
        )
        username_field.send_keys(linkedin_username)
        
        password_field = driver.find_element(By.ID, "password")
        password_field.send_keys(linkedin_password)
        
        sign_in_button = driver.find_element(By.XPATH, "//button[@type='submit']")
        sign_in_button.click()
        
        driver.save_screenshot("after_login.png")
        # Wait for login to complete
        sleep(25)

        print(driver.current_url, driver)
        
        # Check if verification is needed
        if "checkpoint" in driver.current_url or "challenge" in driver.current_url:
            print("LinkedIn requires verification. Please complete it manually.")
            driver.save_screenshot("requires_verification.png")
            input("Press Enter after completing verification...")
            driver.save_screenshot("after_verification.png")

        
    except TimeoutException:
        print("Login page elements not found. Saving screenshot for debugging.")
        driver.save_screenshot("login_error.png")
        raise
    
    # Navigate to post
    print(f"Navigating to post: {post_url}")
    driver.get(post_url)
    sleep(20)  # Wait for page to load
    
    # Load comments
    print("Loading comments:", end=" ", flush=True)
    driver.save_screenshot("post_page.png")

    load_more("comments", Config["load_comments_class"], driver)
    
    if args.show_replies:
        print("\nLoading replies:", end=" ", flush=True)
        driver.save_screenshot("post_page_replies.png")
        load_more("replies", Config["load_replies_class"], driver)
    
    print("\nExtracting data...")
    
    # Save page source if requested
    if args.save_page_source:
        with open("page_source.html", "w", encoding='utf-8') as f:
            f.write(driver.page_source)
        print("Page source saved to page_source.html")
    
    # Parse with BeautifulSoup
    bs_obj = BSoup(driver.page_source, "html.parser")
    
    # Extract data with error handling
    comments = bs_obj.find_all("span", {"class": Config["comment_class"]})
    comments = [comment.get_text(strip=True) for comment in comments]
    
    headlines = bs_obj.find_all("span", {"class": Config["headline_class"]})
    headlines = [headline.get_text(strip=True) for headline in headlines]
    
    emails = extract_emails(comments)
    
    names = bs_obj.find_all("span", {"class": Config["name_class"]})
    names = [name.get_text(strip=True).split("\n")[0] for name in names]
    
    BASE_URL = "https://www.linkedin.com/"
    
    profile_links_set = bs_obj.find_all("a", {"class": Config["avatar_class"]})
    profile_links = [
        urljoin(BASE_URL, profile_link.get("href", "")) 
        for profile_link in profile_links_set
    ]
    
    avatars = []
    for a in profile_links_set:
        img_link = ""
        try:
            img_tag = a.find("img")
            if img_tag:
                img_link = img_tag.get("src", "")
        except Exception as e:
            print(f"Error extracting avatar: {e}")
        
        avatars.append(img_link)
    
    # Ensure all lists have the same length
    max_len = max(len(names), len(profile_links), len(avatars), len(headlines), len(comments))
    
    # Pad lists to same length
    names += [""] * (max_len - len(names))
    profile_links += [""] * (max_len - len(profile_links))
    avatars += [""] * (max_len - len(avatars))
    headlines += [""] * (max_len - len(headlines))
    emails += [""] * (max_len - len(emails))
    comments += [""] * (max_len - len(comments))
    
    print(f"Found {len(names)} comments")
    
    # Write data to CSV
    write_data2csv(writer, names, profile_links, avatars, headlines, emails, comments)
    
    # Download avatars if requested
    if args.download_avatars:
        download_avatars(avatars, names, Config["dirname"] + unique_suffix)
    
    end = time()
    time_spent = end - start
    
    print(
        "%d linkedin post comments scraped in: %.2f minutes (%d seconds)"
        % (len(names), ((time_spent) / 60), (time_spent))
    )

except Exception as e:
    print(f"Error during scraping: {e}")
    driver.save_screenshot("error_screenshot.png")
    if args.save_page_source:
        with open("error_page_source.html", "w", encoding='utf-8') as f:
            f.write(driver.page_source)
    raise

finally:
    # Cleanup
    driver.quit()
    csv_file.close()
    print("Browser closed and files saved.")
