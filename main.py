import re
import csv
import json
import argparse
from time import time, sleep
from datetime import datetime
from urllib.parse import urljoin

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from bs4 import BeautifulSoup as BSoup

import undetected_chromedriver as uc

from utils import (
    check_post_url,
    login_details,
    download_avatars,
)

def load_all_comments(driver, show_replies=False):
    """Click 'load more' and 'show replies' buttons until all are loaded."""
    wait = WebDriverWait(driver, 5)
    print("Loading comments: ", end="", flush=True)

    # Click "load more comments" button
    while True:
        try:
            load_more_btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button.comments-comments-list__load-more-comments-button--cr")))
            driver.execute_script("arguments[0].scrollIntoView(true);", load_more_btn)
            load_more_btn.click()
            print(".", end="", flush=True)
            sleep(1.5)
        except TimeoutException:
            break
    print(" Done!")

    if show_replies:
        print("Loading replies: ", end="", flush=True)
        
        # Click "see previous replies" buttons
        while True:
            try:
                previous_replies_btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, 'button.comments-replies-list__replies-button')))
                driver.execute_script("arguments[0].scrollIntoView(true);", previous_replies_btn)
                previous_replies_btn.click()
                print(".", end="", flush=True)
                sleep(1)
            except TimeoutException:
                break
        
        # Click on "X replies" to expand them
        while True:
            try:
                # Use a more specific selector
                reply_buttons = driver.find_elements(By.CSS_SELECTOR, 'button.comments-comment-social-bar__reply-action-button--cr')
                if not reply_buttons:
                    break
                
                clicked = False
                # Click them starting from the last to avoid stale elements
                for i in range(len(reply_buttons) - 1, -1, -1):
                    btn = reply_buttons[i]
                    if btn.is_displayed() and "repl" in btn.text: # Check for "reply" or "replies"
                        driver.execute_script("arguments[0].scrollIntoView(true);", btn)
                        btn.click()
                        print(".", end="", flush=True)
                        sleep(0.5)
                        clicked = True

                if not clicked:
                    break # No more reply buttons were clicked in this pass
                
                sleep(2) # wait for replies to load
            except Exception:
                break
        
        print(" Done!")

def extract_data_from_html(html_content):
    """Extract comment data from HTML using BeautifulSoup"""
    soup = BSoup(html_content, "html.parser")
    
    data = []
    email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
    
    comment_articles = soup.find_all("article", class_="comments-comment-entity")
    
    for article in comment_articles:
        name, headline, profile_link, avatar, comment_text = "", "", "", "", ""
        emails = []

        name_elem = article.select_one("span.comments-comment-meta__description-title")
        if name_elem:
            name = name_elem.get_text(strip=True)

        headline_elem = article.select_one("div.comments-comment-meta__description-subtitle")
        if headline_elem:
            headline = headline_elem.get_text(strip=True)
            
        profile_link_elem = article.select_one("a.comments-comment-meta__image-link")
        if profile_link_elem:
            profile_link = urljoin("https://www.linkedin.com/", profile_link_elem.get("href", ""))
            avatar_elem = profile_link_elem.find("img")
            if avatar_elem:
                avatar = avatar_elem.get("src", "")

        comment_elem = article.select_one("span.comments-comment-item__main-content")
        if comment_elem:
            comment_text = comment_elem.get_text(strip=True)
            emails = re.findall(email_pattern, comment_text)

        if name or comment_text:
            data.append({
                "Name": name,
                "Profile Link": profile_link,
                "Profile Picture": avatar,
                "Headline": headline,
                "Email": ", ".join(emails),
                "Comment": comment_text
            })
            
    return data

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

def main():
    parser = argparse.ArgumentParser(description="Linkedin Scraping.")
    parser.add_argument("--headless", action="store_true", help="Go headless browsing")
    parser.add_argument("--show-replies", action="store_true", help="Load all replies to comments")
    parser.add_argument("--download-pfp", dest="download_avatars", action="store_true", help="Download profile pictures of commentors")
    parser.add_argument("--save-page-source", action="store_true", help="Save page source for debugging")
    args = parser.parse_args()

    now = datetime.now()
    unique_suffix = now.strftime("-%m-%d-%Y--%H-%M")

    try:
        with open("config.json") as f:
            config = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Error with config.json: {e}")
        exit(1)

    post_url = check_post_url(config.get("post_url"))
    output_file = config.get("filename", "linkedin_comments") + unique_suffix + ".csv"
    
    linkedin_username, linkedin_password = login_details()
    
    start = time()
    print("Initiating the process....")

    options = uc.ChromeOptions()
    if args.headless:
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled")
    # options.add_experimental_option("excludeSwitches", ["enable-automation"])
    # options.add_experimental_option('useAutomationExtension', False)

    try:
        driver = uc.Chrome(options=options, service=Service(ChromeDriverManager().install()))
        driver.maximize_window()
    except Exception as e:
        print(f"Error initializing Chrome driver: {e}")
        exit(1)

    try:
        driver.get("https://www.linkedin.com/login")
        wait = WebDriverWait(driver, 20)
        
        username_field = wait.until(EC.presence_of_element_located((By.ID, "username")))
        username_field.send_keys(linkedin_username)
        driver.find_element(By.ID, "password").send_keys(linkedin_password)
        driver.find_element(By.XPATH, "//button[@type='submit']").click()
        
        sleep(15)
        
        if "checkpoint" in driver.current_url or "challenge" in driver.current_url:
            print("Verification required. Please complete it manually.")
            input("Press Enter after completing verification...")

        print(f"Navigating to post: {post_url}")
        driver.get(post_url)
        sleep(10)

        load_all_comments(driver, args.show_replies)
        
        if args.save_page_source:
            with open("page_source.html", "w", encoding='utf-8') as f:
                f.write(driver.page_source)
            print("Page source saved.")

        print("\nExtracting data...")
        data = extract_data_from_html(driver.page_source)
        
        print(f"Found {len(data)} comments")
        write_to_csv(data, output_file)
        
        if args.download_avatars:
            avatars = [item['Profile Picture'] for item in data if item.get('Profile Picture')]
            names = [item['Name'] for item in data if item.get('Profile Picture')]
            download_avatars(avatars, names, config.get("dirname", "avatars") + unique_suffix)

        time_spent = time() - start
        print(f"{len(data)} comments scraped in: {time_spent / 60:.2f} minutes ({time_spent:.0f} seconds)")

    except Exception as e:
        print(f"An error occurred: {e}")
        driver.save_screenshot("error_screenshot.png")
        raise
    finally:
        driver.quit()
        print("Browser closed.")

if __name__ == "__main__":
    main()
