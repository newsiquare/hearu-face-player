"""
example_pipeline.py — end-to-end skeleton tying your STT/LLM/TTS to the face.

Run order:
    1)  python3 ../face_player.py          # in another terminal (opens the hook)
    2)  python3 example_pipeline.py        # this file

As shipped it runs in MOCK mode (keyboard input + synth/espeak voice) so you can
watch the full state cycle immediately. Replace the four functions marked
"# >>> REPLACE" with your real components and you're done.
"""
import os, time, wave, subprocess, tempfile
import numpy as np
import face_client as face


# ============================================================
# >>> REPLACE these four with your real STT / LLM / TTS hooks
# ============================================================
def wait_for_wake():
    """Block until the user starts talking (VAD / wake word)."""
    input("\n[MOCK] 按 Enter 模擬『使用者開始說話』… ")

def record_and_transcribe():
    """Record until the user stops, return transcribed text ('' if nothing)."""
    return input("[MOCK STT] 輸入使用者說的話： ").strip()

def think(user_text):
    """Your LLM. Return (reply_text, emotion_label)."""
    t = user_text.lower()
    if any(w in user_text for w in ("難過", "傷心", "哭", "sad")):
        return "我聽到了，這一定很不好受，我會陪著你。", "sad"
    if any(w in user_text for w in ("生氣", "氣", "angry")):
        return "這真的太過分了，換作是我也會很不平。", "angry"
    if any(w in user_text for w in ("累", "沒力", "提不起", "down")):
        return "聽起來你真的很累了，我們慢慢來，不急。", "dejected"
    if any(w in user_text for w in ("開心", "高興", "好棒", "happy")):
        return "太好了！聽到你這麼說我也很開心！", "happy"
    return "好的，我幫你看看這件事。", "neutral"

def synthesize(reply_text):
    """Your TTS. Return a path to an audio file (wav best)."""
    return _mock_tts(reply_text)
# ============================================================


def _mock_tts(text):
    """Demo voice: espeak-ng if present, else a syllable-shaped tone wav."""
    path = os.path.join(tempfile.gettempdir(), "pipeline_tts.wav")
    try:
        subprocess.run(["espeak-ng", "-v", "cmn", "-w", path, text],
                       check=True, capture_output=True, timeout=8)
        return path
    except Exception:
        sr, secs = 22050, max(1.2, min(4.0, len(text) * 0.18))
        t = np.linspace(0, secs, int(sr * secs), endpoint=False)
        env = (np.sin(2 * np.pi * 6 * t) * 0.5 + 0.5) ** 1.5 * (np.random.rand(len(t)) > 0.05)
        sig = ((0.25 * np.sin(2 * np.pi * 150 * t)) * env * 0.6 * 32767).astype(np.int16)
        with wave.open(path, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr); w.writeframes(sig.tobytes())
        return path


def converse_once():
    wait_for_wake()
    face.set_state("listening")                      # 偵測到語音
    user_text = record_and_transcribe()
    if not user_text:
        face.set_state("idle"); return

    face.set_state("thinking")                       # 等推論
    reply_text, emotion_label = think(user_text)
    emotion = face.to_face_emotion(emotion_label)    # 映射到 5 種臉部情緒
    print(f"[reply] ({emotion}) {reply_text}")

    wav = face.ensure_wav16(synthesize(reply_text))  # 產生 / 轉檔
    face.speak(wav, emotion)                          # 播 TTS + 對嘴；講完自動回 idle


def main():
    face.set_state("idle")
    print("face pipeline running. (Ctrl-C 離開)")
    while True:
        try:
            converse_once()
            time.sleep(0.3)
        except KeyboardInterrupt:
            break
        except Exception as e:
            print("pipeline error:", e)
            face.set_state("error"); time.sleep(2); face.set_state("idle")


if __name__ == "__main__":
    main()
