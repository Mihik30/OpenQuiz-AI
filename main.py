import os
import queue
import threading
import logging
logging.getLogger('pywebview').setLevel(logging.CRITICAL)
import webview

# Heavy imports — loaded lazily on first use to keep startup fast
_pytesseract = None
_requests = None
_ImageGrab = None
_ImageOps = None
_pynput_keyboard = None

def _lazy_imports():
    global _pytesseract, _requests, _ImageGrab, _ImageOps, _pynput_keyboard
    if _pytesseract is None:
        import pytesseract as _pt
        _pytesseract = _pt
        from PIL import ImageGrab, ImageOps
        _ImageGrab = ImageGrab
        _ImageOps = ImageOps
        import requests as _req
        _requests = _req
        from pynput import keyboard as _kb
        _pynput_keyboard = _kb

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


# ── env loader ───────────────────────────────────────────────────────────────
def load_env_file(path):
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


load_env_file(os.path.join(BASE_DIR, ".env"))


def first_env(*names, default=""):
    for name in names:
        v = os.getenv(name, "").strip()
        if v:
            return v
    return default


DEFAULT_TESSERACT = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
TESSERACT_CMD = os.getenv("TESSERACT_CMD", DEFAULT_TESSERACT)

AI_API_CONFIG = {
    "url":     first_env("AI_API_URL", "GROQ_API_URL", "OPENAI_API_URL",
                         default="https://api.groq.com/openai/v1/chat/completions"),
    "api_key": first_env("AI_API_KEY", "GROQ_API_KEY", "OPENAI_API_KEY"),
    "model":   first_env("AI_MODEL", "GROQ_MODEL", "OPENAI_MODEL",
                         default="llama-3.1-8b-instant"),
}


# ── Area selector (still uses tkinter — runs briefly, then hides) ────────────
def select_area_blocking():
    """Show a full-screen crosshair selector. Returns (x1,y1,x2,y2) or None."""
    import tkinter as tk

    result = {"bbox": None}
    root = tk.Tk()
    root.attributes("-alpha", 0.25)
    root.attributes("-fullscreen", True)
    root.attributes("-topmost", True)
    root.configure(bg="black")
    root.overrideredirect(True)

    canvas = tk.Canvas(root, cursor="cross", bg="black", highlightthickness=0)
    canvas.pack(fill="both", expand=True)
    canvas.create_text(30, 30, anchor="nw", fill="white",
                       font=("Segoe UI Semibold", 16),
                       text="Drag over the question area. Press Esc to cancel.")

    state = {"x": 0, "y": 0, "rect": None}

    def on_press(e):
        state["x"], state["y"] = e.x, e.y
        if state["rect"]:
            canvas.delete(state["rect"])
        state["rect"] = canvas.create_rectangle(e.x, e.y, e.x, e.y,
                                                outline="#22d3a4", width=2,
                                                fill="#22d3a4", stipple="gray25")

    def on_drag(e):
        if state["rect"]:
            canvas.coords(state["rect"], state["x"], state["y"], e.x, e.y)

    def on_release(e):
        result["bbox"] = (
            min(state["x"], e.x), min(state["y"], e.y),
            max(state["x"], e.x), max(state["y"], e.y),
        )
        root.destroy()

    def on_esc(_e):
        root.destroy()

    canvas.bind("<ButtonPress-1>", on_press)
    canvas.bind("<B1-Motion>", on_drag)
    canvas.bind("<ButtonRelease-1>", on_release)
    root.bind("<Escape>", on_esc)
    root.mainloop()
    return result["bbox"]


# ── Python API exposed to the JS frontend ────────────────────────────────────
class API:
    def __init__(self):
        self.window = None          # set after webview.create_window
        self.bbox = None
        self.running = True
        self.processing = False
        self.auto_mode = False
        self.auto_interval_ms = 3000
        self.current_answer = ""
        self.last_question = ""
        self._answer_queue = queue.Queue()
        self._global_listener = None
        self._auto_timer = None

        # start background answer worker
        threading.Thread(target=self._answer_worker, daemon=True).start()

    # ── called by JS ─────────────────────────────────────────────────────────

    def select_area(self):
        """Launch selector in a background thread — never blocks the main loop."""
        threading.Thread(target=self._select_area_thread, daemon=True).start()

    def _select_area_thread(self):
        import time
        self._emit("onStatus", "Draw a box around the question area…", "info")
        self.window.hide()
        time.sleep(0.15)          # let the window fully disappear first
        bbox = select_area_blocking()
        self.window.show()
        if bbox:
            self.bbox = bbox
            self._emit("onStatus", "Area locked — ready to capture.", "ready")
        else:
            if self.bbox:
                self._emit("onStatus", "Cancelled — previous area still active.", "warning")
            else:
                self._emit("onStatus", "No area selected. Click Select Area to begin.", "warning")

    def capture_ai(self):
        self._trigger_capture(in_depth=False)

    def capture_indepth(self):
        self._trigger_capture(in_depth=True)

    def capture_fullscreen(self):
        self._trigger_capture(in_depth=False, fullscreen=True)

    def toggle_auto(self):
        if self.auto_mode:
            self.auto_mode = False
            self._emit("onAutoChanged", False)
            self._emit("onStatus", "Auto mode stopped.", "warning")
        else:
            if not self.bbox:
                self._emit("onStatus", "Select an area first.", "warning")
                return False
            self.auto_mode = True
            self._emit("onAutoChanged", True)
            self._emit("onStatus", "Auto 3s active — watching for changes…", "ready")
            threading.Thread(target=self._auto_tick, daemon=True).start()
        return self.auto_mode

    def copy_answer(self):
        if not self.current_answer:
            self._emit("onStatus", "No answer to copy yet.", "warning")
            return
        # Use JS clipboard API via eval
        safe = self.current_answer.replace("\\", "\\\\").replace("`", "\\`")
        self.window.evaluate_js(
            f"navigator.clipboard.writeText(`{safe}`).catch(()=>{{}})"
        )
        self._emit("onStatus", "Answer copied to clipboard.", "ready")

    def exit_app(self):
        self.running = False
        self.auto_mode = False
        if self._global_listener:
            self._global_listener.stop()
        self.window.destroy()

    # ── internal helpers ─────────────────────────────────────────────────────

    def _emit(self, event, *args):
        """Call a JS function on the page."""
        if not self.window:
            return
        import json
        arg_str = ", ".join(json.dumps(a) for a in args)
        try:
            self.window.evaluate_js(f"window.{event} && window.{event}({arg_str})")
        except Exception:
            pass

    def _trigger_capture(self, in_depth=False, fullscreen=False):
        if self.processing:
            self._emit("onStatus", "Already processing — please wait.", "warning")
            return
        bbox = None if fullscreen else self.bbox
        if not fullscreen and not self.bbox:
            self._emit("onStatus", "No area selected. Click Capture Area first.", "warning")
            return
        threading.Thread(target=self._do_capture, args=(bbox, in_depth), daemon=True).start()

    def _do_capture(self, bbox, in_depth):
        self.processing = True
        label = "selected area" if bbox else "full screen"
        self._emit("onStatus", f"Running OCR on {label}…", "info")
        self._emit("onProcessing", True)

        question = self._ocr(bbox)
        if question is None:
            self.processing = False
            self._emit("onProcessing", False)
            return
        if not question:
            self._emit("onStatus", "OCR found no text. Try a tighter selection.", "error")
            self._emit("onQuestion", "No readable text detected.")
            self._emit("onAnswer", "OCR returned nothing.\n\nRe-select the area and press F8.", "error")
            self.processing = False
            self._emit("onProcessing", False)
            return

        self.last_question = question
        self.current_answer = ""
        self._emit("onQuestion", question)
        mode = "in-depth answer" if in_depth else "answer"
        self._emit("onStatus", f"Question captured. Generating {mode}…", "info")
        self._emit("onAnswer", "Thinking…", "loading")
        self._answer_queue.put({"question": question, "in_depth": in_depth})

    def _ocr(self, bbox):
        _lazy_imports()
        if not os.path.exists(TESSERACT_CMD):
            self._emit("onStatus", "Tesseract not found.", "error")
            self._emit("onAnswer",
                       f"Tesseract OCR is missing.\n\nExpected:\n"
                       f"{TESSERACT_CMD}\n\n"
                       "Install it or set TESSERACT_CMD in .env", "error")
            return None
        _pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD
        try:
            shot = _ImageGrab.grab(bbox=bbox)
            gray = _ImageOps.grayscale(shot)
            boosted = gray.point(lambda p: 255 if p > 155 else 0, mode="1")
            text = _pytesseract.image_to_string(boosted, config="--oem 3 --psm 6").strip()
            if not text:
                text = _pytesseract.image_to_string(gray, config="--oem 3 --psm 6").strip()
            return " ".join(text.split())
        except Exception as exc:
            self._emit("onStatus", "OCR failed.", "error")
            self._emit("onAnswer", f"OCR error:\n{exc}", "error")
            return None

    def _answer_worker(self):
        while self.running:
            job = self._answer_queue.get()
            if job is None:
                break
            answer = self._call_ai(job["question"], job["in_depth"])
            self.current_answer = answer
            self.processing = False
            tone = "error" if answer.startswith(("API Error:", "AI Error:")) else "answer"
            self._emit("onAnswer", answer, tone)
            if tone == "answer":
                self._emit("onStatus", "Answer ready. Press F9 to copy.", "ready")
            else:
                self._emit("onStatus", "Request failed — see answer box.", "error")
            self._emit("onProcessing", False)
            self._answer_queue.task_done()

    def _auto_tick(self):
        import time
        while self.running and self.auto_mode:
            time.sleep(self.auto_interval_ms / 1000)
            if not self.auto_mode or self.processing or not self.bbox:
                continue
            question = self._ocr(self.bbox)
            if question and question != self.last_question:
                self.last_question = question
                self.current_answer = ""
                self._emit("onQuestion", question)
                self._emit("onStatus", "New question detected. Generating answer…", "info")
                self._emit("onAnswer", "Thinking…", "loading")
                self._emit("onProcessing", True)
                self.processing = True
                self._answer_queue.put({"question": question, "in_depth": False})

    def _call_ai(self, question, in_depth=False):
        api_key = AI_API_CONFIG["api_key"]
        if not api_key:
            return ("API Error: No API key set.\n\n"
                    "Add to .env:\nGROQ_API_KEY=your_key\n"
                    "GROQ_MODEL=llama-3.1-8b-instant\n"
                    "GROQ_API_URL=https://api.groq.com/openai/v1/chat/completions")

        system = (
            "You answer quiz questions clearly and thoroughly. Start with a direct answer, "
            "then give a compact explanation with key facts."
            if in_depth else
            "You answer quiz questions. Give a short direct answer first, then one brief "
            "explanation line if needed. If OCR text looks incomplete, say so."
        )
        try:
            _lazy_imports()
            r = _requests.post(
                AI_API_CONFIG["url"],
                headers={"Authorization": f"Bearer {api_key}",
                         "Content-Type": "application/json"},
                json={"model": AI_API_CONFIG["model"],
                      "messages": [{"role": "system", "content": system},
                                   {"role": "user", "content": question}],
                      "max_tokens": 420 if in_depth else 220,
                      "temperature": 0.1},
                timeout=20,
            )
        except Exception as exc:
            return f"AI Error: {exc}"

        if r.status_code != 200:
            detail = r.text.strip()[:280]
            return f"API Error: {r.status_code}\n{detail}"

        try:
            return r.json()["choices"][0]["message"]["content"].strip()
        except Exception as exc:
            return f"AI Error: Could not parse response ({exc})"

    def start_hotkeys(self):
        def on_press(key):
            try:
                if key == _pynput_keyboard.Key.f8:
                    self._trigger_capture(in_depth=False)
                elif key == _pynput_keyboard.Key.f9:
                    self.copy_answer()
                elif key == _pynput_keyboard.Key.esc:
                    self.exit_app()
            except Exception:
                pass

        _lazy_imports()
        self._global_listener = _pynput_keyboard.Listener(on_press=on_press)
        self._global_listener.daemon = True
        self._global_listener.start()


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # Calculate top-right position using tkinter (already a dependency)
    import tkinter as _tk
    _r = _tk.Tk(); _r.withdraw()
    _sw, _sh = _r.winfo_screenwidth(), _r.winfo_screenheight()
    _r.destroy()
    WIN_W, WIN_H, MARGIN = 360, 530, 18
    START_X = _sw - WIN_W - MARGIN
    START_Y = MARGIN

    api = API()
    html_path = os.path.join(BASE_DIR, "ui.html")

    window = webview.create_window(
        title="OpenQuiz",
        url=html_path,
        js_api=api,
        width=WIN_W,
        height=WIN_H,
        x=START_X,
        y=START_Y,
        resizable=False,
        frameless=True,
        on_top=True,
        background_color="#111827",
        min_size=(WIN_W, WIN_H),
    )
    api.window = window

    def on_loaded():
        import time
        def _ready():
            time.sleep(0.3)
            api._emit("onStatus", "Click 'Select Area' to begin.", "info")
            # Pre-warm heavy imports in background so first capture is instant
            _lazy_imports()
            api.start_hotkeys()
        threading.Thread(target=_ready, daemon=True).start()

    window.events.loaded += on_loaded
    webview.start(debug=False)