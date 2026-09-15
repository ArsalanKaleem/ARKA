# Desktop Companion

A lightweight animated desktop pet for Windows, written entirely in Python.
Give it **one full-body anime-style PNG** and it turns that single image
into a small creature that walks, idles, jumps, sleeps, and reacts to your
CPU/GPU load and (optionally) Windows notifications — all through
procedural animation, with no spritesheets or AI-generated frames required.

## What it does

- Renders your character in a borderless, transparent, always-on-top
  window that stays out of the taskbar.
- Walks across the bottom of your screen, turns at the edges, idles,
  jumps, and sleeps — all generated from one static image via
  position/rotation/scale/flip transforms.
- Watches CPU (and NVIDIA GPU, if present) usage and reacts:
  green/yellow/red status dot, and EXCITED/PANIC animations under load.
- Shows a small "NEW MESSAGE" sign when a notification is detected (or
  manually triggered from the tray menu).
- Lives in the system tray with pause/resume, character switching,
  settings, and exit.
- Supports multiple characters and can start with Windows.

## Requirements

- Windows 10 or 11 (the transparent overlay, tray icon, startup
  registration, and notification listener are Windows-specific; the app
  will still run on macOS/Linux for development, minus those features).
- Python 3.11+.

## Installation

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

If you don't have an NVIDIA GPU, you can skip `nvidia-ml-py` — the app
detects its absence and simply reports GPU status as unavailable.

## Running

```powershell
python main.py
```

On first launch, if no character exists yet, a setup dialog will ask you
to pick a PNG. A simple placeholder character is included at
`assets/characters/default/character.png` so you can try the app
immediately — replace it (or add a new character from the tray menu)
with your own full-body art.

## Adding / changing a character

Two ways:

1. **Tray menu → Change Character** — pick any PNG and give it a name;
   it's copied into `assets/characters/<name>/character.png` and applied
   immediately (no restart needed).
2. **Manually** — drop a PNG at
   `assets/characters/<your_name>/character.png`, then select it from
   **Settings → Appearance → Character**.

Best results come from a full-body, front- or three-quarter-facing,
centered character with a simple or transparent background. The app will
attempt to strip a flat-color background automatically; if that's
unreliable for your art, supply an already-transparent PNG.

Processed/cropped/flipped versions are cached under `data/cache/<name>/`
so reprocessing only happens when the source PNG changes.

## Configuration

All settings live in `config.json` next to `main.py` (created
automatically with sensible defaults on first run), and are also editable
from **Settings** in the tray menu:

```json
{
  "pet": { "scale": 1.0, "walk_speed": 2.0, "animation_fps": 12 },
  "behavior": { "idle_min_seconds": 3, "idle_max_seconds": 15, "jump_probability": 0.02 },
  "system": { "monitor_cpu": true, "monitor_gpu": true, "yellow_threshold": 50, "red_threshold": 80 },
  "notifications": { "enabled": true, "board_duration": 3 }
}
```

Malformed or partial config files are repaired automatically by merging
with defaults — the app will never fail to start because of a bad
`config.json`.

## Building a Windows executable

```powershell
pip install pyinstaller
python build.py
```

This produces `dist/DesktopCompanion.exe` — a single windowless
executable with assets bundled in. `config.json`, `data/app.log`, and the
image-processing cache are created next to the .exe on first run.

## Starting with Windows

Toggle **Start With Windows** from the tray menu, or in
**Settings → General**. This adds a per-user entry to
`HKCU\Software\Microsoft\Windows\CurrentVersion\Run` — no administrator
privileges required, and it can be removed the same way at any time.

## Known Windows limitations

- **GPU monitoring** requires an NVIDIA GPU and the `nvidia-ml-py`
  package (which provides the `pynvml` module). AMD/Intel GPU support is
  not implemented yet; the `system_monitor.py` module is structured so a
  reader class for another vendor can be added alongside `_NvmlGpuReader`
  without touching the rest of the app.
- **Notification detection** uses the WinRT `UserNotificationListener`
  API via the `winsdk` package. This requires the user to grant
  "Notification access" the first time (Windows will prompt, or you may
  need to enable it manually under *Settings → Privacy & Security →
  Notification access*), only sees notifications routed through the
  Windows Notification Center, and never reads private message contents —
  it only reports that *a* notification arrived. If `winsdk` isn't
  installed or access is denied, this feature quietly disables itself;
  the tray menu's **Send Test Notification** action always works as a
  manual fallback.
- Very old or unusual multi-monitor DPI configurations may occasionally
  need `monitor_index` adjusted manually in `config.json`.

## Suggestions for future AI character generation

`app/character.py` and `app/image_processor.py` are intentionally decoupled
from *where* a PNG comes from — they just expect
`assets/characters/<name>/character.png` to exist. A future
`character_generator.py` module could:

1. Take a text prompt from a new Settings tab.
2. Call an image-generation API (e.g. read the key from an environment
   variable such as `GEMINI_API_KEY` — **never hardcode API keys**).
3. Save the result to `assets/characters/<name>/character.png`.
4. Call the existing `CharacterManager`/`ImageProcessor` pipeline exactly
   as `Change Character` does today.

Because the animation/movement/behavior layers only ever consume the
already-processed PNGs, none of that code would need to change.

## Project structure

```
desktop_companion/
├── main.py                 # entry point / wiring
├── requirements.txt
├── README.md
├── config.json
├── build.py                 # PyInstaller build script
├── app/
│   ├── pet_window.py         # transparent window, painting, mouse input, board, indicator
│   ├── pet.py                 # combines character + animation + movement + behavior
│   ├── animation.py           # procedural per-state transforms (no spritesheets)
│   ├── movement.py            # screen bounds, walking position, edges, monitors
│   ├── behavior.py             # state machine deciding IDLE/WALK/JUMP/etc.
│   ├── system_monitor.py       # psutil + optional pynvml, on a background QThread
│   ├── notifications.py         # optional WinRT notification listener + manual fallback
│   ├── character.py              # character folder discovery/import
│   ├── image_processor.py         # Pillow: crop/bg-removal/resize/flip + caching
│   ├── settings.py                 # config load/validate/save + Settings dialog
│   ├── tray.py                      # system tray icon and menu
│   ├── startup.py                    # optional "start with Windows" (registry Run key)
│   ├── first_run.py                   # first-launch character picker
│   └── utils.py                        # paths + logging
├── assets/characters/default/character.png
└── data/                                # config, logs, and processed-image cache (created at runtime)
```

## Troubleshooting

- **Nothing appears on screen**: check `data/app.log` for a stack trace;
  the most common cause is a missing/corrupt `character.png`.
- **GPU shows "unavailable"**: install `nvidia-ml-py` and confirm you have
  an NVIDIA GPU with up-to-date drivers.
- **Notifications never trigger**: confirm `winsdk` is installed, that
  Windows granted notification access, and in the meantime use **Send
  Test Notification** from the tray menu to confirm the rest of the
  pipeline (board, NOTICE animation) works.
