import pytesseract
from PIL import Image, ImageGrab
import tkinter as tk
from pynput import keyboard
import pyperclip
import time

# --- CONFIGURATION ---
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

class AreaSelector:
    def __init__(self):
        self.root = tk.Tk()
        self.root.attributes('-alpha', 0.3)  # Make window transparent
        self.root.attributes('-fullscreen', True)
        self.root.attributes("-topmost", True)
        self.canvas = tk.Canvas(self.root, cursor="cross", bg="grey")
        self.canvas.pack(fill="both", expand=True)
        
        self.start_x = None
        self.start_y = None
        self.rect = None
        self.bbox = None

        self.canvas.bind("<ButtonPress-1>", self.on_button_press)
        self.canvas.bind("<B1-Motion>", self.on_move_press)
        self.canvas.bind("<ButtonRelease-1>", self.on_button_release)
        self.root.bind("<Escape>", lambda e: self.root.destroy())

    def on_button_press(self, event):
        self.start_x = event.x
        self.start_y = event.y
        self.rect = self.canvas.create_rectangle(self.start_x, self.start_y, 1, 1, outline='red', width=3)

    def on_move_press(self, event):
        self.canvas.coords(self.rect, self.start_x, self.start_y, event.x, event.y)

    def on_button_release(self, event):
        # Save the coordinates (left, top, right, bottom)
        self.bbox = (min(self.start_x, event.x), min(self.start_y, event.y), 
                     max(self.start_x, event.x), max(self.start_y, event.y))
        self.root.destroy()

# 1. Run Area Selection
print("STEP 1: Draw a box over the question area on your screen.")
selector = AreaSelector()
selector.root.mainloop()
selected_bbox = selector.bbox

if not selected_bbox:
    print("No area selected. Exiting.")
    exit()

print(f"Area Locked: {selected_bbox}")
questions_list = []

# 2. Setup Background Listener
def on_press(key):
    try:
        if key == keyboard.Key.f8:
            # Capture only the pre-selected box
            screenshot = ImageGrab.grab(bbox=selected_bbox)
            text = pytesseract.image_to_string(screenshot).strip()
            
            if text:
                questions_list.append(text)
                print(f"Captured Question {len(questions_list)}!")
            else:
                print("Capture failed - text not recognized.")

        if key == keyboard.Key.esc:
            return False
    except Exception as e:
        print(f"Error during capture: {e}")

print("\nSTEP 2: Quiz Mode Active")
print("- Press 'F8' to capture the question in your box.")
print("- Press 'ESC' when finished with all questions.")

with keyboard.Listener(on_press=on_press) as listener:
    listener.join()

# 3. Final Output
final_output = "\n\n--- NEXT QUESTION ---\n\n".join(questions_list)
pyperclip.copy(final_output)

print("\n" + "="*40)
print(f"SUCCESS: {len(questions_list)} questions copied to clipboard!")
print("Paste them into the chat now.")
print("="*40)