"""
This module provides utility functions for the LinkedIn scrapers.
It handles checking post URLs, user login details, saving credentials, and downloading avatars.
"""

import os
import re
import sys
import json
import urllib.request
from time import sleep
from getpass import getpass


"""
Redundant piece of Code

def str2bool(v):
    if isinstance(v, bool):
        return v
    if v.lower() in ("yes", "true", "t", "y", "1"):
        return True
    elif v.lower() in ("no", "false", "f", "n", "0"):
        return False
    else:
        raise argparse.ArgumentTypeError("Boolean value expected.")
"""

def check_post_url(post_url: str):
    if not post_url:
        print("You haven't entered required post_url in config.json file!")
        choice = input("Do you want to enter url now? (y/N) : ").lower()
        if choice == "y":
            post_url = input("Enter url of post: ")
            return post_url
        elif choice == "n":
            sys.exit()
        else:
            print("Invalid choice!")
            sys.exit(1)

    return post_url


def login_details() -> tuple[str, str]:
    credentials_exist = True
    try:
        with open(
            "credentials.json",
        ) as f:
            Creds: dict[str, str] = json.load(f)
    except:
        credentials_exist = False

    if credentials_exist:
        choice = input("Do you want to use the saved credentials? (y/N) : ")
        if choice.lower() == "y":
            return Creds["email"], Creds["password"]

    username = input("Enter your email registered in LinkedIn : ")
    password = getpass("Enter your password : ")
    save_credentials(username, password)

    return username, password


def save_credentials(email: str, password: str):
    print("Entering credentials everytime is boring :/")
    choice = input("Do you want to save the login credentials in a json? (y/N) : ")
    if choice.lower() == "y":
        with open("credentials.json", "w") as f:
            json.dump({"email": email, "password": password}, f)


def download_avatars(urls: list[str], filenames: list[str], dir_name: str):
    try:
        os.mkdir(dir_name)
    except:
        pass

    filenames = [
        filename.lower().replace(".", "").replace(" ", "-") for filename in filenames
    ]

    opener = urllib.request.build_opener()
    opener.addheaders = [
        (
            "User-Agent",
            "Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/36.0.1941.0 Safari/537.36",
        )
    ]
    urllib.request.install_opener(opener)

    for url, filename in zip(urls, filenames):
        urllib.request.urlretrieve(url, f"{dir_name}/{filename}.jpg")

    print("Profile pictures have been downloaded!")