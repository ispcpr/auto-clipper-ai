import yt_dlp
import os

url = "https://www.youtube.com/watch?v=jNQXAC9IVRw"

print("Testing download with EDGE cookies...")
opts = {
    'cookiesfrombrowser': ('edge',),
    'outtmpl': 'test_edge_%(id)s.%(ext)s',
    'quiet': False,
    'verbose': True
}

try:
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])
    print("SUCCESS: Edge worked.")
except Exception as e:
    print(f"FAILURE: Edge failed: {e}")
