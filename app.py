import streamlit as st
import os
import time
import clipper
import database
import json
import streamlit.components.v1 as components
from dotenv import load_dotenv
import sys
import io
import tiktok_uploader
import socket
import dns.resolver

# --- NUCLEAR NETWORK FIX: Bypass System DNS entirely ---
# The environment has broken DNS (Errno -5). We manually resolve via Google DNS (8.8.8.8).
_orig_getaddrinfo = socket.getaddrinfo

def _getaddrinfo_bypassed(host, port, family=0, type=0, proto=0, flags=0):
    # Only hijack specific domains if needed, or all. Let's try to be safe.
    # If it's an IP, skip.
    try:
        # Check if already IP
        socket.inet_aton(host)
        return _orig_getaddrinfo(host, port, family, type, proto, flags)
    except:
        pass

    try:
        # Create a custom resolver pointing to Google/Cloudflare
        resolver = dns.resolver.Resolver()
        resolver.nameservers = ['8.8.8.8', '1.1.1.1'] # Google & Cloudflare
        
        # Resolve A record (IPv4)
        response = resolver.resolve(host, 'A')
        ip_address = response[0].to_text()
        
        print(f"DEBUG: Nuclear DNS Resolved {host} -> {ip_address}")
        
        # Return in format expected by socket.getaddrinfo
        # (family, type, proto, canonname, sockaddr)
        # Using AF_INET hardcoded
        return [(socket.AF_INET, type, proto, '', (ip_address, port))]
        
    except Exception as e:
        print(f"DEBUG: Nuclear DNS Failed for {host}: {e}. Falling back to system.")
        return _orig_getaddrinfo(host, port, family, type, proto, flags)

socket.getaddrinfo = _getaddrinfo_bypassed
print("DEBUG: Applied Nuclear Custom DNS Resolver (8.8.8.8)")
# -----------------------------------------------------

# --- Database Init ---
database.init_db()

# --- DNS Debug (Run once) ---
try:
    import socket
    st.write(f"<!-- DNS Check: {socket.gethostbyname('www.youtube.com')} -->")
    print(f"DEBUG: Resolved www.youtube.com to {socket.gethostbyname('www.youtube.com')}")
except Exception as e:
    print(f"DEBUG: DNS Resolution Failed: {e}")

# --- Logging Setup (Session State) ---
if 'log_capture' not in st.session_state:
    st.session_state['log_capture'] = []

# --- Navigation State ---
if 'active_tab' not in st.session_state:
    st.session_state['active_tab'] = "Analisis Baru"

# Load environment variables
load_dotenv()

# --- Configuration ---
DOWNLOAD_DIR = "downloads"
OUTPUT_DIR = "output_clips"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

# --- UI Setup ---
st.set_page_config(page_title="Auto Clipper AI (Groq)", layout="wide", page_icon="⚡")

# Custom CSS for Professional UI
st.markdown("""
<style>
    .stButton button {
        width: 100%;
        border-radius: 8px;
        font-weight: 600;
    }
    .stExpander {
        border: 1px solid #e0e0e0;
        border-radius: 8px;
    }
    .stTextInput input {
        border-radius: 8px;
    }
    div[data-testid="stSidebar"] {
        background-color: #f8f9fa;
        padding-top: 20px;
    }
</style>
""", unsafe_allow_html=True)

# --- Authentication ---
def check_password():
    """Returns `True` if the user had the correct password."""

    def password_entered():
        """Checks whether a password entered by the user is correct."""
        user = st.session_state.get("username", "")
        pwd = st.session_state.get("password", "")
        
        env_user = os.getenv("APP_USERNAME", "admin")
        env_pwd = os.getenv("APP_PASSWORD", "password")

        if user == env_user and pwd == env_pwd:
            st.session_state["password_correct"] = True
            # Don't delete immediately to be safe, or check existence before delete
            if "password" in st.session_state: del st.session_state["password"]
            if "username" in st.session_state: del st.session_state["username"]
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        # First run, show input for password.
        st.title("🔐 Login Required")
        st.text_input("Username", key="username")
        st.text_input("Password", type="password", on_change=password_entered, key="password")
        st.button("Login", on_click=password_entered)
        return False
    elif not st.session_state["password_correct"]:
        # Password failure, show input for password.
        st.title("🔐 Login Required")
        st.text_input("Username", key="username")
        st.text_input("Password", type="password", on_change=password_entered, key="password")
        st.error("😕 User not known or password incorrect")
        st.button("Login", on_click=password_entered)
        return False
    else:
        # Password correct.
        return True

if not check_password():
    st.stop()

st.title("⚡ Auto Clipper AI (Groq Fast Mode)")

# --- Modern Sidebar ---
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/3074/3074767.png", width=50)
    st.subheader("Navigation")
    
    # Modern Button Navigation
    if st.button("🏠 Analisis Baru", key="nav_new", use_container_width=True, type="primary" if st.session_state['active_tab'] == "Analisis Baru" else "secondary"):
        st.session_state['active_tab'] = "Analisis Baru"
        if 'viral_clips' in st.session_state:
             # Preserve session state if switching back? Or reset?
             # User might want to see clips. Let's not reset.
             pass
        st.rerun()
        
    if st.button("📚 Riwayat Analisis", key="nav_history", use_container_width=True, type="primary" if st.session_state['active_tab'] == "Riwayat" else "secondary"):
        st.session_state['active_tab'] = "Riwayat"
        st.rerun()

    st.divider()

    if st.session_state['active_tab'] == "Analisis Baru":
        st.caption("Settings")
        api_key = os.getenv("GROQ_API_KEY", "")
        if not api_key:
            api_key = st.text_input("Groq API Key", type="password")
            if api_key:
                os.environ["GROQ_API_KEY"] = api_key
        else:
            st.success("✅ API Ready")
        
        st.divider()
        st.caption("Configuration")
        target_clip_count = st.slider("Target Clips", 1, 10, 3)
        
        # --- Cookies Uploader for Bot Bypass ---
        st.divider()
        st.caption("🤖 Bot Verification Bypass")
        uploaded_cookies = st.file_uploader("Upload cookies.txt", type=["txt"], help="Upload cookies.txt from YouTube to bypass 'Sign in' errors.")
        if uploaded_cookies is not None:
            # Save to root as cookies.txt
            with open("cookies.txt", "wb") as f:
                f.write(uploaded_cookies.getbuffer())
            st.success("✅ Cookies saved! Restarting...")
            time.sleep(1)
            st.rerun()

        if os.path.exists("cookies.txt"):
            st.info("🍪 Cookies active")
            if st.button("Delete Cookies"):
                os.remove("cookies.txt")
                st.rerun()
        # ---------------------------------------
        
        if st.button("↻ Reset Session", use_container_width=True):
            if 'viral_clips' in st.session_state:
                del st.session_state['viral_clips']
            st.rerun()

# --- Main Logic ---
mode = st.session_state['active_tab']

if mode == "Analisis Baru":
    st.markdown("### 🚀 Mulai Analisis Video")
    st.caption("Masukkan URL YouTube untuk mulai download, transkripsi, dan analisis konten viral menggunakan AI.")
    
    youtube_url = st.text_input("YouTube URL", placeholder="https://www.youtube.com/watch?v=...", label_visibility="collapsed")
    
    col_act, col_space = st.columns([1, 4])
    with col_act:
        analyze_clicked = st.button("⚡ ANALYZE NOW", type="primary", use_container_width=True)

    # --- Clean Logs Box ---
    st.divider()
    with st.expander("📝 System Logs", expanded=True):
        log_container = st.container(height=300)
        log_placeholder = log_container.empty()
        
    class LiveLogger:
        def __init__(self, placeholder):
            self.placeholder = placeholder
            
        def debug(self, msg): self.log(msg)
        def info(self, msg): self.log(msg)
        def warning(self, msg): self.log(msg)
        def error(self, msg): self.log(msg)
        
        def log(self, msg):
            msg_str = str(msg)
            # Formatting: Ensure newlines for clarity
            clean_msg = msg_str.replace('\r', '\n')
            if not clean_msg.endswith('\n'):
                clean_msg += '\n'
                
            st.session_state['log_capture'].append(clean_msg)
            
            full_log = "".join(st.session_state['log_capture'])
            self.placeholder.text_area("Log Output", value=full_log, height=300, disabled=True, label_visibility="collapsed", key=f"log_{len(st.session_state['log_capture'])}")
            
            # Auto-Scroll
            components.html(
            f"""<script>
                const areas = window.parent.document.querySelectorAll('textarea');
                for (const area of areas) {{
                    if (area.value.length > 0) {{
                        area.scrollTop = area.scrollHeight;
                    }}
                }}
            </script>""", height=0)

    live_logger = LiveLogger(log_placeholder)

    if analyze_clicked:
        if not youtube_url:
            st.error("Please provide a valid YouTube URL.")
        elif not os.getenv("GROQ_API_KEY"):
            st.error("Groq API Key is missing.")
        else:
            status_container = st.container()
            with status_container:
                # 1. Download
                with st.status("📥 Phase 1: Downloading Video...", expanded=True) as status:
                    download_bar = st.progress(0, text="Starting Download...")
                    def update_progress(percent, text):
                        download_bar.progress(percent, text=text)

                    try:
                        video_path = clipper.download_video(
                            youtube_url, 
                            DOWNLOAD_DIR, 
                            progress_callback=update_progress,
                            logger=live_logger
                        )
                    except Exception as e:
                        video_path = None
                        live_logger.error(f"Download Error: {e}")
                        st.error(f"Download Error: {e}")
                    
                    if not video_path:
                        status.update(label="Download Failed", state="error")
                        st.stop()
                    
                    status.update(label="Download Complete!", state="complete", expanded=False)
                    st.session_state['video_path'] = video_path

                # 2. Analyze
                with st.status("🧠 Phase 2: AI Analysis...", expanded=True) as status:
                    full_text, viral_clips = clipper.process_video_groq(
                        st.session_state['video_path'], 
                        n_clips=target_clip_count,
                        logger=live_logger
                    )
                    
                    if not viral_clips:
                        status.update(label="Analysis Failed", state="error")
                        st.stop()
                    else:
                        st.success(f"Found {len(viral_clips)} viral candidates!")
                        st.session_state['viral_clips'] = viral_clips
                        status.update(label="Analysis Complete!", state="complete", expanded=False)

                # 3. Auto-Render (Phase 3 Moved Here)
                with st.status("⚙️ Phase 3: Auto-Rendering Clips...", expanded=True) as status:
                    render_bar = st.progress(0, text="Rendering Clips...")
                    
                    for i, clip in enumerate(st.session_state['viral_clips']):
                        status.write(f"Rendering #{i+1}: {clip['title']}...")
                        
                        # Sub-progress bar for the current clip
                        clip_bar = st.progress(0, text=f"Rendering Clip {i+1}...")
                        def update_clip_progress(percent):
                            clip_bar.progress(percent, text=f"Rendering Clip {i+1}: {int(percent*100)}%")

                        try:
                            video_path = st.session_state['video_path']
                            # Sanitize title
                            safe_title = "".join([c for c in clip['title'] if c.isalnum() or c in (' ','-','_')]).strip()
                            out_name = f"clip_{i+1}_{safe_title[:30]}_{int(time.time())}.mp4"
                            out_path = os.path.join(OUTPUT_DIR, out_name)
                            
                            final_clip_path = clipper.save_vertical_clip(
                                video_path, 
                                clip, 
                                out_path,
                                progress_callback=update_clip_progress
                            )

                            
                            clip['file_path'] = final_clip_path
                            live_logger.info(f"Rendered: {final_clip_path}")
                            
                        except Exception as e:
                            live_logger.error(f"Render Error Clip #{i+1}: {e}")
                        
                        render_bar.progress((i + 1) / len(st.session_state['viral_clips']))
                    
                    # Save Final Result to DB
                    try:
                        video_title = os.path.basename(st.session_state['video_path'])
                        database.save_analysis_result(youtube_url, video_title, st.session_state['video_path'], st.session_state['viral_clips'])
                        live_logger.info("Saved to History Database.")
                    except Exception as e:
                        live_logger.error(f"DB Save Error: {e}")

                    status.update(label="Rendering Complete!", state="complete", expanded=False)
            
            st.rerun()
            
    # Display Results (After Rerun)
    if 'viral_clips' in st.session_state:
        st.divider()
        st.subheader("✅ Analysis Results")
        
        r_cols = st.columns(3)
        for i, clip in enumerate(st.session_state['viral_clips']):
            if 'file_path' in clip and clip['file_path'] and os.path.exists(clip['file_path']):
                with r_cols[i % 3]:
                    with st.container(border=True):
                        st.video(clip['file_path'])
                        st.write(f"**{clip['title']}**")
                        st.caption(clip.get('viral_detail', clip['reason'])) # Show hooks
                        with open(clip['file_path'], "rb") as f:
                            st.download_button(
                                label=f"Download Clip #{i+1}",
                                data=f,
                                file_name=os.path.basename(clip['file_path']),
                                mime="video/mp4",
                                key=f"down_auto_{i}",
                                use_container_width=True
                            )
                        
                        st.divider()
                        if st.button("🎵 Upload to TikTok", key=f"tt_upload_{i}", use_container_width=True):
                            with st.spinner("Opening browser... Please login if needed."):
                                # Prepare description
                                hashtags = " ".join([f"#{t.replace('#','')}" for t in clip['hashtags']])
                                desc = f"{clip['title']}\n\n{clip['viral_detail']}\n\n{hashtags}"
                                
                                msg = tiktok_uploader.upload_video(clip['file_path'], desc)
                                st.info(msg)

elif mode == "Riwayat":
    st.title("📚 Riwayat Analisis")
    st.markdown("Daftar video yang telah dianalisis sebelumnya.")
    
    history_data = database.get_all_history()
    
    if not history_data:
        st.info("Belum ada data riwayat.")
    
    for item in history_data:
        with st.container(border=True):
            # Row 1: Header
            c_head, c_btn = st.columns([8, 1])
            with c_head:
                st.markdown(f"### {item['title']}")
                st.caption(f"📅 {item['created_at']} | 🔗 {item['youtube_url']}")
            with c_btn:
                if st.button("🗑️", key=f"del_vid_{item['id']}", help="Delete Video & Clips"):
                    # Delete Video Logic
                    v_path, c_paths = database.delete_video(item['id'])
                    
                    # Remove files
                    if v_path and os.path.exists(v_path):
                        try: os.remove(v_path)
                        except: pass
                    
                    for cp in c_paths:
                        if cp and os.path.exists(cp):
                            try: os.remove(cp) 
                            except: pass
                            
                    st.success("Video deleted.")
                    st.rerun()

            # Row 2: Content
            col_left, col_right = st.columns([1, 2])
            
            with col_left:
                if os.path.exists(item['file_path']):
                    st.video(item['file_path'])
                else:
                    st.warning("Original video missing")
            
            with col_right:
                # Vertical List of Clips (Cards)
                for clip in item['clips']:
                    with st.expander(f"🎬 {clip['title']} (Score: {clip['score']})", expanded=False):
                        # Use markdown for rich text
                        detail = clip.get('viral_detail', clip.get('reason', ''))
                        st.markdown(f"**Description:**\n{detail}")
                        
                        tags = [t.replace('#', '') for t in clip['hashtags']]
                        display_tags = " ".join([f"#{t}" for t in tags])
                        st.caption(f"Tags: {display_tags}")
                        
                        c_vid, c_act = st.columns([3, 1])
                        with c_vid:
                            if clip.get('file_path') and os.path.exists(clip['file_path']):
                                 st.video(clip['file_path'])
                            else:
                                st.info("Clip not rendered or missing.")

                            if clip.get('file_path') and os.path.exists(clip['file_path']):
                                if st.button("🎵 Upload to TikTok", key=f"tt_upload_hist_{clip['id']}"):
                                     with st.spinner("Opening browser..."):
                                        hashtags = " ".join([f"#{t.replace('#','')}" for t in clip['hashtags']])
                                        desc = f"{clip['title']}\n\n{detail}\n\n{hashtags}"
                                        msg = tiktok_uploader.upload_video(clip['file_path'], desc)
                                        st.info(msg)
                        
                        with c_act:
                             if st.button("🗑️", key=f"del_clip_{clip['id']}", help="Delete this clip"):
                                 f_path = database.delete_clip(clip['id'])
                                 if f_path and os.path.exists(f_path):
                                     try: os.remove(f_path)
                                     except: pass
                                 st.success("Clip deleted")
                                 st.rerun()
