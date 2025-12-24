import sqlite3
import os

DB_NAME = "autoclipper.db"

if not os.path.exists(DB_NAME):
    print(f"ERROR: {DB_NAME} does not exist.")
    exit()

try:
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    c.execute("SELECT COUNT(*) FROM videos")
    video_count = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM clips")
    clip_count = c.fetchone()[0]
    
    print(f"Videos: {video_count}")
    print(f"Clips: {clip_count}")
    
    if video_count > 0:
        c.execute("SELECT id, title, created_at, file_path FROM videos ORDER BY id DESC LIMIT 1")
        last_vid = c.fetchone()
        print(f"Last Video: {last_vid}")
        
    conn.close()
except Exception as e:
    print(f"Error reading DB: {e}")
