import clipper
import os
import shutil

url = "https://www.youtube.com/watch?v=jNQXAC9IVRw"

def test_engine(engine_name):
    print(f"\n--- Testing Engine: {engine_name} ---")
    try:
        path = clipper.download_video(url, output_dir=f"test_{engine_name}", engine=engine_name)
        if path and os.path.exists(path):
            print(f"SUCCESS: {engine_name} downloaded to {path}")
            return True
        else:
            print(f"FAILURE: {engine_name} returned None or file missing.")
            return False
    except Exception as e:
        print(f"FAILURE: {engine_name} Exception: {e}")
        return False

# Test pytubefix
test_engine("pytubefix")

# Test Cobalt
test_engine("cobalt")
