# 情緒陪伴機器人 — 臉部播放器（Raspberry Pi 4）

預烤分層 sprite ＋ pygame 即時合成。會說話的 5 種情緒（開心/難過/沮喪/生氣/說話中）
的嘴型由**實際 TTS 音量驅動**（lip-sync），並有眨眼、視線游移、挑眉/壓眉等微動作；
不說話的 6 種狀態（開機/待機/聆聽/思考/休眠/異常）直接播放預先做好的 APNG。
畫面 800×480，對應你的小螢幕。

## 內容物

```
face_player.py        主程式（狀態機、lip-sync、微動作、TCP 指令介面）
run_face.sh           啟動腳本（環境變數設定）
face.service          systemd 使用者服務（開機自啟）
requirements.txt      Python 相依
assets/sprites/       5 種情緒的分層圖（screen / brows / eyes / mouth_0..7）
assets/apng/          6 種非說話狀態的 APNG（迴圈播放）
tools/render_layers.py  重新烘焙分層 sprite（改造型/顏色時用）
tools/render_apng.py    重新產生 APNG
integration/face_client.py     從你的 pipeline 驅動臉部（含情緒映射、wav 轉檔）
integration/example_pipeline.py 可直接跑的端到端骨架（含 mock，標好替換點）
```

## 1. 硬體與系統

- Raspberry Pi 4（2GB 以上即可；本程式佔用僅數十 MB，比 Chromium 省很多）。
- 800×480 螢幕（DSI/HDMI 觸控皆可）＋喇叭。
- Raspberry Pi OS Bookworm 64-bit（桌面版，需要圖形工作階段來顯示）。

## 2. 安裝

```bash
sudo apt update
sudo apt install -y python3-pygame python3-pil python3-numpy fonts-noto-cjk
# 想用內建語音做示範可裝（非必要，實機用你自己的 TTS）：
sudo apt install -y espeak-ng
# 把整個資料夾放到 ~/companion-face
```
若偏好 pip：`pip install -r requirements.txt --break-system-packages`

## 3. 音訊輸出

`pygame.mixer` 走系統預設音訊裝置。用 `raspi-config` →
System Options → Audio 選對輸出（3.5mm / HDMI / USB / I2S 擴大板），
或在 `~/.asoundrc` 設預設 sink。先 `aplay 某檔.wav` 確認有聲音再跑本程式。

## 4. 先在視窗測試

```bash
cd ~/companion-face
FACE_WINDOWED=1 FACE_DEBUG=1 python3 face_player.py
```
鍵盤：`1`開心 `2`難過 `3`沮喪 `4`生氣 `5`說話中（會用示範語音對嘴）；
`b`開機 `i`待機 `l`聆聽 `t`思考 `k`休眠 `x`異常；`Esc/q` 離開。

## 5. 開機自啟

**方法 A — 合成器 autostart（最簡單）。** Bookworm 預設 Wayland：
- labwc：編輯 `~/.config/labwc/autostart`，加入
  `bash /home/<USER>/companion-face/run_face.sh &`
- 舊版 wayfire：在 `~/.config/wayfire.ini` 的 `[autostart]` 區段加一行。
搭配 `raspi-config` 設定**桌面自動登入**。

**方法 B — systemd 使用者服務（較好管理、會自動重啟）。**
```bash
loginctl enable-linger <USER>
mkdir -p ~/.config/systemd/user
cp face.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now face.service
journalctl --user -u face.service -f   # 看日誌
```

> 若畫面全黑或位置跑掉：Wayland/SDL 偶有相容問題。先在 `run_face.sh`
> 試 `export SDL_VIDEODRIVER=x11`，或用 `raspi-config` → Advanced →
> Wayland 切回 X11（很多 kiosk 在 X11 下更穩）。關螢幕休眠：`xset s off -dpms`（X11）
> 或在合成器設定關閉 DPMS。

## 6. 與你的 STT/LLM/TTS pipeline 整合

程式啟動會在 `127.0.0.1:8765` 開一個 TCP 指令介面（傳一行 JSON 即可）：

```python
import socket, json
def face(cmd):
    s = socket.socket(); s.connect(("127.0.0.1", 8765))
    s.sendall((json.dumps(cmd) + "\n").encode()); s.close()

face({"cmd": "state", "name": "listening"})              # 偵測到語音
face({"cmd": "state", "name": "thinking"})               # 送出辨識、等推論
face({"cmd": "speak", "emotion": "happy", "wav": "/tmp/reply.wav"})  # 播 TTS 並對嘴
# 講完會自動回到 idle
face({"cmd": "stop"})                                    # 中斷
```

`speak` 的 `wav` 給你 TTS 輸出的 wav 檔（16-bit PCM 最佳）；程式會即時算它的音量
包絡來開合嘴。`emotion` 從你的情緒判斷結果帶入（happy/sad/dejected/angry/speaking）。

典型流程對照：
`待機 → vad 觸發 state:listening → 辨識完 state:thinking → TTS 開始 speak(emotion,wav) → 講完自動 idle`。
（也可改成 `import face_player`、直接呼叫 `Face` 物件的方法，省去 TCP。）

## 7. 改造型 / 顏色

所有發光、顏色、嘴型形狀都在 `tools/render_layers.py` 的 `EMO` 與幾何參數裡。
改完重烤即可（需要 Pillow + numpy 的開發機，可在 Pi 或你的電腦上跑）：

```bash
python3 tools/render_layers.py     # 重新產生 assets/sprites/
python3 tools/render_apng.py       # 重新產生 assets/apng/
```
缺點就是改造型要重烤一次（不像程序化繪製即時改參數），但這是一行指令的事。

## 8. 效能

純粹是預烤圖層的 blit，Pi 4 在 800×480 跑 60fps 非常輕鬆，
不像 Chromium 要每格重算 CSS 濾鏡。表面以 `convert_alpha()` 載入以加速。

## 微動作個性對照（程式內 `PROFILE`）

| 情緒 | 視線 | 挑眉/壓眉 | 眨眼 | 浮動 |
|---|---|---|---|---|
| 開心 | 活潑 | 常挑眉（上） | 不眨（彎眼） | 大 |
| 說話中 | 一般 | 適度（上） | 正常 | 中 |
| 難過 | 慢、少 | 極少 | 慢 | 小 |
| 沮喪 | 最少 | 幾乎不動 | 最慢 | 小 |
| 生氣 | 中 | **壓眉（下）** | 正常 | 微 |
