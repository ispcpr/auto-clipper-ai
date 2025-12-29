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

# --- Database Init ---
database.init_db()

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
            if "password" in st.session_state: del st.session_state["password"]
            if "username" in st.session_state: del st.session_state["username"]
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        st.title("🔐 Login Required")
        st.text_input("Username", key="username")
        st.text_input("Password", type="password", on_change=password_entered, key="password")
        st.button("Login", on_click=password_entered)
        return False
    elif not st.session_state["password_correct"]:
        st.title("🔐 Login Required")
        st.text_input("Username", key="username")
        st.text_input("Password", type="password", on_change=password_entered, key="password")
        st.error("😕 User not known or password incorrect")
        st.button("Login", on_click=password_entered)
        return False
    else:
        return True

if not check_password():
    st.stop()

st.title("⚡ Auto Clipper AI (Groq Fast Mode)")

# --- Modern Sidebar ---
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/3074/3074767.png", width=50)
    st.subheader("Navigation")
    
    if st.button("🏠 Analisis Baru", key="nav_new", use_container_width=True, type="primary" if st.session_state['active_tab'] == "Analisis Baru" else "secondary"):
        st.session_state['active_tab'] = "Analisis Baru"
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
        
        # --- Cookies Uploader (Primary Auth) ---
        with st.expander("🍪 Login with Cookies (Required)", expanded=True):
            st.caption("Upload `cookies.txt` to bypass 'Sign in' errors.")
            uploaded_cookies = st.file_uploader("Upload cookies.txt", type=["txt"], key="cookie_uploader")
            
            if uploaded_cookies is not None:
                with open("cookies.txt", "wb") as f:
                    f.write(uploaded_cookies.getbuffer())
                st.success("✅ Cookies saved! Restarting...")
                time.sleep(1)
                st.rerun()

            if os.path.exists("cookies.txt"):
                st.success("✅ Logged In (cookies.txt active)")
                if st.button("Logout (Delete Cookies)"):
                    os.remove("cookies.txt")
                    st.rerun()
            else:
                st.warning("❌ Not Logged In")
                
            with st.expander("❓ How to get cookies.txt?"):
                st.markdown("""
                1. Install **"Get cookies.txt LOCALLY"** (Chrome/Firefox).
                2. Login to YouTube.
                3. Click extension > "Export".
                4. Upload the file here.
                """)
        # ---------------------------------------

        st.divider()
        target_clip_count = st.slider("Target Clips", 1, 10, 3)
        
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
            
            # --- CRITICAL FIX: Filter out noisy yt-dlp download logs ---
            # These logs occur 10-20 times per second and crash the Streamlit websocket
            if "[download]" in msg_str and "%" in msg_str:
                return 
            
            # Print to console for debugging crashes
            print(f"[LOG] {msg_str}")
            
            # Formatting
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
                        # Clean call to download_video (no use_oauth)
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
                    full_text, viral_clips, transcript_words = clipper.process_video_groq(
                        st.session_state['video_path'], 
                        n_clips=target_clip_count,
                        logger=live_logger
                    )
                    
                    if not viral_clips:
                        status.update(label="Analysis Failed", state="error")
                        st.stop()
                    else:
                        # Add caption text and transcript words to each clip
                        for clip in viral_clips:
                            clip['caption_text'] = clipper.get_caption_text_for_clip(
                                transcript_words, 
                                clip['start'], 
                                clip['end']
                            )
                            clip['transcript_words'] = clipper.get_clip_words(
                                transcript_words, 
                                clip['start'], 
                                clip['end']
                            )
                        
                        st.success(f"Found {len(viral_clips)} viral candidates!")
                        st.session_state['viral_clips'] = viral_clips
                        st.session_state['transcript_words'] = transcript_words
                        
                        # --- SAVE TO DB IMMEDIATELY ---
                        try:
                            v_id, c_ids = database.save_analysis_result(
                                youtube_url,
                                st.session_state.get('video_title', 'Untitled'),
                                st.session_state.get('video_path'),
                                viral_clips
                            )
                            st.session_state['current_video_id'] = v_id
                            st.session_state['current_clip_ids'] = c_ids
                            live_logger.info(f"Analysis saved to DB (ID: {v_id}). Starting render...")
                        except Exception as e:
                            live_logger.error(f"DB Save Error: {e}")
                            st.error(f"DB Save Error: {e}")

                        status.update(label="Analysis Complete!", state="complete", expanded=False)
                
                # 3. Auto-Render with Subtitles
                with st.status("⚙️ Phase 3: Rendering Clips with Subtitles...", expanded=True) as status:
                    render_bar = st.progress(0, text="Rendering Clips...")
                    
                    for i, clip in enumerate(st.session_state['viral_clips']):
                        status.write(f"Rendering #{i+1}: {clip['title']}...")
                        
                        clip_bar = st.progress(0, text=f"Rendering Clip {i+1}...")
                        def update_clip_progress(percent):
                            clip_bar.progress(percent, text=f"Rendering Clip {i+1}: {int(percent*100)}%")

                        try:
                            video_path = st.session_state['video_path']
                            safe_title = "".join([c for c in clip['title'] if c.isalnum() or c in (' ','-','_')]).strip()
                            out_name = f"clip_{i+1}_{safe_title[:30]}_{int(time.time())}.mp4"
                            out_path = os.path.join(OUTPUT_DIR, out_name)
                            
                            # Get transcript words for this clip
                            t_words = clip.get('transcript_words', [])
                            
                            final_clip_path = clipper.save_vertical_clip(
                                video_path, 
                                clip, 
                                out_path,
                                progress_callback=update_clip_progress,
                                transcript_words=t_words
                            )

                            clip['file_path'] = final_clip_path
                            live_logger.info(f"Rendered: {final_clip_path}")
                            
                            # --- UPDATE DB PATH ---
                            if 'current_clip_ids' in st.session_state:
                                try:
                                    c_id = st.session_state['current_clip_ids'][i]
                                    database.update_clip_path(c_id, final_clip_path)
                                except Exception as e:
                                    live_logger.error(f"Failed to update clip path: {e}")

                        except Exception as e:
                            live_logger.error(f"Render Error Clip #{i+1}: {e}")
                        
                        clip_bar.empty()
                        render_bar.progress((i + 1) / len(st.session_state['viral_clips']))
                    
                    st.success("✅ Rendering Complete! All clips saved to History.")
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
                        st.caption(clip.get('viral_detail', clip['reason']))
                        # Lazy Download for Analysis Results
                        dl_key = f"ready_dl_new_{i}"
                        if dl_key not in st.session_state:
                            if st.button("⬇️ Siapkan Download", key=f"prep_new_{i}", use_container_width=True):
                                st.session_state[dl_key] = True
                                st.rerun()
                        else:
                            with open(clip['file_path'], "rb") as f:
                                st.download_button(
                                    label="⬇️ Download Sekarang",
                                    data=f,
                                    file_name=os.path.basename(clip['file_path']),
                                    mime="video/mp4",
                                    key=f"down_auto_{i}",
                                    use_container_width=True
                                )
                        
                        st.divider()
                        if st.button("🎵 Upload to TikTok", key=f"tt_upload_{i}", use_container_width=True):
                            with st.spinner("Opening browser... Please login if needed."):
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
            c_head, c_btn = st.columns([8, 1])
            with c_head:
                st.markdown(f"### {item['title']}")
                st.caption(f"📅 {item['created_at']} | 🔗 {item['youtube_url']}")
            with c_btn:
                if st.button("🗑️", key=f"del_vid_{item['id']}", help="Delete Video & Clips"):
                    v_path, c_paths = database.delete_video(item['id'])
                    if v_path and os.path.exists(v_path):
                        try: os.remove(v_path)
                        except: pass
                    for cp in c_paths:
                        if cp and os.path.exists(cp):
                            try: os.remove(cp) 
                            except: pass
                    st.success("Video deleted.")
                    st.rerun()

            col_left, col_right = st.columns([1, 2])
            
            with col_left:
                if os.path.exists(item['file_path']):
                    st.video(item['file_path'])
                else:
                    st.warning("Original video missing")
            
            with col_right:
                for clip in item['clips']:
                    with st.expander(f"🎬 {clip['title']} (Score: {clip['score']})", expanded=False):
                        detail = clip.get('viral_detail', clip.get('reason', ''))
                        st.markdown(f"**Description:**\n{detail}")
                        
                        tags = [t.replace('#', '') for t in clip['hashtags']]
                        display_tags = " ".join([f"#{t}" for t in tags])
                        st.caption(f"Tags: {display_tags}")
                        
                        c_vid, c_act = st.columns([3, 1])
                        with c_vid:
                            if clip.get('file_path') and os.path.exists(clip['file_path']):
                                 st.video(clip['file_path'])
                            elif os.path.exists(item['file_path']):
                                st.info("Clip not rendered or missing.")
                                if st.button("🔄 Retry Render", key=f"retry_{clip['id']}", help="Render this clip"):
                                    retry_bar = st.progress(0, text="Starting render...")
                                    def update_retry_progress(percent):
                                        retry_bar.progress(percent, text=f"Rendering: {int(percent*100)}%")
                                    
                                    try:
                                        video_path = item['file_path']
                                        safe_title = "".join([c for c in clip['title'] if c.isalnum() or c in (' ','-','_')]).strip()
                                        out_name = f"clip_{clip['id']}_{safe_title[:30]}_{int(time.time())}.mp4"
                                        out_path = os.path.join(OUTPUT_DIR, out_name)
                                        
                                        final_path = clipper.save_vertical_clip(
                                            video_path,
                                            {'start': clip['start_time'], 'end': clip['end_time']},
                                            out_path,
                                            progress_callback=update_retry_progress
                                        )
                                        
                                        retry_bar.empty()
                                        if final_path:
                                            database.update_clip_path(clip['id'], final_path)
                                            st.success("✅ Rendered!")
                                            st.rerun()
                                    except Exception as e:
                                        retry_bar.empty()
                                        st.error(f"Retry failed: {e}")
                            else:
                                st.warning("Source video missing")

                            if clip.get('file_path') and os.path.exists(clip['file_path']):
                                # Lazy Download for History
                                dl_hist_key = f"ready_dl_hist_{clip['id']}"
                                
                                if dl_hist_key not in st.session_state:
                                    if st.button("⬇️ Siapkan Download", key=f"prep_hist_{clip['id']}", use_container_width=True):
                                        st.session_state[dl_hist_key] = True
                                        st.rerun()
                                else:
                                    with open(clip['file_path'], "rb") as f:
                                        st.download_button(
                                            label="⬇️ Download Sekarang",
                                            data=f,
                                            file_name=os.path.basename(clip['file_path']),
                                            mime="video/mp4",
                                            key=f"down_hist_{clip['id']}",
                                            use_container_width=True
                                        )

                                if st.button("🎵 Upload to TikTok", key=f"tt_upload_hist_{clip['id']}", use_container_width=True):
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
