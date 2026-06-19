#!/usr/bin/env python3
"""
mac_say_test.py — 用 macOS 內建 `say` 產生語音，餵給 face_player 測「真實對嘴」。

先在另一個終端機啟動臉： python3 ../face_player.py   （或同層的 face_player.py）

一次性用法（帶參數）:
    python3 mac_say_test.py "你今天過得好嗎" --emotion sad
    python3 mac_say_test.py "太好了！" -e happy -v Meijia -r 190
    python3 mac_say_test.py --state listening          # 只切狀態、不說話
    python3 mac_say_test.py --voices                    # 列出可用語音

互動模式（不帶文字直接執行，邊調邊試）:
    python3 mac_say_test.py
    然後輸入：
        直接打字            → 用目前設定說出來並對嘴
        :happy / :sad / :dejected / :angry / :speaking   → 換情緒
        :voice Meijia       → 換語音（中文女聲，需系統已安裝）
        :rate 190           → 換語速（words per minute）
        :state thinking     → 只切臉部狀態
        :voices             → 列出語音
        :stop               → 停止說話
        :quit               → 離開
"""
import os, sys, argparse, subprocess, shutil, platform

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # 找得到 face_client
import face_client as face

EMOTIONS = {"happy", "sad", "dejected", "angry", "speaking"}
WAV = "/tmp/mac_say_test.wav"

def have_say():
    return platform.system() == "Darwin" and shutil.which("say")

def list_voices():
    if not have_say():
        print("此功能需 macOS 的 `say` 指令。"); return
    subprocess.run(["say", "-v", "?"])

def synth(text, voice=None, rate=None):
    """用 say 產生 16-bit PCM wav（player 想要的格式）。回傳 wav 路徑或 None。"""
    if not have_say():
        print("找不到 macOS `say`；此腳本僅供 mac 測試用。"); return None
    cmd = ["say", "-o", WAV, "--data-format=LEI16@22050"]
    if voice: cmd += ["-v", voice]
    if rate:  cmd += ["-r", str(rate)]
    cmd.append(text)
    try:
        subprocess.run(cmd, check=True)
        return WAV
    except subprocess.CalledProcessError as e:
        print("say 失敗（語音名稱可能不存在？用 --voices 查）:", e); return None

def say_and_show(text, emotion, voice, rate):
    if emotion not in EMOTIONS:
        print(f"情緒須為 {sorted(EMOTIONS)}；先用 speaking。"); emotion = "speaking"
    wav = synth(text, voice, rate)
    if wav:
        face.speak(wav, emotion)
        print(f"  ▶ [{emotion}] {text}")

def repl(emotion, voice, rate):
    print("互動模式。打字即說；指令見上方說明。Ctrl-D 或 :quit 離開。\n")
    face.set_state("idle")
    while True:
        try:
            line = input(f"[{emotion}|{voice or '預設'}|{rate or '預設'}]> ").strip()
        except EOFError:
            print(); break
        if not line:
            continue
        if line.startswith(":"):
            parts = line[1:].split(maxsplit=1)
            cmd = parts[0].lower(); arg = parts[1].strip() if len(parts) > 1 else ""
            if cmd in EMOTIONS:                 emotion = cmd
            elif cmd == "voice":                voice = arg or None
            elif cmd == "rate":                 rate = arg or None
            elif cmd == "state":                face.set_state(arg or "idle"); print("  state →", arg)
            elif cmd == "voices":               list_voices()
            elif cmd == "stop":                 face.stop()
            elif cmd in ("quit", "q", "exit"):  break
            else:                               print("  未知指令：", cmd)
            continue
        say_and_show(line, emotion, voice, rate)

def main():
    ap = argparse.ArgumentParser(description="macOS say → face_player 對嘴測試")
    ap.add_argument("text", nargs="?", help="要說的話（省略則進互動模式）")
    ap.add_argument("-e", "--emotion", default="speaking", help="happy/sad/dejected/angry/speaking")
    ap.add_argument("-v", "--voice", default=None, help="say 語音名（中文女聲如 Meijia）")
    ap.add_argument("-r", "--rate", default=None, help="語速 words-per-minute（如 180）")
    ap.add_argument("--state", default=None, help="只切臉部狀態，不說話（如 listening）")
    ap.add_argument("--voices", action="store_true", help="列出可用語音後結束")
    ap.add_argument("--host", default=face.HOST); ap.add_argument("--port", type=int, default=face.PORT)
    a = ap.parse_args()

    face.HOST, face.PORT = a.host, a.port      # 讓 face_client 連到指定位址

    if a.voices:
        list_voices(); return
    if a.state:
        face.set_state(a.state); print("state →", a.state); return
    if a.text:
        say_and_show(a.text, a.emotion, a.voice, a.rate); return
    repl(a.emotion, a.voice, a.rate)

if __name__ == "__main__":
    main()
