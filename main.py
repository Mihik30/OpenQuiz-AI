import os
import queue
import threading
import logging
from urllib.parse import urlparse
logging.getLogger('pywebview').setLevel(logging.CRITICAL)
import webview
import ctypes
from ctypes import wintypes

try:
    import win32api
    import win32con
    import win32gui
except ImportError:
    win32api = None
    win32con = None
    win32gui = None

# Heavy imports — loaded lazily on first use to keep startup fast
_pytesseract = None
_requests = None
_ImageGrab = None
_ImageOps = None
_pynput_keyboard = None

GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000
WM_MOUSEACTIVATE = 0x0021
MA_NOACTIVATE = 3

UINT_PTR = getattr(wintypes, "UINT_PTR", wintypes.WPARAM)
DWORD_PTR = getattr(wintypes, "DWORD_PTR", wintypes.LPARAM)
LRESULT = ctypes.c_longlong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_long


def _find_window_hwnd(window):
    hwnd = getattr(window, "hwnd", None)
    if hwnd:
        return hwnd

    if not win32gui:
        return None

    title = getattr(window, "title", "")
    if title:
        hwnd = win32gui.FindWindow(None, title)
        if hwnd:
            return hwnd

    handles = []

    def callback(candidate, extra):
        if win32gui.IsWindowVisible(candidate):
            text = win32gui.GetWindowText(candidate)
            if title and title in text:
                extra.append(candidate)
        return True

    win32gui.EnumWindows(callback, handles)
    return handles[0] if handles else None


def setup_no_activate_subclass(window):
    """Keep the pywebview overlay clickable without activating it."""
    if os.name != "nt":
        return False
    if not win32gui:
        print("pywin32 is required for no-activate window behavior")
        return False

    hwnd = _find_window_hwnd(window)
    if not hwnd:
        print("Could not find window handle")
        return False

    exstyle = win32gui.GetWindowLong(hwnd, GWL_EXSTYLE)
    win32gui.SetWindowLong(hwnd, GWL_EXSTYLE, exstyle | WS_EX_NOACTIVATE)

    comctl32 = ctypes.windll.comctl32
    comctl32.DefSubclassProc.restype = LRESULT
    comctl32.DefSubclassProc.argtypes = (
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    )
    comctl32.SetWindowSubclass.restype = wintypes.BOOL

    SUBCLASSPROC = ctypes.WINFUNCTYPE(
        LRESULT,
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
        UINT_PTR,
        DWORD_PTR,
    )

    def subclass_proc(hwnd, msg, wparam, lparam, uidsubclass, dwrefdata):
        if msg == WM_MOUSEACTIVATE:
            return MA_NOACTIVATE
        return comctl32.DefSubclassProc(hwnd, msg, wparam, lparam)

    c_subclass = SUBCLASSPROC(subclass_proc)
    window._c_subclass = c_subclass
    comctl32.SetWindowSubclass.argtypes = (
        wintypes.HWND,
        SUBCLASSPROC,
        UINT_PTR,
        DWORD_PTR,
    )
    installed = comctl32.SetWindowSubclass(hwnd, c_subclass, 1, 0)
    if not installed:
        error_code = win32api.GetLastError() if win32api else ctypes.get_last_error()
        print(f"Could not install window subclass: {error_code}")
        return False

    print("No-activate window subclass installed")
    return True

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

MODEL_CONFIGS = {
    "qwen": {
        "label": "Qwen",
        "url": first_env("HF_API_URL", "HUGGINGFACE_API_URL",
                         default="https://router.huggingface.co/v1/chat/completions"),
        "api_key": first_env("HF_API_KEY", "HUGGINGFACE_API_KEY", "HF_TOKEN"),
        "model": first_env("QWEN_MODEL", default="Qwen/Qwen3-32B:fastest"),
        "key_hint": "HF_API_KEY=your_huggingface_token",
    },
    "deepseek": {
        "label": "DeepSeek",
        "url": first_env("HF_API_URL", "HUGGINGFACE_API_URL",
                         default="https://router.huggingface.co/v1/chat/completions"),
        "api_key": first_env("HF_API_KEY", "HUGGINGFACE_API_KEY", "HF_TOKEN"),
        "model": first_env("DEEPSEEK_MODEL", default="deepseek-ai/DeepSeek-R1:fastest"),
        "key_hint": "HF_API_KEY=your_huggingface_token",
    },
    "llama": {
        "label": "Llama",
        "url": first_env("GROQ_API_URL", "AI_API_URL",
                         default="https://api.groq.com/openai/v1/chat/completions"),
        "api_key": first_env("GROQ_API_KEY", "AI_API_KEY"),
        "model": first_env("GROQ_MODEL", "LLAMA_MODEL",
                           default="llama-3.3-70b-versatile"),
        "key_hint": "GROQ_API_KEY=your_groq_key",
    },
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
        self.selected_model = first_env("DEFAULT_MODEL", default="llama").lower()
        if self.selected_model not in MODEL_CONFIGS:
            self.selected_model = "llama"
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

    def set_model(self, model_key):
        model_key = (model_key or "").lower()
        if model_key not in MODEL_CONFIGS:
            self._emit("onStatus", "Unknown model selection.", "warning")
            return self.selected_model
        self.selected_model = model_key
        label = MODEL_CONFIGS[model_key]["label"]
        self._emit("onModelChanged", model_key)
        self._emit("onStatus", f"{label} selected.", "ready")
        return self.selected_model

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
        self._answer_queue.put({
            "question": question,
            "in_depth": in_depth,
            "model_key": self.selected_model,
        })

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
            answer = self._call_ai(job["question"], job["in_depth"], job.get("model_key"))
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
                self._answer_queue.put({
                    "question": question,
                    "in_depth": False,
                    "model_key": self.selected_model,
                })

    def _call_ai(self, question, in_depth=False, model_key=None):
        config = MODEL_CONFIGS.get(model_key or self.selected_model, MODEL_CONFIGS["llama"])
        api_key = config["api_key"]
        if not api_key:
            return ("API Error: No API key set.\n\n"
                    f"Selected model: {config['label']}\n\n"
                    f"Add to .env:\n{config['key_hint']}")

        system = (
            "You answer quiz questions from OCR text. The OCR may contain mistakes or "
            "missing words. If the question is incomplete, ambiguous, or unreadable, say "
            "that clearly instead of guessing. For clear questions, solve carefully and "
            "return exactly:\nAnswer: <final answer>\nWhy: <clear reasoning>\n"
            "Check: <key fact, calculation, or verification>"
            if in_depth else
            "You answer quiz questions from OCR text. The OCR may contain mistakes or "
            "missing words. If the question is incomplete, ambiguous, or unreadable, say "
            "that clearly instead of guessing. For clear questions, return exactly:\n"
            "Answer: <final answer>\nWhy: <brief reason>"
        )
        try:
            _lazy_imports()
            provider = urlparse(config["url"]).netloc or config["url"]
            print(
                "AI request:",
                f"provider={provider}",
                f"model={config['model']}",
                f"label={config['label']}",
                f"question_chars={len(question or '')}",
            )
            r = _requests.post(
                config["url"],
                headers={"Authorization": f"Bearer {api_key}",
                         "Content-Type": "application/json"},
                json={"model": config["model"],
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
    WIN_W, WIN_H, MARGIN = 380, 660, 18
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
        resizable=True,
        frameless=True,
        on_top=True,
        background_color="#111827",
        min_size=(360, 560),
    )
    api.window = window

    def on_loaded():
        import time
        setup_no_activate_subclass(window)

        def _ready():
            time.sleep(0.3)
            api._emit("onStatus", "Click 'Select Area' to begin.", "info")
            api._emit("onModelChanged", api.selected_model)
            # Pre-warm heavy imports in background so first capture is instant
            _lazy_imports()
            api.start_hotkeys()
        threading.Thread(target=_ready, daemon=True).start()

    window.events.loaded += on_loaded
    webview.start(debug=False)
