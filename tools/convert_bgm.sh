#!/usr/bin/env bash
# convert_bgm.sh — 將 assets/bgm_src/*.mp3 轉換為 assets/bgm/*.ogg
#
# 用法：
#   bash tools/convert_bgm.sh
#
# 需求：ffmpeg（brew install ffmpeg）

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SRC_DIR="$REPO_DIR/assets/bgm_src"
DST_DIR="$REPO_DIR/assets/bgm"

# 確認 ffmpeg 存在
if ! command -v ffmpeg &>/dev/null; then
  echo "❌  找不到 ffmpeg，請先執行：brew install ffmpeg"
  exit 1
fi

# 確認來源目錄
if [ ! -d "$SRC_DIR" ]; then
  echo "❌  來源目錄不存在：$SRC_DIR"
  echo "    請將 mp3 檔案放到 assets/bgm_src/ 後再執行本腳本"
  exit 1
fi

mkdir -p "$DST_DIR"

count=0
for mp3 in "$SRC_DIR"/*.mp3; do
  [ -e "$mp3" ] || { echo "⚠️   assets/bgm_src/ 裡沒有 mp3 檔案"; exit 0; }
  base="$(basename "$mp3" .mp3)"
  ogg="$DST_DIR/${base}.ogg"
  echo "🎵  $base.mp3  →  bgm/${base}.ogg"
  ffmpeg -y -i "$mp3" -c:a libvorbis -q:a 6 "$ogg" -loglevel error
  count=$((count + 1))
done

echo ""
echo "✅  完成，共轉換 $count 個檔案 → $DST_DIR"
ls -lh "$DST_DIR"/*.ogg 2>/dev/null || true
