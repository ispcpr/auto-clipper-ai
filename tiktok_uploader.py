import time
import os
import urllib.parse
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.options import Options

def upload_video(video_path, description):
    """
    Opens a browser window to upload video to TikTok.
    
    Args:
        video_path (str): Absolute path to the video file.
        description (str): Description/Caption for the video.
    
    Returns:
        str: Status message.
    """
    if not os.path.exists(video_path):
        return f"Error: File not found {video_path}"

    try:
        # Setup Chrome Options
        chrome_options = Options()
        # Keep browser open even after script ends (for manual post/login)
        chrome_options.add_experimental_option("detach", True)
        
        # Suppress logging
        chrome_options.add_argument("--log-level=3")
        
        # Initialize Driver
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        
        # 1. Go to Upload Page
        driver.get("https://www.tiktok.com/upload?lang=en")
        
        print("Waiting for upload page...")
        
        # Wait for file input or login redirect
        # We can't easily detect login state perfectly, but we can look for the file input.
        # If it's not there after a while, it might be login screen.
        
        try:
            # Wait up to 60 seconds mostly for the user to potentially login if redirected
            # TikTok usually redirects to login if not authenticated.
            
            # Check if we are on login page by URL or element?
            # Ideally, we just wait for the file input to be present.
            # If the user is not logged in, they will see login page. 
            # We can print a meaningful message.
            
            file_input = WebDriverWait(driver, 60).until(
                EC.presence_of_element_located((By.XPATH, "//input[@type='file']"))
            )
            
            # 2. Upload File
            # Send keys to the hidden file input
            file_input.send_keys(video_path)
            print("File uploading...")
            
            # 3. Set Caption
            # Wait for the editor to appear (iframe or div text editor)
            # TikTok's editor selector changes often. 
            # Common structure: A contenteditable div.
            
            # Wait for upload to process enough for caption area to be ready
            # Usually looking for specific class or role
            
            caption_box = WebDriverWait(driver, 30).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".public-DraftEditor-content, .bg-container")) # Fallback/generic
            )
            
            # The caption box might be complicated. 
            # Let's try to focus and send keys, or just let user do it if it fails.
            try:
                # Clear existing (usually checks/filenames)?
                # TikTok auto-fills filename.
                
                # Clicking it first
                caption_box.click()
                
                # Use ActionChains to be safe?
                actions = webdriver.ActionChains(driver)
                actions.move_to_element(caption_box).click().pause(0.5)
                
                # Select all and replace? Or just append?
                # Appending is safer.
                actions.send_keys(" " + description).perform()
                
                print("Caption added.")
                
            except Exception as e:
                print(f"Could not auto-fill caption (User must do it): {e}")

            return "Browser opened! Please Login (if needed) and click 'Post'."

        except Exception as e:
            # Likely timed out waiting for input -> User needs to login or slow internet
            return "Browser opened. Please Login and then upload manually if automation timed out."

    except Exception as e:
        return f"Failed to launch browser: {e}"
