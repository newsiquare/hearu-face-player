"""
face_client.py — drive the running face_player from your pipeline.

face_player.py opens a TCP command hook on 127.0.0.1:8765. This module wraps it.
    import face_client as face
    face.set_state("listening")
    face.speak("/tmp/reply.wav", emotion="happy")
    face.stop()
"""
import socket, json, os, shutil, subprocess, tempfile

HOST, PORT = "127.0.0.1", 8765

def _send(cmd):
    try:
        with socket.create_connection((HOST, PORT), timeout=1.0) as s:
            s.sendall((json.dumps(cmd) + "\n").encode())
    except OSError as e:
        print("[face_client] send failed:", e)

def set_state(name):                 _send({"cmd": "state", "name": name})
def speak(wav, emotion="speaking"):  _send({"cmd": "speak", "emotion": emotion, "wav": wav})
def stop():                          _send({"cmd": "stop"})

# Map whatever labels your LLM / emotion classifier emits -> the 5 face states.
# Edit freely. Unknown labels fall back to "speaking" (neutral talking).
EMOTION_MAP = {
    "happy": "happy", "joy": "happy", "positive": "happy", "excited": "happy",
    "sad": "sad", "sorrow": "sad", "grief": "sad",
    "dejected": "dejected", "down": "dejected", "depressed": "dejected",
    "discouraged": "dejected", "tired": "dejected",
    "angry": "angry", "anger": "angry", "frustrated": "angry", "annoyed": "angry",
    "neutral": "speaking", "calm": "speaking", "informative": "speaking",
}
def to_face_emotion(label, default="speaking"):
    return EMOTION_MAP.get((label or "").strip().lower(), default)

def ensure_wav16(path):
    """
    The player analyses the wav's volume to drive the mouth and plays it via SDL.
    Best input is a 16-bit PCM wav. If your TTS outputs mp3/ogg/odd formats,
    this converts to 16-bit PCM mono (needs ffmpeg, or the soundfile package).
    """
    if os.path.splitext(path)[1].lower() == ".wav":
        return path
    out = os.path.join(tempfile.gettempdir(), "face_tts.wav")
    if shutil.which("ffmpeg"):
        subprocess.run(["ffmpeg", "-y", "-i", path, "-ac", "1", "-ar", "22050",
                        "-sample_fmt", "s16", out], check=True, capture_output=True)
        return out
    try:
        import soundfile as sf
        data, sr = sf.read(path)
        if getattr(data, "ndim", 1) > 1:
            data = data.mean(axis=1)
        sf.write(out, data, sr, subtype="PCM_16")
        return out
    except Exception as e:
        print("[face_client] convert failed, using original:", e)
        return path
