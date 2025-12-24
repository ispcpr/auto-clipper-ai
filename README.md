# ⚡ Auto Clipper AI (Groq Fast Mode)

Transform long YouTube videos into viral short-form clips (TikTok/Reels/Shorts) automatically using AI.

## 🚀 Features

*   **Fast Download**: Uses `yt-dlp` with optimizations for speed.
*   **AI Transcription**: Ultrafast transcription using **Groq Whisper Large V3**.
*   **Viral Analysis**: Uses **Groq Llama 3 (70B)** to analyze transcripts, find the most engaging segments, and generate viral titles/hooks in **Bahasa Indonesia**.
*   **Auto-Reframing**: Automatically crops videos to 9:16 vertical format with blurred background padding.
*   **Embedded Captions**: Adds subtitles directly to the video.
*   **TikTok Uploader**: Helper to upload directly (requires login).
*   **Bot Bypass**: Built-in support for `cookies.txt` import to bypass YouTube's "Sign in to confirm you're not a bot" errors.

## 🛠️ Prerequisites

*   **Python 3.10+** (Recommend 3.11)
*   **FFmpeg** installed and added to system PATH.
    *   *Windows*: Download from [gyan.dev](https://www.gyan.dev/ffmpeg/builds/), extract, and add `bin` folder to Path.
    *   *Linux*: `sudo apt install ffmpeg`

## 📦 Installation

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/ispcpr/auto-clipper-ai.git
    cd auto-clipper-ai
    ```

2.  **Create a Virtual Environment (Recommended):**
    ```bash
    python -m venv venv
    # Windows
    venv\Scripts\activate
    # Mac/Linux
    source venv/bin/activate
    ```

3.  **Install Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

## ⚙️ Configuration

1.  Copy the example environment file:
    ```bash
    cp .env.example .env
    # or manually rename .env.example to .env
    ```

2.  Edit `.env` and fill in your keys:
    ```ini
    GROQ_API_KEY=gsk_xxxxxxxxxxxx
    
    # App Login
    APP_USERNAME=admin
    APP_PASSWORD=password
    ```

## ▶️ How to Run

1.  **Start the Application:**
    ```bash
    streamlit run app.py
    ```

2.  **Login:**
    Open your browser at `http://localhost:8501`.
    Login with the username/password you set in `.env`.

3.  **Analyze a Video:**
    *   Paste a YouTube URL.
    *   Click **Analyze Now**.
    *   Wait for the AI to download, transcribe, and generate clips.

## ⚠️ Troubleshooting

**Error: "Sign in to confirm you're not a bot"**

This happens if YouTube blocks your IP address. To fix uses **Cookies**:

1.  Install Chrome Extension: [Get cookies.txt LOCALLY](https://chrome.google.com/webstore/detail/get-cookiestxt-locally/cclelndahbckbenkjhflccgomjciDhdb).
2.  Open YouTube.com (make sure you are logged in).
3.  Click the extension to download `cookies.txt`.
4.  In the Auto Clipper App sidebar, look for **"Bot Verification Bypass"**.
5.  Upload your `cookies.txt` file.
6.  Restart the analysis.
