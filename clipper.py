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
import socket

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
        # Every time the logger updates, this function is called.
        # 'bar' is the name of the bar (e.g. 't')
        # 'value' is the current value
        # 'attr' might be 'total' etc.
        # We only care about the main progress bar usually named 't' (time) for video writing
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

# --- 1. Downloading the YouTube Video ---
def download_video(youtube_url, output_dir="downloads", progress_callback=None, logger=None):
    """
    Downloads a YouTube video to the specified directory.
    Returns the absolute path to the downloaded file.
    """
    os.makedirs(output_dir, exist_ok=True)
    
    # Check if URL is valid
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
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            log_msg(logger, f"Downloading {youtube_url}...")
            # Extract info first without downloading to get filename reliably? 
            # Actually standard flow is fine if we catch the error.
            info_dict = ydl.extract_info(youtube_url, download=True)
            video_filename = ydl.prepare_filename(info_dict)
            abs_path = os.path.abspath(video_filename)
            log_msg(logger, f"Video downloaded to: {abs_path}")
            return abs_path
    except Exception as e:
        log_msg(logger, f"Error downloading video: {e}")
        # WinError 32 Workaround
        # Check if the file actually exists despite the error
        # We need to re-prepare filename to check
        try:
             with yt_dlp.YoutubeDL(ydl_opts) as ydl: # Re-init to get filename
                info = ydl.extract_info(youtube_url, download=False)
                potential_file = ydl.prepare_filename(info)
                if os.path.exists(potential_file):
                    log_msg(logger, f"WinError workaround: Found {potential_file}. Proceeding.")
                    return os.path.abspath(potential_file)
        except:
             pass
        return None
        return None

# --- GROQ PIPELINE: Audio Extraction -> Whisper -> Llama3 ---

def extract_audio(video_path, output_audio_path="temp_audio.mp3", logger=None):
    """Extracts audio from video for fast upload. Compresses to 32k mono to save size."""
    log_msg(logger, f"Extracting audio from {video_path}...")
    try:
        video = VideoFileClip(video_path)
        # Use 32k bitrate and mono channel to keep file size small (Groq limit is ~25MB)
        # MoviePy prints to stdout by default, hard to redirect without capture, 
        # but we can try to silence it or let it print (which won't go to logger automatically unless we capture stdout)
        video.audio.write_audiofile(
            output_audio_path, 
            codec='mp3', 
            bitrate='32k',
            ffmpeg_params=["-ac", "1"], # Mono
            verbose=False, 
            logger=None # Silence moviepy logger or pass None
        )
        
        # Check size
        size_mb = os.path.getsize(output_audio_path) / (1024 * 1024)
        log_msg(logger, f"Audio extracted: {output_audio_path} (Size: {size_mb:.2f} MB)")
        
        if size_mb > 25:
            log_msg(logger, "Warning: Audio file is still larger than 25MB. Transcription might fail.")
            
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
    
    prompt = f"""
    You are a professional video editor and content strategist. 
    Analyze the following video transcript (Duration: ~{int(duration)} seconds).
    
    Identify the **top {n_clips} most viral/engaging segments** suitable for TikTok/Reels/Shorts.
    Each segment should be between 15 and 60 seconds long.
    
    **CRITICAL INSTRUCTION**: 
    - The output **MUST BE IN BAHASA INDONESIA**.
    - The Titles must be **CLICKBAIT** and extremely viral (e.g., "TERNYATA...", "JANGAN TIDUR SEBELUM...", "RAHASIA TERBONGKAR...").
    
    For each segment, also generate:
    1. A catchy **Viral Title** (Clickbait, Bahasa Indonesia).
    2. A list of 3-5 **Hashtags** (Bahasa Indonesia/English mixed is okay, but prioritize viral Indo tags like #fyp, #viralindonesia).
    3. A **Viral Hook/Detail**: A 1-2 sentence compelling description in Bahasa Indonesia that makes people curious to watch.
    
    Transcript:
    \"\"\"{transcript_text[:25000]}\"\"\" (Truncated if too long)
    
    Return a strictly VALID JSON list of objects.
    Structure:
    [
    {{
            "start_time": <float seconds>,
            "end_time": <float seconds>,
            "score": <1-10>,
            "reason": "<technical reason for selection>",
            "viral_detail": "<compelling hook/caption for the user>",
            "title": "<Clickbait Title in Bahasa Indonesia>",
            "hashtags": ["#tag1", "#tag2"]
    }}
    ]
    """
    
    try:
        chat_completion = client.chat.completions.create(
            messages=[
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
            model="llama-3.3-70b-versatile",
            temperature=0.7,
            max_tokens=2048,
            stream=False,
            response_format={"type": "json_object"}
        )
        
        result = chat_completion.choices[0].message.content
        data = json.loads(result)
        
        if isinstance(data, dict):
            keys = list(data.keys())
            if keys: data = data[keys[0]]
                
        final_clips = []
        if isinstance(data, list):
            for item in data:
                # Map back words to this segment if available
                segment_words = []
                if hasattr(transcript_obj, 'words'):
                        start = float(item.get("start_time", 0))
                        end = float(item.get("end_time", 0))
                        try:
                            # Filter words in this range
                            all_words = transcript_obj.words if isinstance(transcript_obj.words, list) else []
                            segment_words = []
                            for w in all_words:
                                w_start = w.get('start') if isinstance(w, dict) else w.start
                                w_end = w.get('end') if isinstance(w, dict) else w.end
                                if w_start >= start and w_end <= end:
                                    segment_words.append(w)
                        except:
                            pass

                final_clips.append({
                    "start": item.get("start_time"),
                    "end": item.get("end_time"),
                    "text": item.get("quote", ""),
                    "score": item.get("score"),
                    "reason": item.get("reason"),
                    "viral_detail": item.get("viral_detail", item.get("reason", "")), # Fallback to reason
                    "title": item.get("title", "Untitled Clip"),
                    "hashtags": item.get("hashtags", []),
                    "words": segment_words
                })
        
        return final_clips
    except Exception as e:
        log_msg(logger, f"Groq Analysis error: {e}")
        return []

def process_video_groq(video_path, n_clips=3, logger=None):
    """Orchestrates the Groq Fast Pipeline."""
    
    # 1. Extract Audio
    audio_path = os.path.join(os.path.dirname(video_path), "temp_groq_audio.mp3")
    if not extract_audio(video_path, audio_path, logger=logger):
        return None, []
        
    try:
        # 2. Transcribe
        transcript_obj = transcribe_with_groq(audio_path, logger=logger)
        if not transcript_obj:
            return None, []
            
        full_text = transcript_obj.text
        duration = transcript_obj.duration
        
        # 3. Analyze
        # Pass the full object, not just text, so we can access duration and words
        clips = analyze_transcript_with_groq(transcript_obj, n_clips, logger=logger)
        
        return transcript_obj.text, clips
        
    finally:
            if os.path.exists(audio_path):
                os.remove(audio_path)


# --- HELPERS for PIL Text ---
def create_text_clip_pil(text, fontsize=60, color='yellow', font_path='Arial', stroke_color='black', stroke_width=3, size=None):
    """
    Creates an ImageClip with text using PIL to avoid ImageMagick requirement.
    """
    # 1. Create a dummy image to calculate text size or use provided size
    if size is None:
        size = (1000, 200) # Default canvas
    
    # Try loading a better font, default to default if fails
    try:
        # On Windows 'arial.ttf' usually works if in system path or just 'arial' depending on PIL version
        font = ImageFont.truetype("arial.ttf", fontsize)
    except IOError:
        try:
             font = ImageFont.truetype("Arial.ttf", fontsize)
        except:
             font = ImageFont.load_default()
             # Print warning? 
    
    # Measure text size (basic)
    # PIL 9.2.0 preferred: font.getbbox(text) -> (left, top, right, bottom)
    # Older: font.getsize(text) -> (width, height)
    
    # We will create a transparent image
    img = Image.new('RGBA', size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # Draw Text with Stroke manually (simple version)
    # PIL doesn't support complex strokes easily, so we draw multiple times
    
    x, y = size[0] // 2, size[1] // 2
    
    # Center text alignment
    # We need to calculate text width/height to center it properly
    try:
        left, top, right, bottom = font.getbbox(text)
        w = right - left
        h = bottom - top
    except:
        w, h = draw.textsize(text, font=font)
        
    # Adjustment for centering
    # This centers based on the provided size
    # x = (size[0] - w) / 2
    # y = (size[1] - h) / 2
    
    # Actually ImageDraw.text anchor='mm' does centering if supported
    
    # Draw Stroke
    if stroke_width > 0:
        for adj_x in range(-stroke_width, stroke_width+1):
            for adj_y in range(-stroke_width, stroke_width+1):
                draw.text((x+adj_x, y+adj_y), text, font=font, fill=stroke_color, anchor="mm")

    # Draw Main Text
    draw.text((x, y), text, font=font, fill=color, anchor="mm")
    
    # Convert to numpy
    numpy_img = np.array(img)
    
    return ImageClip(numpy_img)

# --- 9. Video Extraction + Blurred Background ---
def save_vertical_clip(video_path, segment, output_path, blur_intensity=51, progress_callback=None):
    """
    Creates a 9:16 vertical video with blurred background and subtitles.
    """
    print(f"Processing clip: {output_path}")
    target_w, target_h = 1080, 1920
    
    try:
        with VideoFileClip(video_path) as video:
            start = float(segment["start"])
            end = float(segment["end"])
            
            # Extract the subclip
            clip = video.subclip(start, end)
            
            # 1. Prepare Main Content (Center)
            clip_aspect = clip.w / clip.h
            target_aspect = target_w / target_h
            
            if clip_aspect > target_aspect:
                # Video is wider than 9:16 (e.g. 16:9). Fit to width.
                main_clip = resize(clip, width=target_w)
            else:
                main_clip = resize(clip, height=target_h)
            
            # 2. Prepare Background (Blurred)
            # Resize logic for background to fill screen
            if clip_aspect > target_aspect:
                bg_clip = resize(clip, height=target_h)
            else:
                bg_clip = resize(clip, width=target_w)
                
            # Crop to fill
            bg_clip = bg_clip.crop(
                x_center=bg_clip.w/2, 
                y_center=bg_clip.h/2, 
                width=target_w, 
                height=target_h
            )
            
            # Blur
            bg_clip = bg_clip.fl_image(lambda image: cv2.GaussianBlur(image, (blur_intensity, blur_intensity), 0))
            
            # Darken Background (Dimming) to make main clip pop
            # Create a black overlay
            dim_clip = ColorClip(size=(target_w, target_h), color=(0,0,0)).set_opacity(0.6).set_duration(bg_clip.duration)
            bg_clip = CompositeVideoClip([bg_clip, dim_clip])
            
            # 3. Composite
            # Add small margin/padding to main clip so it looks cleaner
            if clip_aspect > target_aspect:
                 main_clip = resize(clip, width=target_w - 60) # 30px padding each side
            else:
                 main_clip = resize(clip, height=target_h - 60)
                 
            video_comp = CompositeVideoClip([
                bg_clip,
                main_clip.set_position("center")
            ])
            
            # 4. Add Captions (PIL TextClip approach)
            subtitle_clips = []
            if "words" in segment and len(segment["words"]) > 0:
                 words = segment["words"]
                 # Group words into chunks (e.g. 3-5 words at a time)
                 chunk_size = 4
                 
                 for i in range(0, len(words), chunk_size):
                     chunk = words[i:i+chunk_size]
                     
                     # Robustly access attributes (dict or object)
                     chunk_text = []
                     c_start = None
                     c_end = None
                     
                     for w in chunk:
                         w_word = w.get('word') if isinstance(w, dict) else w.word
                         w_start = w.get('start') if isinstance(w, dict) else w.start
                         w_end = w.get('end') if isinstance(w, dict) else w.end
                         
                         chunk_text.append(w_word)
                         if c_start is None: c_start = w_start
                         c_end = w_end
                         
                     txt = " ".join(chunk_text).strip()
                     
                     # Relative timestamps
                     t_start = c_start - start 
                     t_end = c_end - start
                     
                     # Clamp
                     t_start = max(0, t_start)
                     t_end = min(video_comp.duration, t_end)
                     
                     if t_end > t_start:
                         try:
                             # Use PIL Text Generator
                             # Pass explicit size to ensure we have enough room
                             # TikTok Safe Zone: Avoid right side (buttons) and bottom description
                             # Reduce width to avoid right icons (~120px) + left padding
                             safe_width = target_w - 240
                             
                             txt_clip = create_text_clip_pil(
                                 txt,
                                 fontsize=55, # Slightly smaller for safety
                                 color='yellow',
                                 stroke_color='black',
                                 stroke_width=3,
                                 size=(safe_width, 250) # Fixed height strip
                             )
                             
                             # Position: Center, Higher up to avoid TikTok bottom overlay (~bottom 25-30% is risky)
                             # 1920 * 0.65 = ~1250
                             txt_clip = txt_clip.set_position(('center', 1250)).set_start(t_start).set_end(t_end)
                             subtitle_clips.append(txt_clip)
                         except Exception as e: 
                             print(f"Subtitle error: {e}")
                             break

            if subtitle_clips:
                final = CompositeVideoClip([video_comp] + subtitle_clips)
            else:
                final = video_comp

            # Configure Logger
            my_logger = None
            if progress_callback:
                my_logger = MyBarLogger(progress_callback)
            else:
                my_logger = 'bar' # Default moviepy logger

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
        print(f"Error processing clip: {e}")
        return None
