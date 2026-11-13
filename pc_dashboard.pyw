"""PC Dashboard: a small desktop widget with live PC stats and a to-do list.

Run it by double-clicking this file (the .pyw extension runs it without a
console window), or from a terminal with:  pythonw pc_dashboard.pyw

Drag the title bar to move it. Right-click anywhere for options.
"""

import ctypes
import json
import os
import sys
import time
import tkinter as tk
from tkinter import font as tkfont

import psutil

APP_NAME = "PCDashboard"
DATA_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), APP_NAME)
TODO_FILE = os.path.join(DATA_DIR, "todos.json")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")

REFRESH_MS = 1000  # how often stats update
WIDTH = 290        # widget width in pixels
MARGIN = 16        # gap from the screen edge
PAD = 14           # inner padding
BAR_HEIGHT = 6

C = {
    "bg": "#15171c",
    "panel": "#1d2027",
    "text": "#e6e8ee",
    "muted": "#8a90a0",
    "accent": "#4c9aff",
    "good": "#3ecf8e",
    "warn": "#f5a524",
    "bad": "#f2555a",
    "track": "#2b2f38",
}

DEFAULT_SETTINGS = {
    "corner": "top-right",  # top-right, top-left, bottom-right, bottom-left, custom
    "x": None,
    "y": None,
    "topmost": False,
    "alpha": 0.94,
}


# ---------------------------------------------------------------- helpers

def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save_json(path, data):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)
    except OSError:
        pass


def fmt_bytes(n, per_sec=False):
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    n = float(n)
    while n >= 1024 and i < len(units) - 1:
        n /= 1024
        i += 1
    text = f"{n:.0f} {units[i]}" if i == 0 or n >= 100 else f"{n:.1f} {units[i]}"
    return text + ("/s" if per_sec else "")


def fmt_duration(seconds):
    seconds = int(seconds)
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes = seconds // 60
    if days:
        return f"{days}d {hours}h {minutes}m"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def level_color(pct):
    if pct < 60:
        return C["good"]
    if pct < 85:
        return C["warn"]
    return C["bad"]


def work_area(root):
    """Usable screen area (excludes the taskbar) as (left, top, right, bottom)."""
    try:
        from ctypes import wintypes
        rect = wintypes.RECT()
        SPI_GETWORKAREA = 0x0030
        if ctypes.windll.user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(rect), 0):
            return rect.left, rect.top, rect.right, rect.bottom
    except Exception:
        pass
    return 0, 0, root.winfo_screenwidth(), root.winfo_screenheight()


def already_running():
    """Use a named Windows mutex so only one dashboard runs at a time."""
    try:
        kernel32 = ctypes.windll.kernel32
        already_running._handle = kernel32.CreateMutexW(None, False, "Local\\PCDashboardSingleInstance")
        ERROR_ALREADY_EXISTS = 183
        return kernel32.GetLastError() == ERROR_ALREADY_EXISTS
    except Exception:
        return False


# ---------------------------------------------------------- start with Windows

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def startup_command():
    exe = sys.executable
    pythonw = os.path.join(os.path.dirname(exe), "pythonw.exe")
    if os.path.exists(pythonw):
        exe = pythonw
    return f'"{exe}" "{os.path.abspath(__file__)}"'


def startup_enabled():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, APP_NAME)
        return True
    except OSError:
        return False


def set_startup(enabled):
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, startup_command())
            else:
                try:
                    winreg.DeleteValue(key, APP_NAME)
                except FileNotFoundError:
                    pass
    except OSError:
        pass


# ------------------------------------------------------------------- widget

class Dashboard:
    def __init__(self):
        self.settings = dict(DEFAULT_SETTINGS)
        saved = load_json(SETTINGS_FILE, {})
        if isinstance(saved, dict):
            self.settings.update(saved)

        todos = load_json(TODO_FILE, [])
        self.todos = [t for t in todos if isinstance(t, dict) and "text" in t] if isinstance(todos, list) else []

        self.root = tk.Tk()
        self.root.title("PC Dashboard")
        self.root.overrideredirect(True)  # no title bar / borders
        self.root.configure(bg=C["bg"])
        self.root.attributes("-alpha", self.settings["alpha"])
        self.root.attributes("-topmost", bool(self.settings["topmost"]))

        family = "Segoe UI"
        self.f_title = tkfont.Font(family=family, size=10, weight="bold")
        self.f_section = tkfont.Font(family=family, size=8, weight="bold")
        self.f_label = tkfont.Font(family=family, size=9)
        self.f_value = tkfont.Font(family=family, size=9, weight="bold")
        self.f_body = tkfont.Font(family=family, size=9)
        self.f_done = tkfont.Font(family=family, size=9, overstrike=1)
        self.f_box = tkfont.Font(family=family, size=11)

        self._drag = None
        self._placeholder_on = False

        self.build_ui()
        self.build_menu()

        psutil.cpu_percent(None)  # first call primes the CPU counter
        self.last_net = psutil.net_io_counters()
        self.last_net_time = time.monotonic()
        self.disk_path = os.environ.get("SystemDrive", "C:") + "\\"

        self.render_todos()
        self.update_stats()

    # ---------------------------------------------------------- layout

    def build_ui(self):
        self.container = tk.Frame(self.root, bg=C["bg"], padx=1, pady=1)
        self.container.pack(fill="both", expand=True)

        # Header (drag handle)
        header = tk.Frame(self.container, bg=C["bg"], padx=PAD, pady=8)
        header.pack(fill="x")
        title = tk.Label(header, text="PC Dashboard", font=self.f_title, fg=C["text"], bg=C["bg"])
        title.pack(side="left")
        close = tk.Label(header, text="✕", font=self.f_label, fg=C["muted"], bg=C["bg"], cursor="hand2")
        close.pack(side="right")
        close.bind("<Button-1>", lambda e: self.quit())
        close.bind("<Enter>", lambda e: close.config(fg=C["bad"]))
        close.bind("<Leave>", lambda e: close.config(fg=C["muted"]))
        self.clock = tk.Label(header, text="", font=self.f_label, fg=C["muted"], bg=C["bg"])
        self.clock.pack(side="right", padx=(0, 10))
        for w in (header, title, self.clock):
            w.bind("<ButtonPress-1>", self.start_drag)
            w.bind("<B1-Motion>", self.on_drag)
            w.bind("<ButtonRelease-1>", self.end_drag)
            w.config(cursor="fleur")

        # Stats panel
        stats = self.panel("SYSTEM")
        self.cpu_val, self.cpu_bar = self.bar_row(stats, "CPU")
        self.ram_val, self.ram_bar = self.bar_row(stats, "Memory")
        self.disk_val, self.disk_bar = self.bar_row(stats, "Disk (C:)")
        self.net_val = self.info_row(stats, "Network")
        self.up_val = self.info_row(stats, "Uptime")
        self.batt_row = tk.Frame(stats, bg=C["panel"])
        self.batt_val = self.info_row(stats, "Battery", frame=self.batt_row)

        # To-do panel
        todo = self.panel("TO-DO", right_text="Clear done", right_cmd=self.clear_done)
        self.entry = tk.Entry(
            todo, font=self.f_body, bg=C["track"], fg=C["text"], insertbackground=C["text"],
            relief="flat", highlightthickness=1, highlightbackground=C["track"],
            highlightcolor=C["accent"],
        )
        self.entry.pack(fill="x", ipady=4, pady=(0, 8))
        self.entry.bind("<Return>", self.add_todo)
        self.entry.bind("<FocusIn>", self.hide_placeholder)
        self.entry.bind("<FocusOut>", self.show_placeholder)
        self.entry.bind("<Button-1>", lambda e: self.entry.focus_force())
        self.show_placeholder()

        self.todo_list = tk.Frame(todo, bg=C["panel"])
        self.todo_list.pack(fill="x")

        tk.Frame(self.container, bg=C["bg"], height=PAD - 4).pack(fill="x")

    def panel(self, title, right_text=None, right_cmd=None):
        outer = tk.Frame(self.container, bg=C["panel"], padx=PAD, pady=10)
        outer.pack(fill="x", padx=PAD - 4, pady=(0, 8))
        head = tk.Frame(outer, bg=C["panel"])
        head.pack(fill="x", pady=(0, 8))
        tk.Label(head, text=title, font=self.f_section, fg=C["muted"], bg=C["panel"]).pack(side="left")
        if right_text:
            link = tk.Label(head, text=right_text, font=self.f_label, fg=C["accent"], bg=C["panel"], cursor="hand2")
            link.pack(side="right")
            link.bind("<Button-1>", lambda e: right_cmd())
            self.done_link = link
        return outer

    def bar_row(self, parent, name):
        row = tk.Frame(parent, bg=C["panel"])
        row.pack(fill="x", pady=(0, 8))
        top = tk.Frame(row, bg=C["panel"])
        top.pack(fill="x")
        tk.Label(top, text=name, font=self.f_label, fg=C["muted"], bg=C["panel"]).pack(side="left")
        value = tk.Label(top, text="…", font=self.f_value, fg=C["text"], bg=C["panel"])
        value.pack(side="right")
        bar = tk.Canvas(row, height=BAR_HEIGHT, bg=C["panel"], highlightthickness=0)
        bar.pack(fill="x", pady=(4, 0))
        return value, bar

    def info_row(self, parent, name, frame=None):
        row = frame or tk.Frame(parent, bg=C["panel"])
        if frame is None:
            row.pack(fill="x", pady=(0, 3))
        tk.Label(row, text=name, font=self.f_label, fg=C["muted"], bg=C["panel"]).pack(side="left")
        value = tk.Label(row, text="…", font=self.f_value, fg=C["text"], bg=C["panel"])
        value.pack(side="right")
        return value

    def draw_bar(self, canvas, pct):
        canvas.delete("all")
        w = canvas.winfo_width()
        if w <= 1:
            w = WIDTH - 4 * PAD
        canvas.create_rectangle(0, 0, w, BAR_HEIGHT, fill=C["track"], width=0)
        fill = max(0.0, min(100.0, pct)) / 100 * w
        if fill > 0:
            canvas.create_rectangle(0, 0, fill, BAR_HEIGHT, fill=level_color(pct), width=0)

    # ------------------------------------------------------------ stats

    def update_stats(self):
        try:
            self.clock.config(text=time.strftime("%I:%M %p").lstrip("0"))

            cpu = psutil.cpu_percent(None)
            self.cpu_val.config(text=f"{cpu:.0f}%")
            self.draw_bar(self.cpu_bar, cpu)

            mem = psutil.virtual_memory()
            self.ram_val.config(text=f"{fmt_bytes(mem.used)} / {fmt_bytes(mem.total)}")
            self.draw_bar(self.ram_bar, mem.percent)

            disk = psutil.disk_usage(self.disk_path)
            self.disk_val.config(text=f"{fmt_bytes(disk.free)} free")
            self.draw_bar(self.disk_bar, disk.percent)

            now = time.monotonic()
            net = psutil.net_io_counters()
            dt = max(now - self.last_net_time, 0.001)
            down = max(net.bytes_recv - self.last_net.bytes_recv, 0) / dt
            up = max(net.bytes_sent - self.last_net.bytes_sent, 0) / dt
            self.last_net, self.last_net_time = net, now
            self.net_val.config(text=f"↓ {fmt_bytes(down, True)}   ↑ {fmt_bytes(up, True)}")

            self.up_val.config(text=fmt_duration(time.time() - psutil.boot_time()))

            batt = psutil.sensors_battery()
            if batt is not None:
                plug = " ⚡" if batt.power_plugged else ""
                self.batt_val.config(text=f"{batt.percent:.0f}%{plug}")
                if not self.batt_row.winfo_ismapped():
                    self.batt_row.pack(fill="x", pady=(0, 3))
                    self.place_window()
        except Exception:
            pass  # never let one bad reading stop the loop
        self.root.after(REFRESH_MS, self.update_stats)

    # ------------------------------------------------------------ to-do

    def show_placeholder(self, event=None):
        if not self.entry.get():
            self._placeholder_on = True
            self.entry.config(fg=C["muted"])
            self.entry.insert(0, "Add a task and press Enter")

    def hide_placeholder(self, event=None):
        if self._placeholder_on:
            self._placeholder_on = False
            self.entry.delete(0, "end")
            self.entry.config(fg=C["text"])

    def add_todo(self, event=None):
        if self._placeholder_on:
            return
        text = self.entry.get().strip()
        if text:
            self.todos.append({"text": text, "done": False})
            self.save_todos()
            self.render_todos()
        self.entry.delete(0, "end")

    def toggle_todo(self, index):
        self.todos[index]["done"] = not self.todos[index].get("done", False)
        self.save_todos()
        self.render_todos()

    def delete_todo(self, index):
        del self.todos[index]
        self.save_todos()
        self.render_todos()

    def clear_done(self):
        self.todos = [t for t in self.todos if not t.get("done")]
        self.save_todos()
        self.render_todos()

    def save_todos(self):
        save_json(TODO_FILE, self.todos)

    def render_todos(self):
        for child in self.todo_list.winfo_children():
            child.destroy()

        if not self.todos:
            tk.Label(self.todo_list, text="Nothing to do. Nice!", font=self.f_body,
                     fg=C["muted"], bg=C["panel"]).pack(anchor="w")

        wrap = WIDTH - 4 * PAD - 50
        for i, item in enumerate(self.todos):
            done = bool(item.get("done"))
            row = tk.Frame(self.todo_list, bg=C["panel"])
            row.pack(fill="x", pady=1)

            box = tk.Label(row, text="☑" if done else "☐", font=self.f_box,
                           fg=C["good"] if done else C["muted"], bg=C["panel"], cursor="hand2")
            box.pack(side="left", anchor="n")

            text = tk.Label(row, text=item["text"], font=self.f_done if done else self.f_body,
                            fg=C["muted"] if done else C["text"], bg=C["panel"], anchor="w",
                            justify="left", wraplength=wrap, cursor="hand2")
            text.pack(side="left", fill="x", expand=True, padx=(6, 0), pady=(2, 0))

            delete = tk.Label(row, text="✕", font=self.f_label, fg=C["muted"], bg=C["panel"], cursor="hand2")
            delete.pack(side="right", anchor="n", pady=(2, 0))

            for w in (box, text):
                w.bind("<Button-1>", lambda e, i=i: self.toggle_todo(i))
            delete.bind("<Button-1>", lambda e, i=i: self.delete_todo(i))
            delete.bind("<Enter>", lambda e, d=delete: d.config(fg=C["bad"]))
            delete.bind("<Leave>", lambda e, d=delete: d.config(fg=C["muted"]))

        remaining = sum(1 for t in self.todos if not t.get("done"))
        self.done_link.config(fg=C["accent"] if remaining < len(self.todos) else C["track"])
        self.place_window()

    # ---------------------------------------------------- window position

    def place_window(self):
        self.root.update_idletasks()
        w = WIDTH
        h = self.container.winfo_reqheight()
        left, top, right, bottom = work_area(self.root)
        corner = self.settings.get("corner", "top-right")

        if corner == "custom" and self.settings.get("x") is not None:
            x = min(max(int(self.settings["x"]), left), right - w)
            y = min(max(int(self.settings["y"]), top), max(bottom - h, top))
        else:
            x = right - w - MARGIN if "right" in corner else left + MARGIN
            y = top + MARGIN if "top" in corner else bottom - h - MARGIN
        self.root.geometry(f"{w}x{h}+{x}+{y}")

    def start_drag(self, event):
        self._drag = (event.x_root - self.root.winfo_x(), event.y_root - self.root.winfo_y())

    def on_drag(self, event):
        if self._drag:
            dx, dy = self._drag
            self.root.geometry(f"+{event.x_root - dx}+{event.y_root - dy}")

    def end_drag(self, event):
        if self._drag:
            self._drag = None
            self.settings.update(corner="custom", x=self.root.winfo_x(), y=self.root.winfo_y())
            self.corner_var.set("custom")
            self.save_settings()

    def save_settings(self):
        save_json(SETTINGS_FILE, self.settings)

    # ------------------------------------------------------- right-click

    def build_menu(self):
        self.menu = tk.Menu(self.root, tearoff=0)

        self.topmost_var = tk.BooleanVar(value=bool(self.settings["topmost"]))
        self.menu.add_checkbutton(label="Always on top", variable=self.topmost_var, command=self.toggle_topmost)

        self.startup_var = tk.BooleanVar(value=startup_enabled())
        self.menu.add_checkbutton(label="Start with Windows", variable=self.startup_var,
                                  command=lambda: set_startup(self.startup_var.get()))

        corners = tk.Menu(self.menu, tearoff=0)
        self.corner_var = tk.StringVar(value=self.settings["corner"])
        for value, label in (("top-right", "Top right"), ("top-left", "Top left"),
                             ("bottom-right", "Bottom right"), ("bottom-left", "Bottom left")):
            corners.add_radiobutton(label=label, value=value, variable=self.corner_var, command=self.set_corner)
        self.menu.add_cascade(label="Move to corner", menu=corners)

        opacity = tk.Menu(self.menu, tearoff=0)
        self.alpha_var = tk.DoubleVar(value=self.settings["alpha"])
        for value in (1.0, 0.94, 0.85, 0.75):
            opacity.add_radiobutton(label=f"{int(value * 100)}%", value=value, variable=self.alpha_var,
                                    command=self.set_alpha)
        self.menu.add_cascade(label="Opacity", menu=opacity)

        self.menu.add_separator()
        self.menu.add_command(label="Quit", command=self.quit)

        self.root.bind_all("<Button-3>", self.show_menu)

    def show_menu(self, event):
        self.startup_var.set(startup_enabled())
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()

    def toggle_topmost(self):
        self.settings["topmost"] = self.topmost_var.get()
        self.root.attributes("-topmost", self.settings["topmost"])
        self.save_settings()

    def set_corner(self):
        self.settings["corner"] = self.corner_var.get()
        self.save_settings()
        self.place_window()

    def set_alpha(self):
        self.settings["alpha"] = self.alpha_var.get()
        self.root.attributes("-alpha", self.settings["alpha"])
        self.save_settings()

    # -------------------------------------------------------------- run

    def quit(self):
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    if not already_running():
        Dashboard().run()
