import streamlit as st
import requests
import time
import base64
from pathlib import Path

# =====================================================================
# CONFIG (NO st.secrets — Safe & Local)
# =====================================================================

API_URL = "http://127.0.0.1:8000"      # Backend URL
ADMIN_KEY_ENV = ""                     # No secrets usage
USE_OPENAI = False                     # backend controls via .env

st.set_page_config(
    page_title="Business AI Assistant",
    layout="wide",
    initial_sidebar_state="expanded"
)

# =====================================================================
# Helpers
# =====================================================================

def download_text_file(text, filename="chat_history.txt"):
    b64 = base64.b64encode(text.encode()).decode()
    return f'<a href="data:text/plain;base64,{b64}" download="{filename}">📥 Download Chat History</a>'

def highlight_text(text, terms):
    text = text.replace("<", "&lt;").replace(">", "&gt;")
    for term in terms:
        if len(term) < 3:
            continue
        text = text.replace(term, f"<mark>{term}</mark>")
        text = text.replace(term.capitalize(), f"<mark>{term.capitalize()}</mark>")
    return text

# =====================================================================
# SIDEBAR (Admin + Upload + Settings)
# =====================================================================

st.sidebar.title("⚙️ Admin & Document Upload")

# Login system
if "user" not in st.session_state:
    st.session_state["user"] = "user"

mode = st.sidebar.radio("Mode", ["User", "Admin"])

if mode == "Admin":
    admin_key = st.sidebar.text_input("Enter Admin Key", type="password")

    # Load admin key from .env
    env_key = ""
    if Path(".env").exists():
        env_text = Path(".env").read_text()
        if "ADMIN_API_KEY=" in env_text:
            env_key = env_text.split("ADMIN_API_KEY=")[1].splitlines()[0].strip()

    if admin_key == env_key:
        st.sidebar.success("Admin authenticated")
        st.session_state["user"] = "admin"
    else:
        st.sidebar.info("Enter valid admin key")
else:
    st.session_state["user"] = "user"

# Upload multiple files
st.sidebar.markdown("### 📂 Upload PDFs / Text Files")
files = st.sidebar.file_uploader("Upload multiple files", type=["pdf", "txt"], accept_multiple_files=True)

if files and st.session_state["user"] == "admin":
    for f in files:
        resp = requests.post(
            f"{API_URL}/ingest",
            files={"file": (f.name, f.getvalue())},
            headers={"key": admin_key},
            timeout=120
        )
        if resp.ok:
            st.sidebar.success(f"Uploaded {f.name} ({resp.json()['chunks']} chunks)")
        else:
            st.sidebar.error(f"Upload error: {resp.text}")

# Settings
st.sidebar.markdown("---")
top_k = st.sidebar.slider("Top-K Chunks", 1, 10, 3)
enable_tts = st.sidebar.checkbox("🔊 Assistant Voice Output", True)
enable_stt = st.sidebar.checkbox("🎤 Voice Input", True)
st.sidebar.markdown("---")

# =====================================================================
# STT Button (Browser)
# =====================================================================

if enable_stt:
    st.markdown("""
    <script>
    function startSTT() {
        if (!('webkitSpeechRecognition' in window)) {
            alert("Speech recognition requires Chrome.");
            return;
        }
        const recog = new webkitSpeechRecognition();
        recog.lang = "en-US";
        recog.onresult = function(e) {
            const text = e.results[0][0].transcript;
            const input = document.getElementById("voice_input");
            input.value = text;
            input.dispatchEvent(new Event("input", { bubbles: true }));
        }
        recog.start();
    }
    </script>

    <button onclick="startSTT()" style="padding:8px 15px;background:#0052cc;color:white;border:none;border-radius:5px;">
        🎤 Speak your question
    </button>

    <input id="voice_input" style="opacity:0;height:0px" />
    """, unsafe_allow_html=True)

# =====================================================================
# Viewer (Right column)
# =====================================================================

left_col, right_col = st.columns([2, 1])

with right_col:
    st.header("📄 Retrieved Chunks (Highlighted)")

    if "retrieved" not in st.session_state:
        st.session_state["retrieved"] = []

    if st.session_state["retrieved"]:
        for chunk in st.session_state["retrieved"]:
            highlighted = highlight_text(chunk["text"], st.session_state.get("query_terms", []))
            st.markdown(
                f"<div style='background:#f4f4f4;padding:10px;border-radius:8px'>{highlighted}</div><br>",
                unsafe_allow_html=True
            )
    else:
        st.info("Ask something to show relevant chunks.")

# =====================================================================
# Chat (Left column)
# =====================================================================

with left_col:
    st.header("💬 AI Assistant")

    if "messages" not in st.session_state:
        st.session_state["messages"] = []

    # Display chat
    for msg in st.session_state["messages"]:
        if msg["role"] == "user":
            st.markdown(
                f"<div style='text-align:right'><div style='display:inline-block;background:#e1ffc7;padding:10px;border-radius:10px'>{msg['content']}</div></div>",
                unsafe_allow_html=True
            )
        else:
            st.markdown(
                f"<div style='text-align:left'><div style='display:inline-block;background:white;padding:10px;border-radius:10px;border:1px solid #ddd'>{msg['content']}</div></div>",
                unsafe_allow_html=True
            )

    # Input field
    user_input = st.chat_input("Ask anything...")

    if user_input:
        st.session_state["messages"].append({"role": "user", "content": user_input})
        st.rerun()

    # Run query after user message
    if st.session_state["messages"] and st.session_state["messages"][-1]["role"] == "user":
        query = st.session_state["messages"][-1]["content"]

        # show typing animation
        typing = st.empty()
        typing.markdown("**🤖 Assistant is typing...**")

        resp = requests.post(
            f"{API_URL}/query",
            json={"query": query, "top_k": top_k},
            timeout=60
        )

        try:
            data = resp.json()
        except:
            typing.empty()
            st.session_state["messages"].append({
                "role": "assistant",
                "content": f"❌ Backend error: {resp.text}"
            })
            st.rerun()

        typing.empty()

        # Extract retrieved chunks
        docs = data.get("results", [])
        docs = docs[0] if docs and isinstance(docs[0], list) else docs

        st.session_state["retrieved"] = [{"text": d, "source": "unknown"} for d in docs]
        st.session_state["query_terms"] = query.split()

        # Streaming answer
        answer = data.get("answer", "No answer.")
        stream_box = st.empty()
        streamed = ""

        for i in range(0, len(answer), 50):
            streamed += answer[i:i+50]
            stream_box.markdown(
                f"<div style='background:white;padding:10px;border-radius:8px;border:1px solid #ddd'>{streamed}</div>",
                unsafe_allow_html=True
            )
            time.sleep(0.03)

        # TTS
        if enable_tts:
            safe_text = answer.replace("'", "\\'")
            st.markdown(f"""
            <script>
                let msg = new SpeechSynthesisUtterance('{safe_text}');
                speechSynthesis.speak(msg);
            </script>
            """, unsafe_allow_html=True)

        # save assistant reply
        st.session_state["messages"].append({"role": "assistant", "content": answer})
        st.rerun()
