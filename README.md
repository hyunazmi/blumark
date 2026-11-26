# Blumark

A PySide6 desktop app that covers a video watermark with a blur.

The logo lives in `blumark/resources/` (`logo.svg`, plus `logo.png` and `logo.ico` for packaging).

## Features

- Drag a video onto the window, or press Ctrl+O.
- Playback with audio, with the blur shown live.
- Selection box: move it, resize it from any of the 8 handles, or drag on empty space to draw a new one.
- Click the green check button next to the top-right corner of the box (outside it) to confirm the area. Click the area again to edit it.
- Blur menu: strength, edge softness and live preview toggle. Sliders jump straight to where you click.
- Export with ffmpeg (original audio kept by default). Progress shows at the right end of the playback controls, and the X button next to Export cancels it.
- Export settings (Settings > Export settings): pick the container (MP4, MKV, WebM, MOV) and the video codec (H.264, H.265, AV1 via SVT-AV1 or libaom, VP9, and NVIDIA NVENC). Each codec has its own speed setting (named presets for x264/x265, numbers for AV1/NVENC, -cpu-used for libaom/VP9) and its own quality scale (CRF/CQ). The output resolution is detected from the opened video: Original, plus every standard size below it (1080p, 720p, 480p...), never enlarged. Audio can be re-encoded, copied or dropped. Every codec that fits the chosen container is listed, marked Supported or Not supported for this computer: Blumark tests each one in the background with a tiny real encode, so it reflects your actual hardware (for example NVENC needs an NVIDIA GPU). Unsupported codecs are greyed out; hover one to see why.
- ffmpeg location can be set in Settings > FFmpeg, with a test button and auto-detect.

The app never prints to the terminal: Qt, OpenCV and ffmpeg messages are silenced, and errors are shown as dialogs inside the app. Set `BLUMARK_DEBUG=1` to turn the silencing off while developing.

Every menu, form row and dialog button has an icon.

Shortcuts: Space play/pause, Left and Right arrows previous/next frame, Ctrl+O open, Ctrl+E export.

## Install and run

    cd blumark
    pip install .          # or: pip install -e .  for development
    blumark
    # or
    python -m blumark [video.mp4]

## Files

    blumark/__main__.py       python -m blumark
    blumark/app.py            QApplication and main()
    blumark/main_window.py    main window, menus, player, drag and drop, export
    blumark/video_canvas.py   frame drawing, live blur, selection box
    blumark/widgets.py        JumpSlider (click-to-jump) and IconLabel
    blumark/ffmpeg_dialog.py  ffmpeg settings dialog
    blumark/export_dialog.py  container / codec / speed / quality dialog
    blumark/ffmpeg_tools.py   find ffmpeg and read its version
    blumark/exporter.py       ffmpeg command builder and export worker (OpenCV -> pipe -> ffmpeg)
    blumark/blur.py           blur logic (no Qt)
    blumark/video_info.py     video metadata
    blumark/hardware.py       background test of which codecs this computer can run
    blumark/codecs.py         containers, codecs and their ffmpeg arguments
    blumark/settings.py       QSettings (ffmpeg path, export options, volume, last folder)
    blumark/icons.py          SVG icon loader that follows the palette
    blumark/utils.py
    blumark/resources/icons/  Lucide icons (ISC license included)
