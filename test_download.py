import clipper
import os
import shutil

# Test URL (short video)
url = "https://www.youtube.com/watch?v=jNQXAC9IVRw" # Me at the zoo (very short)

print("Testing download with new cookie logic...")
try:
    path = clipper.download_video(url, output_dir="downloads_test")
    if path and os.path.exists(path):
        print(f"SUCCESS: Video downloaded to {path}")
        # Clean up
        dir_path = os.path.dirname(path)
        shutil.rmtree(dir_path)
        print("Cleanup complete.")
    else:
        print("FAILURE: Download returned None or file missing.")
except Exception as e:
    print(f"FAILURE: Exception occurred: {e}")
