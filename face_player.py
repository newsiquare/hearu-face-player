#!/usr/bin/env python3
"""
Companion-robot face player (Raspberry Pi 4 / pygame).

Approach C: pre-baked layered sprites.
  - Talking states (happy/sad/dejected/angry/speaking): composite layers each frame
    (screen + brows + eyes + mouth) and pick the MOUTH frame from live TTS volume
    -> real lip-sync. Eye/brow micro-motion added by offsetting layers.
  - Non-talking states (boot/idle/listening/thinking/sleep/error): play the
    pre-rendered APNG as a frame loop (no lip-sync needed).

Integrate from your STT/LLM/TTS pipeline either by:
  (a) importing this module and calling face.set_state(...) / face.speak(wav, emotion), or
  (b) sending JSON lines to the TCP hook (127.0.0.1:8765), e.g.
        {"cmd":"state","name":"listening"}
        {"cmd":"speak","emotion":"happy","wav":"/tmp/reply.wav"}

Keyboard demo:  1..5 speak(happy/sad/dejected/angry/speaking) · b i l t k x = states · ESC quit
Env: FACE_WINDOWED=1 (windowed), FACE_TCP=0 (disable hook)
"""
import os, sys, math, time, wave, json, queue, socket, threading, tempfile, subprocess, random, argparse
import numpy as np
import pygame
from PIL import Image, ImageSequence

W, H = 800, 480
HERE = os.path.dirname(os.path.abspath(__file__))
SPR = os.path.join(HERE, "assets", "sprites")
APN = os.path.join(HERE, "assets", "apng")

TALKERS = ["happy", "sad", "dejected", "angry", "speaking"]
LOOPS   = ["boot", "idle", "listening", "thinking", "sleep", "error"]
MOUTH_STEPS = 8
LED = {"boot":"BOOT","idle":"IDLE","listening":"LISTEN","thinking":"THINK","speaking":"SPEAK",
       "happy":"HAPPY","sad":"SAD","dejected":"DOWN","angry":"ANGRY","sleep":"SLEEP","error":"ERROR"}

# BGM mapping: state name → ogg filename (None = silence)
BGM_MAP = {
    "happy":    "happy",    "sad":       "sad",   "dejected": "dejected",
    "angry":    "angry",    "speaking":  "speaking",
    "idle":     "idle",     "listening": "listening", "thinking": "thinking",
    "boot":     None,       "sleep":     None,    "error":    None,
}
BGM_FULL       = 0.75   # 正常音量
BGM_DUCK       = 0.15   # TTS 說話時壓低到此
BGM_FADE_SPEED = 1.5    # 每秒音量變化量（淡入淡出速度）
BGM_CH         = 1      # 專用 mixer channel

# micro-motion profile per talking state: gaze interval(ms), gaze amplitude(px),
# brow-flash probability, brow direction (+up / -down for angry), blink interval(ms)
PROFILE = {
    "happy":   dict(gaze=(700,1500),  amp=8, flash=0.8, dir=+1, blink=None,        floatA=8),
    "speaking":dict(gaze=(1100,2200), amp=6, flash=0.5, dir=+1, blink=(2200,5200), floatA=5),
    "sad":     dict(gaze=(2400,4200), amp=4, flash=0.2, dir=+1, blink=(3600,6800), floatA=3),
    "dejected":dict(gaze=(2600,4600), amp=4, flash=0.1, dir=+1, blink=(4000,7200), floatA=3),
    "angry":   dict(gaze=(1000,2000), amp=5, flash=0.4, dir=-1, blink=(2400,5200), floatA=2),
}

def pil_to_surf(im):
    im = im.convert("RGBA")
    return pygame.image.fromstring(im.tobytes(), im.size, "RGBA").convert_alpha()

def load_png(name):
    return pil_to_surf(Image.open(os.path.join(SPR, name + ".png")))

def load_apng(path):
    im = Image.open(path); frames, durs = [], []
    for fr in ImageSequence.Iterator(im):
        frames.append(pil_to_surf(fr.convert("RGBA")))
        durs.append(fr.info.get("duration", 80))
    return frames, durs

def wav_envelope(path, hop_ms=30):
    """Return (env[0..1] per hop, hop_seconds, duration_s). 16/8-bit PCM wav."""
    wf = wave.open(path, "rb")
    sr, ch, sw, n = wf.getframerate(), wf.getnchannels(), wf.getsampwidth(), wf.getnframes()
    raw = wf.readframes(n); wf.close()
    if sw == 2:   data = np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0
    elif sw == 1: data = (np.frombuffer(raw, np.uint8).astype(np.float32) - 128) / 128.0
    else:         data = np.frombuffer(raw, np.int32).astype(np.float32) / 2147483648.0
    if ch > 1: data = data.reshape(-1, ch).mean(axis=1)
    hop = max(1, int(sr * hop_ms / 1000))
    env = np.array([np.sqrt(np.mean(data[i:i+hop] ** 2) + 1e-9) for i in range(0, len(data), hop)])
    if env.max() > 1e-6: env = env / env.max()
    env = np.clip(env * 1.15, 0, 1)
    return env, hop_ms / 1000.0, n / float(sr)


class Face:
    def __init__(self, windowed=False):
        pygame.init()
        try: pygame.mixer.init(buffer=512)
        except Exception as e: print("mixer init failed (audio off):", e)
        flags = 0 if windowed else (pygame.FULLSCREEN | pygame.SCALED)
        self.screen = pygame.display.set_mode((W, H), flags)
        pygame.mouse.set_visible(False)
        pygame.display.set_caption("Companion Face")
        self.font = pygame.font.SysFont("monospace", 13)
        self._load()
        # BGM runtime state
        self.bgm_current = None   # 目前播放的 BGM key
        self.bgm_vol     = 0.0    # 目前實際音量
        self.bgm_target  = 0.0    # 目標音量
        # runtime state
        self.state = "idle"; self.talking = False
        self.lip = 0.0; self.lip_target = 0.0
        self.env = None; self.env_hop = 0.03; self.audio_t0 = 0.0; self.audio_dur = 0.0
        self.floatA = 5
        self.gaze = [0.0, 0.0]; self.gaze_t = [0.0, 0.0]; self.gaze_next = 0.0
        self.brow_flash = 0.0; self.nod = 0.0; self.next_nod = 0.0
        self.blinking_until = 0.0; self.next_blink = 0.0
        self.loop_i = 0; self.loop_acc = 0.0
        self.set_state("idle")

    def _load(self):
        self.spr = {}
        for e in TALKERS:
            d = {"screen": load_png(f"screen_{e}"), "eyes_open": load_png(f"eyes_open_{e}"),
                 "mouth": [load_png(f"mouth_{e}_{k}") for k in range(MOUTH_STEPS)]}
            for opt in (f"brows_{e}", f"eyes_closed_{e}"):
                p = os.path.join(SPR, opt + ".png")
                if os.path.exists(p): d[opt.split("_")[0] if opt.startswith("brows") else "eyes_closed"] = load_png(opt)
            self.spr[e] = d
        self.loops = {}
        for s in LOOPS:
            p = os.path.join(APN, s + ".png")
            if os.path.exists(p): self.loops[s] = load_apng(p)
        # BGM: 預載所有 ogg 為 Sound 物件
        self.bgm_sounds = {}
        bgm_dir = os.path.join(HERE, "assets", "bgm")
        for key in set(v for v in BGM_MAP.values() if v):
            p = os.path.join(bgm_dir, key + ".ogg")
            if os.path.exists(p):
                self.bgm_sounds[key] = pygame.mixer.Sound(p)
        self.bgm_ch = pygame.mixer.Channel(BGM_CH)

    # ---- public API ----
    def _bgm_switch(self, state_name):
        """切換 BGM 到對應狀態，若相同則不重播。"""
        key = BGM_MAP.get(state_name)
        if key == self.bgm_current:
            return
        self.bgm_current = key
        self.bgm_ch.stop()
        if key and key in self.bgm_sounds:
            self.bgm_ch.play(self.bgm_sounds[key], loops=-1)
            self.bgm_vol    = 0.0
            self.bgm_target = BGM_FULL
        else:
            self.bgm_vol    = 0.0
            self.bgm_target = 0.0

    def set_state(self, name):
        if name not in TALKERS and name not in self.loops: return
        self.state = name
        if name in LOOPS:
            self.talking = False; self.loop_i = 0; self.loop_acc = 0.0
        else:
            self.floatA = PROFILE[name]["floatA"]
            if not self.talking:                      # static emotion mouth
                self.lip_target = 0.45 if name == "happy" else 0.0
        if not self.talking:      # TTS 進行中不切 BGM（speak() 結束後再切）
            self._bgm_switch(name)

    def speak(self, wav_path, emotion="speaking"):
        if emotion not in TALKERS: emotion = "speaking"
        self.set_state(emotion)
        try:
            self.env, self.env_hop, self.audio_dur = wav_envelope(wav_path)
            pygame.mixer.music.load(wav_path); pygame.mixer.music.play()
            self.audio_t0 = time.perf_counter(); self.talking = True
            # TTS 開始：BGM duck
            self.bgm_target = BGM_DUCK
        except Exception as e:
            print("speak failed:", e); self.talking = False

    def stop(self):
        try: pygame.mixer.music.stop()
        except Exception: pass
        self.talking = False; self.lip_target = 0.0; self.set_state("idle")

    # ---- per-frame update ----
    def update(self, dt, now):
        st = self.state
        if st in TALKERS:
            p = PROFILE[st]
            # lip target from TTS envelope (real volume-driven) while talking
            if self.talking:
                if not pygame.mixer.music.get_busy() and (time.perf_counter()-self.audio_t0) > 0.15:
                    self.talking = False; self.lip_target = 0.0
                    self._end_at = now + 0.4
                    # TTS 結束：BGM unduck
                    self.bgm_target = BGM_FULL
                elif self.env is not None:
                    idx = int((time.perf_counter()-self.audio_t0) / self.env_hop)
                    self.lip_target = float(self.env[idx]) if 0 <= idx < len(self.env) else 0.0
            else:
                self.lip_target = 0.45 if st == "happy" else 0.0
                if getattr(self, "_end_at", 0) and now >= self._end_at:
                    self._end_at = 0; self.set_state("idle"); return
            # smooth lip (fast open, slower close)
            k = dt/0.055 if self.lip_target > self.lip else dt/0.11
            self.lip += (self.lip_target - self.lip) * min(1, k)
            # gaze saccades
            if now > self.gaze_next:
                a = p["amp"] * (1.3 if self.talking else 1.0)
                self.gaze_t = [random.uniform(-a, a), random.uniform(-a*0.6, a*0.6)]
                self.gaze_next = now + random.uniform(*p["gaze"]) / 1000.0
            for i in (0, 1): self.gaze[i] += (self.gaze_t[i]-self.gaze[i]) * min(1, dt/0.13)
            # brow flash (emphasis) only while talking
            if self.talking and now > getattr(self, "_nf", 0):
                if random.random() < p["flash"]:
                    self.brow_flash = (4+random.random()*4) * p["dir"]
                self._nf = now + random.uniform(0.25, 0.6)
            self.brow_flash += (0 - self.brow_flash) * min(1, dt/0.12)
            # nod while talking
            if self.talking and now > self.next_nod:
                self.nod = 5; self.next_nod = now + random.uniform(1.2, 2.4)
            self.nod += (0 - self.nod) * min(1, dt/0.14)
            # blink
            if p["blink"] and "eyes_closed" in self.spr[st]:
                if now > self.next_blink:
                    self.blinking_until = now + 0.12
                    self.next_blink = now + random.uniform(*p["blink"]) / 1000.0
        else:
            # advance APNG loop
            L = self.loops.get(st)
            if L:
                frames, durs = L; self.loop_acc += dt*1000
                while self.loop_acc >= durs[self.loop_i]:
                    self.loop_acc -= durs[self.loop_i]; self.loop_i = (self.loop_i+1) % len(frames)
        # BGM 音量漸變（每幀平滑 fade in/out/duck）
        if self.bgm_vol != self.bgm_target:
            step = BGM_FADE_SPEED * dt
            diff = self.bgm_target - self.bgm_vol
            self.bgm_vol = self.bgm_target if abs(diff) <= step else self.bgm_vol + math.copysign(step, diff)
            self.bgm_ch.set_volume(self.bgm_vol)

    def draw(self, now):
        st = self.state
        if st in TALKERS:
            S = self.spr[st]
            self.screen.blit(S["screen"], (0, 0))
            baseY = math.sin(now*0.9*math.pi) * self.floatA + self.nod
            if "brows" in S:
                self.screen.blit(S["brows"], (0, baseY - self.brow_flash))
            eye = S["eyes_closed"] if (now < self.blinking_until and "eyes_closed" in S) else S["eyes_open"]
            self.screen.blit(eye, (self.gaze[0], baseY + self.gaze[1]))
            k = int(round(max(0.0, min(1.0, self.lip)) * (MOUTH_STEPS-1)))
            self.screen.blit(S["mouth"][k], (0, baseY))
        else:
            L = self.loops.get(st)
            if L: self.screen.blit(L[0][self.loop_i], (0, 0))
        # tiny status tag (set FACE_DEBUG=1 to show)
        if os.environ.get("FACE_DEBUG"):
            tag = self.font.render(LED.get(st, st), True, (150, 150, 170))
            self.screen.blit(tag, (W-tag.get_width()-10, 8))


# ---------- demo speech (synthetic wav so the demo works without a TTS) ----------
def make_demo_wav(emotion, seconds=2.6, sr=22050):
    """Try espeak-ng for real speech; else synthesize a syllable-modulated tone."""
    txt = {"happy":"嗨 很高興見到你","sad":"我聽到了 這一定很不好受",
           "dejected":"唉 我也不太知道該怎麼辦","angry":"這真的太過分了",
           "speaking":"好的 我幫你看看這件事"}.get(emotion, "你好")
    path = os.path.join(tempfile.gettempdir(), f"demo_{emotion}.wav")
    try:
        subprocess.run(["espeak-ng","-v","cmn","-w",path,txt],
                       check=True, capture_output=True, timeout=8)
        return path
    except Exception:
        pass
    # fallback: amplitude-modulated tone shaped like syllables
    rate = {"happy":7.0,"angry":8.5,"sad":4.5,"dejected":4.0,"speaking":6.0}.get(emotion,6.0)
    t = np.linspace(0, seconds, int(sr*seconds), endpoint=False)
    syl = (np.sin(2*np.pi*rate*t)*0.5+0.5) ** 1.5
    gate = (np.random.rand(len(t)) > 0.04).astype(np.float32)
    env = syl*gate
    tone = 0.25*np.sin(2*np.pi*140*t) + 0.15*np.sin(2*np.pi*220*t)
    sig = (tone*env*0.6*32767).astype(np.int16)
    with wave.open(path,"wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr); w.writeframes(sig.tobytes())
    return path


# ---------- optional TCP command hook for your pipeline ----------
def tcp_listener(q, host="127.0.0.1", port=8765):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try: s.bind((host, port)); s.listen(5)
    except Exception as e: print("TCP hook off:", e); return
    print(f"[face] command hook on {host}:{port}")
    while True:
        try:
            conn, _ = s.accept()
            buf = conn.recv(4096).decode("utf-8", "ignore")
            for line in buf.splitlines():
                line = line.strip()
                if line:
                    try: q.put(json.loads(line))
                    except Exception: pass
            conn.close()
        except Exception:
            time.sleep(0.2)


def main():
    ap = argparse.ArgumentParser(description="Companion face player")
    ap.add_argument("--state", default="idle",
                    help="起始表情/狀態：happy sad dejected angry speaking | boot idle listening thinking sleep error")
    ap.add_argument("--windowed", action="store_true", help="視窗模式（預設全螢幕）")
    ap.add_argument("--debug", action="store_true", help="角落顯示狀態名")
    ap.add_argument("--no-tcp", action="store_true", help="關閉 127.0.0.1:8765 指令介面")
    a = ap.parse_args()
    if a.debug:
        os.environ["FACE_DEBUG"] = "1"
    windowed = a.windowed or os.environ.get("FACE_WINDOWED") == "1"
    face = Face(windowed=windowed)
    face.set_state(a.state)
    cmdq = queue.Queue()
    if not a.no_tcp and os.environ.get("FACE_TCP", "1") == "1":
        threading.Thread(target=tcp_listener, args=(cmdq,), daemon=True).start()

    clock = pygame.time.Clock()
    last = time.perf_counter()
    keymap = {pygame.K_1:"happy", pygame.K_2:"sad", pygame.K_3:"dejected",
              pygame.K_4:"angry", pygame.K_5:"speaking",
              pygame.K_b:"boot", pygame.K_i:"idle", pygame.K_l:"listening",
              pygame.K_t:"thinking", pygame.K_k:"sleep", pygame.K_x:"error"}
    running = True
    while running:
        now = time.perf_counter(); dt = now - last; last = now
        for e in pygame.event.get():
            if e.type == pygame.QUIT: running = False
            elif e.type == pygame.KEYDOWN:
                if e.key in (pygame.K_ESCAPE, pygame.K_q): running = False
                elif e.key in keymap:
                    tgt = keymap[e.key]
                    mods = pygame.key.get_mods()
                    if tgt in TALKERS:
                        if mods & pygame.KMOD_SHIFT:
                            face.speak(make_demo_wav(tgt), tgt)  # Shift+1~5：播示範語音
                        else:
                            face.set_state(tgt)                  # 1~5：只切情緒/BGM
                    else:
                        face.set_state(tgt)
        # commands from pipeline
        while not cmdq.empty():
            c = cmdq.get()
            if c.get("cmd") == "state": face.set_state(c.get("name", "idle"))
            elif c.get("cmd") == "speak": face.speak(c.get("wav"), c.get("emotion", "speaking"))
            elif c.get("cmd") == "stop": face.stop()

        face.update(dt, now)
        face.draw(now)
        pygame.display.flip()
        clock.tick(60)
    pygame.quit()


if __name__ == "__main__":
    main()
