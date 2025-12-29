import os
import yt_dlp
import json
import cv2
import textwrap
import time
from groq import Groq
from moviepy.editor import VideoFileClip, TextClip, CompositeVideoClip, ColorClip, AudioFileClip, ImageClip
from moviepy.video.fx.all import resize, crop
from dotenv import load_dotenv
import numpy as np
from PIL import Image, ImageFont, ImageDraw
from proglog import ProgressBarLogger

import io
import contextlib
import re
import socket
import requests

# Force IPv4 locally in this module too just in case
_orig_getaddrinfo_clipper = socket.getaddrinfo
def _getaddrinfo_ipv4_clipper(host, port, family=0, type=0, proto=0, flags=0):
    return _orig_getaddrinfo_clipper(host, port, socket.AF_INET, type, proto, flags)
socket.getaddrinfo = _getaddrinfo_ipv4_clipper

# Load environment variables
load_dotenv()

# --- Custom Logger for MoviePy to Streamlit ---
class MyBarLogger(ProgressBarLogger):
    def __init__(self, callback=None):
        super().__init__()
        self.user_callback = callback

    def bars_callback(self, bar, attr, value, old_value=None):
        if bar == 't' and self.user_callback:
            total = self.bars[bar]['total']
            if total > 0:
                percentage = value / total
                self.user_callback(percentage)

def get_groq_client():
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        print("Warning: GROQ_API_KEY not found.")
        return None
    return Groq(api_key=api_key)

# Helper: Log or Print
def log_msg(logger, msg):
    if logger and hasattr(logger, 'info'):
        logger.info(msg)
    else:
        print(msg)

# --- 2. Browser Cookie Import Helper ---
import subprocess

def import_browser_cookies(browser="chrome", output_file="cookies.txt"):
    """
    Runs yt-dlp to extract cookies from the browser and save them to a file.
    User must close the browser for this to work on Windows.
    """
    cmd = [
        "yt-dlp",
        "--cookies-from-browser", browser,
        "--cookies", output_file,
        "--skip-download",
        "https://www.youtube.com"
    ]
    
    try:
        # Run process and capture output to check for "Close browser" warnings
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        
        # Check if cookies.txt was created
        if os.path.exists(output_file):
            return True, "Success"
        else:
            return False, "Cookies file not created. (Unknown error)"
            
    except subprocess.CalledProcessError as e:
        err_msg = e.stderr or e.stdout
        # Common error: "Permission denied" or "Database locked"
        if "lock" in err_msg.lower() or "permission" in err_msg.lower() or "close" in err_msg.lower():
            return False, f"Please CLOSE {browser} completely and try again."
        return False, f"Error: {err_msg}"
    except Exception as e:
        return False, str(e)

def download_video(youtube_url, output_dir="downloads", progress_callback=None, logger=None):
    """
    Dispatcher for video downloading.
    Only Engine: 'yt-dlp'
    """
    os.makedirs(output_dir, exist_ok=True)
    
    # Default to yt-dlp
    if not youtube_url or "youtube.com" not in youtube_url and "youtu.be" not in youtube_url:
        log_msg(logger, "Invalid YouTube URL")
        return None

    # Use timestamp in filename to avoid WinError 5/32 (File Locked)
    timestamp = int(time.time())
    
    # Progress Hook
    def my_hook(d):
        if d['status'] == 'downloading':
            if progress_callback:
                try:
                    p = d.get('_percent_str', '0%').replace('%','')
                    total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
                    downloaded = d.get('downloaded_bytes', 0)
                    if total > 0:
                        percent = downloaded / total
                        progress_callback(percent, f"Downloading: {int(percent*100)}%")
                except:
                    pass
        if d['status'] == 'finished':
            log_msg(logger, 'Done downloading, now converting ...')

    ydl_opts = {
        'format': 'best[ext=mp4]', 
        'outtmpl': os.path.join(output_dir, f'%(title)s_{timestamp}.%(ext)s'),
        'noplaylist': True,
        'overwrites': True,
        'nopart': True,
        'progress_hooks': [my_hook],
        'logger': logger,
        'retries': 3,
        'fragment_retries': 3,
        'force_ipv4': True,
        # Improve bot avoidance
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    }
    
    # Optional Cookies Support (manual bypass)
    cookies_path = "cookies.txt"
    if os.path.exists(cookies_path):
        ydl_opts['cookiefile'] = cookies_path
        log_msg(logger, f"Using cookies from {cookies_path}")
    else:
        # Fallback to browser cookies
        log_msg(logger, "cookies.txt not found. Attempting to use cookies from Chrome browser...")
        ydl_opts['cookiesfrombrowser'] = ('chrome',)
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            log_msg(logger, f"Downloading {youtube_url}...")
            info_dict = ydl.extract_info(youtube_url, download=True)
            video_filename = ydl.prepare_filename(info_dict)
            abs_path = os.path.abspath(video_filename)
            log_msg(logger, f"Video downloaded to: {abs_path}")
            return abs_path
    except Exception as e:
        err_str = str(e)
        if "cookie" in err_str.lower() or "locked" in err_str.lower() or "permission" in err_str.lower():
             log_msg(logger, "⚠️ WARNING: Auto-cookies failed. Please CLOSE your browser (Chrome) and try again, OR upload 'cookies.txt'.")
             log_msg(logger, "ℹ️ See the 'How to get cookies.txt' guide in the sidebar for a permanent fix.")
        
        log_msg(logger, f"Error downloading video: {e}")
        # WinError 32 Workaround
        try:
             with yt_dlp.YoutubeDL(ydl_opts) as ydl: # Re-init to get filename
                info = ydl.extract_info(youtube_url, download=False)
                potential_file = ydl.prepare_filename(info)
                if os.path.exists(potential_file):
                    log_msg(logger, f"WinError workaround: Found {potential_file}. Proceeding.")
                    return os.path.abspath(potential_file)
        except:
             pass
        # Re-raise to show user the specific error
        raise e

def extract_audio(video_path, output_audio_path="temp_audio.mp3", logger=None):
    """Extracts audio from video for fast upload. Compresses to 32k mono to save size."""
    log_msg(logger, f"Extracting audio from {video_path}...")
    try:
        video = VideoFileClip(video_path)
        video.audio.write_audiofile(
            output_audio_path, 
            codec='mp3', 
            bitrate='32k',
            ffmpeg_params=["-ac", "1"], # Mono
            verbose=False, 
            logger=None 
        )
        
        size_mb = os.path.getsize(output_audio_path) / (1024 * 1024)
        log_msg(logger, f"Audio extracted: {output_audio_path} (Size: {size_mb:.2f} MB)")
        
        if size_mb > 25:
            log_msg(logger, "Warning: Audio file is still larger than 25MB. Transcription might fail.")
        
        video.close()
        return output_audio_path
    except Exception as e:
        log_msg(logger, f"Error extracting audio: {e}")
        return None

def transcribe_with_groq(audio_path, logger=None):
    """Transcribes audio using Groq's Whisper API (Large-v3)."""
    client = get_groq_client()
    if not client: return None
    
    log_msg(logger, "Transcribing with Groq Whisper (Large V3)...")
    try:
        with open(audio_path, "rb") as file:
            transcription = client.audio.transcriptions.create(
                file=(os.path.basename(audio_path), file.read()),
                model="whisper-large-v3",
                response_format="verbose_json",
                timestamp_granularities=["word"]
            )
        return transcription
    except Exception as e:
        log_msg(logger, f"Groq Transcription error: {str(e)}")
        return None

def analyze_transcript_with_groq(transcript_obj, n_clips=3, logger=None):
    """Analyzes transcript using Groq Llama 3 to find viral clips with metadata."""
    client = get_groq_client()
    if not client: return []
    
    transcript_text = transcript_obj.text
    duration = transcript_obj.duration
    
    log_msg(logger, "Analyzing transcript with Groq Llama 3...")
    
    logit_has_template = os.getenv("AI_PROMPT_TEMPLATE")
    
    if logit_has_template:
        try:
            transcript_short = textwrap.shorten(transcript_text, width=15000, placeholder="...(truncated)")
            prompt = logit_has_template.format(
                duration=int(duration),
                n_clips=n_clips,
                transcript=transcript_short
            )
            log_msg(logger, "✅ Using Custom AI Prompt from .env")
        except Exception as e:
             log_msg(logger, f"⚠️ Error formatting .env prompt: {e}. Using default.")
             logit_has_template = None # Fallback

    if not logit_has_template:
        prompt = f"""
    You are a professional video editor and content strategist. 
    Analyze the following video transcript (Duration: ~{int(duration)} seconds).
    
    Identify the **top {n_clips} most viral/engaging segments** suitable for TikTok/Reels/Shorts.
    Each segment should be between 59 and 90 seconds long.
    
    **CRITICAL INSTRUCTION**: 
    - The output **MUST BE IN BAHASA INDONESIA**.
    - The Titles must be **CLICKBAIT** and extremely viral (e.g., "TERNYATA...", "JANGAN TIDUR SEBELUM...", "RAHASIA TERBONGKAR...").
    
    For each segment, also generate:
    1. A catchy **Viral Title** (Clickbait, Bahasa Indonesia).
    2. A list of 3-5 **Hashtags** (Bahasa Indonesia/English mixed is okay, but prioritize viral Indo tags like #fyp, #viralindonesia).
    3. A **Viral Hook/Detail**: A 1-2 sentence compelling description in Bahasa Indonesia that makes people curious to watch.
    
    Transcript:
    {textwrap.shorten(transcript_text, width=15000, placeholder="...(truncated)")}
    
    **RETURN JSON FORMAT ONLY**:
    [
      {{
        "start": <start_time_seconds>,
        "end": <end_time_seconds>,
        "title": "<Clickbait Title>",
        "reason": "<English Reason for selection>",
        "viral_detail": "<Bahasa Indonesia Hook>",
        "hashtags": ["#tag1", "#tag2", "#tag3"],
        "score": <virality_score_1_to_10>
      }},
      ...
    ]
    """

    try:
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "You are a viral content expert. Output strictly valid JSON."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            response_format={"type": "json_object"}
        )
        result = completion.choices[0].message.content
        data = json.loads(result)
        # Handle { "clips": [...] } or just [...]
        if isinstance(data, dict):
             if "clips" in data: return data["clips"]
             if "segments" in data: return data["segments"]
             # If keys are just the list
             return list(data.values())[0] if data else []
        return data
    except Exception as e:
        log_msg(logger, f"Groq Analysis Error: {e}")
        return []

def get_transcript_words(transcript):
    """
    Safely extracts word-level timestamps from Groq transcript object.
    Returns list of word objects/dicts.
    """
    if not transcript:
        return []
    
    # Groq returns transcript.words as a list
    if hasattr(transcript, 'words') and transcript.words:
        return transcript.words
    
    return []

def process_video_groq(video_path, n_clips=3, logger=None):
    """Pipeline: Extract -> Transcribe -> Analyze"""
    log_msg(logger, "▶️ Starting AI Pipeline...")
    
    log_msg(logger, "1️⃣ Extracting Audio...")
    audio_path = extract_audio(video_path, logger=logger)
    if not audio_path: 
        log_msg(logger, "❌ Audio extraction failed.")
        return None, []
    
    log_msg(logger, "2️⃣ Transcribing Audio (Whisper)...")
    transcript = transcribe_with_groq(audio_path, logger=logger)
    if not transcript: 
        log_msg(logger, "❌ Transcription failed.")
        return None, []
    
    log_msg(logger, "3️⃣ Analyzing Content (Llama 3)...")
    clips = analyze_transcript_with_groq(transcript, n_clips, logger=logger)
    
    # Clean up temp audio
    try: 
        video_handle = VideoFileClip(video_path)
        video_handle.close() # Ensure video is released? No, just audio.
        os.remove(audio_path)
    except: pass
    
    # Extract words safely
    words = get_transcript_words(transcript)
    
    return transcript.text, clips, words

# --- MoviePy Rendering ---

def hex_to_rgb(hex_color):
    hex_color = hex_color.lstrip('#')
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))

def save_vertical_clip(video_path, clip_data, output_path, progress_callback=None, transcript_words=None):
    """
    Crops video to 9:16 vertical, adds blurred background, and simple captions (optional).
    Uses MoviePy.
    Added: transcript_words support for burnt-in subtitles.
    """
    t_start = clip_data.get('start', clip_data.get('start_time'))
    t_end = clip_data.get('end', clip_data.get('end_time'))
    
    try:
        # Load Video
        full_clip = VideoFileClip(video_path)
        
        if t_start is None: t_start = 0.0
        if t_end is None: t_end = full_clip.duration
        
        clip = full_clip.subclip(t_start, t_end)
        
        # Target 9:16
        target_ratio = 9/16
        target_height = 1920
        target_width = 1080
        
        # 1. Prepare Main Content (Center)
        # We want to keep original aspect ratio of the video, scale it to fit width 1080
        clip_aspect = clip.w / clip.h
        
        # Standard valid vertical clip logic:
        # Resize original clip to width 1080
        video_main = clip.resize(width=target_width)
        
        # If it's too tall (unlikely for horizontal source), crop it.
        # If it's too short (horizontal source), we center it on a blurred background.
        
        # 1. Background (Blurred and Zoomed)
        # Resize to cover height 1920
        bg_clip = clip.resize(height=target_height)
        bg_clip = bg_clip.crop(x1=bg_clip.w/2 - target_width/2, width=target_width, height=target_height)
        bg_clip = bg_clip.fl_image(lambda image: cv2.GaussianBlur(image, (101, 101), 0))
        
        # 2. Main Video (Centered)
        # video_main is already width=1080.
        # Position it in the center
        video_main = video_main.set_position("center")
        
        # Combine
        final_layers = [bg_clip, video_main]
        
        # 3. Add Captions (Subtitles)
        if transcript_words and os.getenv("ENABLE_CAPTIONS", "true").lower() == "true":
            subs = generate_subtitle_clips(transcript_words, t_start, t_end)
            final_layers.extend(subs)

        final = CompositeVideoClip(final_layers, size=(target_width, target_height))
        
        # Render
        my_logger = MyBarLogger(progress_callback) if progress_callback else None
        
        final.write_videofile(
            output_path, 
            codec="libx264", 
            audio_codec="aac", 
            threads=4, 
            preset="medium",
            fps=24,
            logger=my_logger
        )
        
        return output_path
        
    except Exception as e:
        raise e
def get_caption_text_for_clip(words, clip_start, clip_end):
    """
    Extracts readable caption text for the specific clip duration.
    """
    if not words: return ""
    
    text_parts = []
    
    for w in words:
        w_start = w.start if hasattr(w, 'start') else w.get('start')
        w_end = w.end if hasattr(w, 'end') else w.get('end')
        w_word = w.word if hasattr(w, 'word') else w.get('word')
        
        if w_start is None or w_end is None:
            continue
            
        if w_end > clip_start and w_start < clip_end:
            text_parts.append(w_word.strip())
    
    return " ".join(text_parts)

def get_clip_words(words, clip_start, clip_end):
    """
    Extracts the list of word objects/dicts for the clip.
    Used for saving to DB for future re-rendering.
    """
    if not words: return []
    
    clip_words = []
    for w in words:
        w_start = w.start if hasattr(w, 'start') else w.get('start')
        w_end = w.end if hasattr(w, 'end') else w.get('end')
        
        if w_start is None or w_end is None:
            continue
            
        # Add 0.5s buffer
        if w_end > clip_start and w_start < clip_end:
             # Clone/dictify
             wd = {
                 'start': w_start,
                 'end': w_end,
                 'word': w.word if hasattr(w, 'word') else w.get('word')
             }
             clip_words.append(wd)
             
    return clip_words

def create_text_clip_image(text, fontsize=80, color='yellow', stroke_width=4, stroke_color='black'):
    """
    Creates a PIL image with text (for subtitles).
    """
    from PIL import Image, ImageDraw, ImageFont
    
    # Try to load a nice font
    try:
        font = ImageFont.truetype("arial.ttf", fontsize)
    except:
        font = ImageFont.load_default()
    
    # Calculate text size
    dummy_img = Image.new('RGBA', (1, 1))
    draw = ImageDraw.Draw(dummy_img)
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    
    # Create image with padding
    padding = 20
    img_width = text_width + padding * 2
    img_height = text_height + padding * 2
    img = Image.new('RGBA', (img_width, img_height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # Draw stroke (outline)
    x = padding
    y = padding
    draw.text((x-stroke_width, y), text, font=font, fill=stroke_color)
    draw.text((x+stroke_width, y), text, font=font, fill=stroke_color)
    draw.text((x, y-stroke_width), text, font=font, fill=stroke_color)
    draw.text((x, y+stroke_width), text, font=font, fill=stroke_color)
    draw.text((x-stroke_width, y-stroke_width), text, font=font, fill=stroke_color)
    draw.text((x+stroke_width, y+stroke_width), text, font=font, fill=stroke_color)
    draw.text((x-stroke_width, y+stroke_width), text, font=font, fill=stroke_color)
    draw.text((x+stroke_width, y-stroke_width), text, font=font, fill=stroke_color)
    
    # Draw text
    draw.text((x, y), text, font=font, fill=color)
    
    return np.array(img)

def generate_subtitle_clips(words, clip_start, clip_end, video_size=(1080, 1920)):
    """
    Generates MoviePy clips for subtitles based on word timestamps.
    """
    subtitle_clips = []
    
    if not words:
        return []

    # Filter words relevant to this clip
    clip_words = []
    for w in words:
        # Check compatibility with object or dict
        w_start = w.start if hasattr(w, 'start') else w.get('start')
        w_end = w.end if hasattr(w, 'end') else w.get('end')
        w_word = w.word if hasattr(w, 'word') else w.get('word')
        
        if w_start is None or w_end is None:
             continue
             
        if w_end > clip_start and w_start < clip_end:
            clip_words.append({
                'start': max(w_start, clip_start) - clip_start, # Relative time
                'end': min(w_end, clip_end) - clip_start,       # Relative time
                'word': w_word.strip()
            })
            
    # Create clips
    for item in clip_words:
        word_text = item['word']
        start_t = item['start']
        end_t = item['end']
        duration = end_t - start_t
        
        # Min duration for visibility
        if duration < 0.1: duration = 0.1
        
        # Create Image
        img_array = create_text_clip_image(word_text, fontsize=80, color='yellow', stroke_width=4)
        
        txt_clip = (ImageClip(img_array)
                    .set_start(start_t)
                    .set_duration(duration)
                    .set_position(('center', 1400))) # Bottom-center position
                    
        subtitle_clips.append(txt_clip)
        
    return subtitle_clips
def get_transcript_words(transcript):
    """
    Safely extracts word-level timestamps from Groq transcript object.
    Returns list of word objects/dicts.
    """
    if not transcript:
        return []
    
    # Groq returns transcript.words as a list
    if hasattr(transcript, 'words') and transcript.words:
        return transcript.words
    
    return []
