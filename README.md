# QuizGrip

QuizGrip is a Python-based utility designed to capture specific screen areas, perform OCR (Optical Character Recognition), and compile text from multiple screen states into a single clipboard-ready format.

## Features
- Visual Selection: Draw a box over the screen area you want to track at the start of the session.
- Background Listener: Use the F8 hotkey to capture text without switching windows.
- Clipboard Integration: Automatically compiles all captured text and copies it to your clipboard upon exit.

## Prerequisites

1. Python 3.x installed on your system.
2. Tesseract OCR Engine:
   - This script requires the Tesseract binary to perform text extraction.
   - Download the Windows installer here: https://github.com/UB-Mannheim/tesseract/wiki
   - After installation, ensure the path in the script (`pytesseract.pytesseract.tesseract_cmd`) matches your install location (usually `C:\Program Files\Tesseract-OCR\tesseract.exe`).

3. Required Python Libraries:
   ```bash
   pip install pytesseract pillow pynput pyperclip
   ```

## How to Run

1. Open a terminal in the project folder:
   ```bash
   cd path/to/your/folder
   ```

2. Start the script:
   ```bash
   python main.py
   ```

3. When the transparent overlay appears, drag to select the area where the quiz question appears.

4. Press `F8` each time you want to capture the current question from that selected area.

5. Press `Esc` when you are finished. All captured questions will be combined and copied to your clipboard.
