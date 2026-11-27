#!/usr/bin/env bash
set -e

sudo apt update
sudo apt install -y git ffmpeg python3-pip python3-numpy python3-opencv python3-pyside6.qtcore python3-pyside6.qtgui python3-pyside6.qtwidgets python3-pyside6.qtmultimedia python3-pyside6.qtsvg

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

git clone --depth 1 https://github.com/hyunazmi/blumark.git "$TMP/blumark"
pip install --no-deps --user --break-system-packages "$TMP/blumark"

grep -q '.local/bin' ~/.bashrc || echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc

echo "[+] Proses instalasi selesai."
