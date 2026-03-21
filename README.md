# QuizGrip

QuizGrip is a small Windows desktop overlay for fast quiz answering. It uses a `pywebview` UI, lets you select a screen region, runs OCR with Tesseract, and sends the detected question to a Groq-hosted model for either a quick answer or a more detailed explanation.

## Disclaimer

This project is provided for educational, research, and personal learning purposes only. You are responsible for how you use it. Do not use it in ways that violate exam rules, platform policies, academic integrity policies, employment policies, contracts, or applicable laws. The author and contributors provide this project as-is, without warranties, and accept no liability for misuse.

## Screenshots

![QuizGrip screenshot 1](./Screenshot%202026-03-21%20210135.png)

![QuizGrip screenshot 2](./Screenshot%202026-03-21%20210806.png)

## Current Behavior

- The main overlay is a frameless always-on-top desktop window.
- The capture region selector is a temporary full-screen Tkinter crosshair overlay.
- `F8` captures the selected area and immediately generates a normal answer.
- `AI Answer` re-captures the current content and generates a fresh normal answer.
- `In Depth` captures again and generates a longer answer.
- `Full Screen` runs a one-time full-screen OCR capture and answers that capture.
- `Auto 3s` checks the selected area every 3 seconds and only triggers a new answer when the OCR text changes.
- `F9` copies the latest answer.
- `Esc` or the close button exits the app.

## Files

- `main.py`: Python backend, OCR, hotkeys, Groq API calls, area selector, and JS bridge
- `ui.html`: desktop overlay UI rendered through `pywebview`
- `.env`: local API and OCR configuration

## Prerequisites

1. Python 3.x
2. Tesseract OCR
   - Recommended Windows build: https://github.com/UB-Mannheim/tesseract/wiki
   - Default expected path: `C:\Program Files\Tesseract-OCR\tesseract.exe`
   - If your install is elsewhere, set:
     ```powershell
     $env:TESSERACT_CMD="C:\path\to\tesseract.exe"
     ```
3. Python packages
   ```powershell
   pip install pywebview pytesseract pillow requests pynput
   ```
4. Local `.env`
   ```env
   GROQ_API_KEY=your_key_here
   GROQ_MODEL=llama-3.1-8b-instant
   GROQ_API_URL=https://api.groq.com/openai/v1/chat/completions
   TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe
   ```

`.env` is loaded automatically on startup. The app also accepts `AI_*` variables and legacy `OPENAI_*` variables, but Groq is the default setup.

## Run

```powershell
python main.py
```

## Use

1. Launch the app.
2. Click `Select Area` and drag over the question region.
3. Press `F8` for an instant answer from the selected area.
4. Use `AI Answer` to re-capture and answer again.
5. Use `In Depth` for a longer answer.
6. Use `Full Screen` for a one-time full-screen capture.
7. Turn on `Auto 3s` if you want automatic next answers only when the detected question changes.
8. Press `F9` to copy the latest answer.
9. Press `Esc` or click the close button to exit.

## Notes

- Heavy OCR/API imports are loaded lazily, so the app starts faster and warms itself in the background after the window loads.
- Auto mode only works with a selected area, not with one-time full-screen capture.
- If OCR reads the same text again, auto mode does nothing.
- The answer box in the UI will show OCR errors and API errors directly.

## Troubleshooting

- If Tesseract is missing, the answer area will show the expected OCR path and tell you to set `TESSERACT_CMD`.
- If the API key is missing, the answer area will tell you to set `GROQ_API_KEY` in `.env`.
- If the API request fails, the answer area will show the HTTP status and returned message.
- If OCR finds no text, tighten the selected area and try again.
