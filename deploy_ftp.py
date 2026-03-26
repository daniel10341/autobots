#!/usr/bin/env python3
"""
Deploy files to HostGator via FTP.
Requires FTP_PASSWORD environment variable to be set.

Usage:
    export FTP_PASSWORD="your_password_here"
    python deploy_ftp.py
"""

import ftplib
import os
import sys
from pathlib import Path

# FTP Configuration
FTP_HOST = "uus.jqs.temporary.site"
FTP_IP = "50.6.160.193"
FTP_USER = "daniel@website-fca884fc.uus.jqs.temporary.site"
FTP_PORT = 21
REMOTE_DIR = "/home2/uusjqste/public_html/website_fca884fc"

# Files to deploy (relative to this script's directory)
DEPLOY_FILES = [
    "dashboard.html",
]


def get_password():
    password = os.environ.get("FTP_PASSWORD")
    if not password:
        print("ERROR: FTP_PASSWORD environment variable is not set.")
        print("Run: export FTP_PASSWORD='your_password_here'")
        sys.exit(1)
    return password


def deploy():
    password = get_password()

    print(f"Connecting to {FTP_HOST}:{FTP_PORT}...")
    try:
        ftp = ftplib.FTP()
        ftp.connect(FTP_HOST, FTP_PORT, timeout=30)
        ftp.login(FTP_USER, password)
        print("Connected successfully.")
    except ftplib.all_errors as e:
        print(f"FTP connection failed: {e}")
        print(f"Retrying with IP {FTP_IP}...")
        try:
            ftp = ftplib.FTP()
            ftp.connect(FTP_IP, FTP_PORT, timeout=30)
            ftp.login(FTP_USER, password)
            print("Connected via IP successfully.")
        except ftplib.all_errors as e2:
            print(f"FTP connection failed: {e2}")
            sys.exit(1)

    try:
        ftp.cwd(REMOTE_DIR)
        print(f"Changed to remote directory: {REMOTE_DIR}")
    except ftplib.all_errors as e:
        print(f"Failed to change directory: {e}")
        ftp.quit()
        sys.exit(1)

    script_dir = Path(__file__).parent
    success_count = 0

    for filename in DEPLOY_FILES:
        local_path = script_dir / filename
        if not local_path.exists():
            print(f"WARNING: {filename} not found locally, skipping.")
            continue

        print(f"Uploading {filename}...")
        try:
            with open(local_path, "rb") as f:
                ftp.storbinary(f"STOR {filename}", f)
            print(f"  Uploaded {filename} successfully.")
            success_count += 1
        except ftplib.all_errors as e:
            print(f"  Failed to upload {filename}: {e}")

    ftp.quit()
    print(f"\nDeployment complete: {success_count}/{len(DEPLOY_FILES)} files uploaded.")


if __name__ == "__main__":
    deploy()
