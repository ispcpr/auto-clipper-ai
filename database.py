import sqlite3
import datetime
import json
import os

DB_NAME = "autoclipper.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    # Videos Table
    c.execute('''
        CREATE TABLE IF NOT EXISTS videos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            youtube_url TEXT,
            title TEXT,
            file_path TEXT,
            created_at DATETIME
        )
    ''')
    
    # Clips Table
    c.execute('''
        CREATE TABLE IF NOT EXISTS clips (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id INTEGER,
            title TEXT,
            hashtags TEXT,
            start_time REAL,
            end_time REAL,
            score INTEGER,
            reason TEXT,
            viral_detail TEXT,
            file_path TEXT,
            FOREIGN KEY(video_id) REFERENCES videos(id)
        )
    ''')
    
    # Simple Migration: Add viral_detail if not exists (for existing DBs)
    try:
        c.execute("ALTER TABLE clips ADD COLUMN viral_detail TEXT")
    except:
        pass # Already exists
        
    conn.commit()
    conn.close()

def update_clip_path(clip_id, file_path):
    """Updates the file path of a specific clip."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE clips SET file_path = ? WHERE id = ?", (file_path, clip_id))
    conn.commit()
    conn.close()

def save_analysis_result(youtube_url, title, video_path, clips_data):
    """
    Saves the full analysis result.
    clips_data: List of dicts (from Clipper)
    """
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    # 1. Insert Video
    created_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute('INSERT INTO videos (youtube_url, title, file_path, created_at) VALUES (?, ?, ?, ?)',
              (youtube_url, title, video_path, created_at))
    video_id = c.lastrowid
    
    # 2. Insert Clips
    clip_ids = []
    for clip in clips_data:
        # Check if file_path exists in clip data (it might not be rendered yet, or might be)
        # For now we might store partial data or update later. 
        # But typically we save AFTER rendering? Or after Analysis?
        # Let's assume we save after Analysis (Candidate generation).
        
        # Serialize hashtags list to string
        hashtags_str = json.dumps(clip.get("hashtags", []))
        
        c.execute('''
            INSERT INTO clips (video_id, title, hashtags, start_time, end_time, score, reason, viral_detail, file_path)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            video_id,
            clip.get("title", "Untitled"),
            hashtags_str,
            clip.get("start"),
            clip.get("end"),
            clip.get("score"),
            clip.get("reason", ""),
            clip.get("viral_detail", ""),
            clip.get("file_path", "")
        ))
        clip_ids.append(c.lastrowid)
        

        
    conn.commit()
    conn.close()
    return video_id, clip_ids

def get_all_history():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    # Get Videos
    c.execute('SELECT * FROM videos ORDER BY created_at DESC')
    videos = [dict(row) for row in c.fetchall()]
    
    # Get Clips for each video
    results = []
    for vid in videos:
        c.execute('SELECT * FROM clips WHERE video_id = ?', (vid['id'],))
        clips = [dict(row) for row in c.fetchall()]
        
        # Parse hashtags back to list
        for clip in clips:
            try:
                clip['hashtags'] = json.loads(clip['hashtags'])
            except:
                clip['hashtags'] = []
                
        vid['clips'] = clips
        results.append(vid)
        
    conn.close()
    return results

    return dict(row) if row else None

def delete_video(video_id):
    """
    Deletes a video and its associated clips from the database.
    Returns the video file path and a list of clip file paths to be deleted from disk.
    """
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    # Get Video Path
    c.execute('SELECT file_path FROM videos WHERE id = ?', (video_id,))
    vid_row = c.fetchone()
    video_path = vid_row['file_path'] if vid_row else None
    
    # Get associated clips paths
    c.execute('SELECT file_path FROM clips WHERE video_id = ?', (video_id,))
    clip_rows = c.fetchall()
    clip_paths = [row['file_path'] for row in clip_rows if row['file_path']]
    
    # Delete Clips
    c.execute('DELETE FROM clips WHERE video_id = ?', (video_id,))
    
    # Delete Video
    c.execute('DELETE FROM videos WHERE id = ?', (video_id,))
    
    conn.commit()
    conn.close()
    
    return video_path, clip_paths

def delete_clip(clip_id):
    """
    Deletes a single clip from the database.
    Returns the file path to be deleted from disk.
    """
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    c.execute('SELECT file_path FROM clips WHERE id = ?', (clip_id,))
    row = c.fetchone()
    file_path = row['file_path'] if row else None
    
    c.execute('DELETE FROM clips WHERE id = ?', (clip_id,))
    
    conn.commit()
    conn.close()
    
    return file_path
