#!/usr/bin/env python3
"""GearUp – Graphical Interface"""
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import ttk
import os
import shutil
import time
import re
import psutil
from pathlib import Path
from tkinter import filedialog, messagebox

APP_NAME    = "GearUp"
APP_VERSION = "v1.0.0"
APP_SUBTITLE = "Modding Toolkit"

TOOLKIT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
CLI     = TOOLKIT / "srs_cli.py"
ROOT    = TOOLKIT.parent
WS_ARC  = ROOT / "SRS Workspace" / "archive.ar"
WS_MOD  = ROOT / "SRS Workspace" / "modeles"

BG        = "#0f0f0f"
PANEL_BG  = "#181818"
HDR_BG    = "#111111"
ACCENT    = "#DC354F"
ACCENT_DARK = "#9c2538"
ACCENT2   = "#1f1f1f"
FG        = "#dcdcdc"
FG_DIM    = "#7a7a7a"
LOG_BG    = "#080808"
BTN_DEF   = "#222222"
BTN_HOV   = "#2f2f2f"
BTN_ACT   = "#00a2ff"

THEME_FONT = "Segoe UI"
FONT_UI   = (THEME_FONT, 10)
FONT_BOLD = (THEME_FONT, 10, "bold")
FONT_TINY = (THEME_FONT, 8)
FONT_LOG  = ("Consolas", 10)
FONT_LOGH = ("Consolas", 10, "bold")
LOG_MAX_LINES = 8000
LOG_TRIM_TO = 6000
POLL_INTERVAL_MS = 80
MAX_QUEUE_ITEMS_PER_TICK = 600


def _is_python_launcher(exe: str) -> bool:
    name = Path(exe).name.lower()
    return name.startswith("python") or name in ("py", "py.exe")


def _find_runner() -> str | None:
    """Return a usable runner for CLI work.

    Prefers a real Python interpreter; falls back to this executable which can
    execute CLI args via the __main__ switch below.
    """
    own = Path(sys.executable).resolve()

    if _is_python_launcher(str(own)):
        return str(own)

    for name in ("py", "python", "python3"):
        found = shutil.which(name)
        if found:
            found_path = Path(found).resolve()
            if _is_python_launcher(str(found_path)) and found_path != own:
                return str(found_path)

    # Fallback for frozen/no-python installs: run this executable in CLI mode.
    return str(own) if own.exists() else None


def _run_worker(args: list[str], q: "queue.Queue", proc_holder: list) -> None:
    runner = _find_runner()
    if runner is None:
        q.put(("line", "ERR: no runtime found for CLI action"))
        q.put(("done", 1))
        return

    if _is_python_launcher(runner):
        cmd = [runner, "-u", str(CLI)] + args
    else:
        cmd = [runner] + args
    popen_kwargs = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "stdin": subprocess.PIPE,
        "text": True,
        "encoding": "utf-8",
        "bufsize": 1,
        "env": {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"},
    }
    if sys.platform == "win32":
        popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

    try:
        proc = subprocess.Popen(cmd, **popen_kwargs)
        if proc.stdin:
            try:
                proc.stdin.write("y\n" * 10)
                proc.stdin.flush()
            except Exception:
                pass
        proc_holder.append(proc)
        for line in proc.stdout:
            q.put(("line", line.rstrip("\r\n")))
        proc.wait()
        q.put(("done", proc.returncode))
    except Exception as exc:
        q.put(("line", f"ERR: {exc}"))
        q.put(("done", 1))
    finally:
        proc_holder.clear()


def _escape_powershell_single_quoted(text: str) -> str:
    return text.replace("'", "''")


def _extract_existing_path(raw_text: str) -> Path | None:
    raw = raw_text.strip().strip('"').strip("'")
    if not raw:
        return None

    direct = Path(raw)
    if direct.exists():
        return direct

    # If the line also contains status text, trim from the end until we
    # find an existing path.
    parts = raw.split()
    if len(parts) > 1:
        for end in range(len(parts) - 1, 0, -1):
            candidate = " ".join(parts[:end]).strip()
            if not candidate:
                continue
            p = Path(candidate)
            if p.exists():
                return p

    return None


def _reveal_in_windows_explorer(target: Path) -> bool:
    if sys.platform != "win32" or not target.exists():
        return False

    target = target.resolve()
    folder = target if target.is_dir() else target.parent
    target_str = _escape_powershell_single_quoted(str(target))
    folder_str = _escape_powershell_single_quoted(str(folder))
    file_name_str = _escape_powershell_single_quoted(target.name)

    script = f"""
$target = [System.IO.Path]::GetFullPath('{target_str}')
$folder = [System.IO.Path]::GetFullPath('{folder_str}')
$fileName = '{file_name_str}'
$shell = New-Object -ComObject Shell.Application
$window = $null
foreach ($candidate in @($shell.Windows())) {{
    try {{
        if (-not $candidate.FullName -or -not $candidate.FullName.ToLower().EndsWith('explorer.exe')) {{ continue }}
        $candidateFolder = $null
        try {{
            $candidateFolder = $candidate.Document.Folder.Self.Path
        }} catch {{}}
        if (-not $candidateFolder) {{
            try {{
                $candidateFolder = ([Uri]$candidate.LocationURL).LocalPath
            }} catch {{}}
        }}
        if ($candidateFolder -and ([System.IO.Path]::GetFullPath($candidateFolder) -ieq $folder)) {{
            $window = $candidate
            break
        }}
    }} catch {{}}
}}

if ($window -ne $null) {{
    try {{ $window.Visible = $true }} catch {{}}
    try {{
        Add-Type -Namespace GearUp -Name NativeMethods -MemberDefinition @'
[System.Runtime.InteropServices.DllImport("user32.dll")]
public static extern bool ShowWindowAsync(System.IntPtr hWnd, int nCmdShow);
[System.Runtime.InteropServices.DllImport("user32.dll")]
public static extern bool SetForegroundWindow(System.IntPtr hWnd);
'@ -ErrorAction SilentlyContinue | Out-Null
        [GearUp.NativeMethods]::ShowWindowAsync([System.IntPtr]$window.HWND, 9) | Out-Null
        [GearUp.NativeMethods]::SetForegroundWindow([System.IntPtr]$window.HWND) | Out-Null
    }} catch {{}}

    if (Test-Path -LiteralPath $target -PathType Leaf) {{
        $alreadySelected = $false
        try {{
            foreach ($item in @($window.Document.SelectedItems())) {{
                if ($item.Path -and ([System.IO.Path]::GetFullPath($item.Path) -ieq $target)) {{
                    $alreadySelected = $true
                    break
                }}
            }}
        }} catch {{}}

        if (-not $alreadySelected) {{
            try {{
                $nameSpace = $shell.Namespace($folder)
                if ($nameSpace -ne $null) {{
                    $item = $nameSpace.ParseName($fileName)
                    if ($item -ne $null) {{
                        $window.Document.SelectItem($item, 29) | Out-Null
                    }}
                }}
            }} catch {{}}
        }}
    }}

    return $true
}}

return $false
""".strip()

    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) if sys.platform == "win32" else 0
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-STA", "-Command", script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            creationflags=creationflags,
        )
        return completed.returncode == 0 and completed.stdout.strip().endswith("True")
    except Exception:
        return False


class SRSApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} — {APP_SUBTITLE}")
        self.configure(bg=BG)
        self.minsize(800, 600)
        self.geometry("980x640")
        _icon_path = TOOLKIT / "assets" / "32-gearup-logo.png"
        if _icon_path.exists():
            try:
                from PIL import Image, ImageTk
                _ico = Image.open(_icon_path).resize((32, 32), Image.LANCZOS)
                self._icon_img = ImageTk.PhotoImage(_ico)
                self.iconphoto(True, self._icon_img)
            except Exception:
                pass
        self._q: queue.Queue = queue.Queue()
        self._buttons: list[tk.Button] = []
        self._desc_labels: list[tk.Label] = []
        self._busy = False
        self._canceling = False
        self._proc_holder: list = []
        self._log_scroll_visible = False
        self._line_counter = 0

        self._timer_start = 0.0
        self._timer_files_done = 0

        self._build_ui()
        self.bind("<Configure>", self._on_window_configure)
        self._poll()

    def _build_ui(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(
            "Dark.Vertical.TScrollbar",
            gripcount=0,
            background="#303030",
            darkcolor="#181818",
            lightcolor="#181818",
            troughcolor="#0f0f0f",
            bordercolor="#0f0f0f",
            arrowcolor="#7a7a7a",
        )
        style.map(
            "Dark.Vertical.TScrollbar",
            background=[("active", ACCENT), ("pressed", ACCENT)],
        )

        hdr = tk.Frame(self, bg=HDR_BG, pady=8)
        hdr.pack(fill="x")

        # Load logo
        self._logo_img = None
        _logo_path = TOOLKIT / "assets" / "gearup-logo.png"
        if _logo_path.exists():
            try:
                from PIL import Image, ImageTk
                _img = Image.open(_logo_path)
                _h = 36
                _w = int(_img.width * _h / _img.height)
                _img = _img.resize((_w, _h), Image.LANCZOS)
                self._logo_img = ImageTk.PhotoImage(_img)
            except Exception:
                try:
                    self._logo_img = tk.PhotoImage(file=str(_logo_path))
                except Exception:
                    pass

        hdr_inner = tk.Frame(hdr, bg=HDR_BG)
        hdr_inner.pack(side="left", padx=10)
        if self._logo_img:
            tk.Label(hdr_inner, image=self._logo_img, bg=HDR_BG).pack(side="left", padx=(0, 4))
        
        _title_wrap = tk.Frame(hdr_inner, bg=HDR_BG)
        _title_wrap.pack(side="left", fill="y", pady=(2, 0))

        _title_top = tk.Frame(_title_wrap, bg=HDR_BG)
        _title_top.pack(side="top", anchor="w")

        tk.Label(
            _title_top,
            text="GearUp",
            bg=HDR_BG, fg="#d6d6d6",
            font=(THEME_FONT, 14, "bold"),
        ).pack(side="left", anchor="s")
        tk.Label(
            _title_top,
            text="by Knijz",
            bg=HDR_BG, fg=FG_DIM,
            font=(THEME_FONT, 9, "italic"),
        ).pack(side="left", anchor="s", padx=(4, 0), pady=(0, 3))

        tk.Label(
            _title_wrap,
            text="— Modding ToolKit",
            bg=HDR_BG, fg=FG_DIM,
            font=(THEME_FONT, 8, "bold"),
        ).pack(side="top", anchor="w", padx=(1, 0))

        self._ind_animating = False

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=10, pady=10)

        # Left action panel with auto-scroll
        left = tk.Frame(body, bg=PANEL_BG, width=284, highlightthickness=1, highlightcolor="#222222", highlightbackground="#222222")
        left.pack(side="left", fill="y", padx=(0, 10))
        left.pack_propagate(False)

        left_scroll_wrap = tk.Frame(left, bg=PANEL_BG)
        left_scroll_wrap.pack(fill="both", expand=True, padx=10, pady=10)
        left_scroll_wrap.grid_rowconfigure(0, weight=1)
        left_scroll_wrap.grid_columnconfigure(0, weight=1)
        left_scroll_wrap.grid_columnconfigure(1, weight=0)

        self._left_vsb = ttk.Scrollbar(left_scroll_wrap, orient="vertical", style="Dark.Vertical.TScrollbar")
        self._left_scroll_visible = False

        self._left_canvas = tk.Canvas(
            left_scroll_wrap, bg=PANEL_BG,
            highlightthickness=0, bd=0,
            yscrollcommand=self._on_left_yscroll,
        )
        self._left_canvas.grid(row=0, column=0, sticky="nsew")
        self._left_vsb.config(command=self._left_canvas.yview)

        self.actions_inner = tk.Frame(self._left_canvas, bg=PANEL_BG)
        self._left_canvas_win = self._left_canvas.create_window(
            (0, 0), window=self.actions_inner, anchor="nw"
        )

        def _on_actions_configure(e):
            self._left_canvas.configure(scrollregion=self._left_canvas.bbox("all"))

        def _on_left_canvas_resize(e):
            self._left_canvas.itemconfig(self._left_canvas_win, width=e.width)

        self.actions_inner.bind("<Configure>", _on_actions_configure)
        self._left_canvas.bind("<Configure>", _on_left_canvas_resize)

        def _on_left_scroll(e):
            if self.actions_inner.winfo_reqheight() > self._left_canvas.winfo_height():
                self._left_canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")

        self._left_canvas.bind("<MouseWheel>", _on_left_scroll)
        self.actions_inner.bind("<MouseWheel>", _on_left_scroll)
        
        top_space = tk.Frame(self.actions_inner, bg=PANEL_BG, height=0)
        top_space.pack(fill="x")
        top_space.bind("<MouseWheel>", _on_left_scroll)

        self._launch_btn = self._btn(
            self.actions_inner,
            icon="🎮",
            label="Launch Game",
            desc="Street Racing Syndicate",
            cmd=self._do_launch_game,
            confirm=False,
        )

        self._btn(
            self.actions_inner,
            icon="📦",
            label="Extract",
            desc="archive.ar",
            cmd=self._do_extract,
        )

        self._section(self.actions_inner, "Convert")
        self._split_btn(
            self.actions_inner,
            icon="🧊",
            label="Models",
            desc=".ARC → .glb",
            options=[
                ("All", self._do_convert_all, True),
                ("Pick...", self._do_convert_pick, False),
            ]
        )

        self._split_btn(
            self.actions_inner,
            icon="🎨",
            label="Textures",
            desc=".ARC → .dds",
            options=[
                ("All", self._do_convert_tex_all, True),
                ("Pick...", self._do_convert_tex_pick, False),
            ]
        )

        self._split_btn(
            self.actions_inner,
            icon="🎵",
            label="Sounds",
            desc=".HDR → .wav/.ogg",
            options=[
                ("All", self._do_convert_sounds_all, True),
                ("Pick...", self._do_convert_sounds_pick, False),
            ]
        )

        self._split_btn(
            self.actions_inner,
            icon="📄",
            label="Texts",
            desc=".LDA → .txt",
            options=[
                ("All", self._do_convert_texts_all, True),
                ("Pick...", self._do_convert_texts_pick, False),
            ]
        )

        self._section(self.actions_inner, "Build")

        self._split_btn(
            self.actions_inner,
            icon="🧊",
            label="Models",
            desc=".glb",
            options=[
                ("All", self._do_build_glb_all, True),
                ("Pick...", self._do_build_glb_pick, False),
            ]
        )

        self._split_btn(
            self.actions_inner,
            icon="🎨",
            label="Textures",
            desc=".dds",
            options=[
                ("All", self._do_build_tex_all, True),
                ("Pick...", self._do_build_tex_pick, False),
            ]
        )

        self._split_btn(
            self.actions_inner,
            icon="🎵",
            label="Sounds",
            desc=".wav/.ogg",
            options=[
                ("All", self._do_build_sounds_all, True),
                ("Pick...", self._do_build_sounds_pick, False),
            ]
        )

        self._split_btn(
            self.actions_inner,
            icon="📄",
            label="Texts",
            desc=".txt",
            options=[
                ("All", self._do_build_texts_all, True),
                ("Pick...", self._do_build_texts_pick, False),
            ]
        )

        space = tk.Frame(self.actions_inner, bg=PANEL_BG, height=10)
        space.pack(fill="x")
        space.bind("<MouseWheel>", lambda e: self._left_canvas.yview_scroll(int(-1*(e.delta/120)),"units") if self.actions_inner.winfo_reqheight() > self._left_canvas.winfo_height() else None)

        self._game_stop_mini = tk.Frame(self.actions_inner, bg="#2a1a1a", cursor="hand2")
        _g_stop_lbl = tk.Label(
            self._game_stop_mini, text="⏹  End task",
            bg="#2a1a1a", fg="#ff5252",
            font=(THEME_FONT, 8, "bold"),
            anchor="center",
        )
        _g_stop_lbl.pack(pady=3)
        def _g_stop_mousedown(e):
            self._game_stop_mini.config(bg="#200d0d")
            _g_stop_lbl.config(bg="#200d0d")

        def _g_stop_click(e):
            self._game_stop_mini.config(bg="#3d1a1a")
            _g_stop_lbl.config(bg="#3d1a1a")
            if e.x < 0 or e.y < 0 or e.x > e.widget.winfo_width() or e.y > e.widget.winfo_height():
                return "break"
            self._do_stop_game()

        for _w in (self._game_stop_mini, _g_stop_lbl):
            _w.bind("<Button-1>", _g_stop_mousedown)
            _w.bind("<ButtonRelease-1>", _g_stop_click)
            _w.bind("<Enter>",    lambda e: self._game_stop_mini.config(bg="#3d1a1a") or _g_stop_lbl.config(bg="#3d1a1a"))
            _w.bind("<Leave>",    lambda e: self._game_stop_mini.config(bg="#2a1a1a") or _g_stop_lbl.config(bg="#2a1a1a"))
            _w.bind("<MouseWheel>", lambda e: self._left_canvas.yview_scroll(int(-1*(e.delta/120)),"units") if self.actions_inner.winfo_reqheight() > self._left_canvas.winfo_height() else None)

        self._action_controls = tk.Frame(self.actions_inner, bg=PANEL_BG)
        
        self._stop_mini = tk.Frame(self._action_controls, bg="#2a1a1a", cursor="hand2")
        self._stop_mini.pack(side="left", fill="both", expand=True)
        _stop_lbl = tk.Label(
            self._stop_mini, text="⏹  End task",
            bg="#2a1a1a", fg="#ff5252",
            font=(THEME_FONT, 8, "bold"),
            anchor="center",
        )
        _stop_lbl.pack(fill="both", expand=True, pady=2)
        
        self._pause_base_color = "#183f2a"
        self._pause_hover_color = "#24583d"
        self._pause_down_color = "#0e271a"
        
        self._pause_mini = tk.Frame(self._action_controls, bg=self._pause_base_color, cursor="hand2")
        self._pause_mini.pack(side="left", padx=(1, 0), fill="y")
        self._pause_lbl = tk.Label(
            self._pause_mini, text="⏸",
            bg=self._pause_base_color, fg="#4ceb8b",
            font=("Segoe UI", 9),
            anchor="center",
        )
        self._pause_lbl.pack(fill="both", expand=True, padx=12, pady=2)
        self._is_paused = False

        def _stop_enter(e):
            is_b1_down = (getattr(e, 'state', 0) & 0x0100) or getattr(self._stop_mini, '_b1_pressed', False)
            c = "#200d0d" if is_b1_down else "#3d1a1a"
            self._stop_mini.config(bg=c)
            _stop_lbl.config(bg=c)

        def _stop_leave(e):
            x = self._stop_mini.winfo_pointerx() - self._stop_mini.winfo_rootx()
            y = self._stop_mini.winfo_pointery() - self._stop_mini.winfo_rooty()
            if 0 <= x < self._stop_mini.winfo_width() and 0 <= y < self._stop_mini.winfo_height():
                return
            self._stop_mini.config(bg="#2a1a1a")
            _stop_lbl.config(bg="#2a1a1a")

        def _stop_mousedown(e):
            self._stop_mini._b1_pressed = True
            self._stop_mini.config(bg="#200d0d")
            _stop_lbl.config(bg="#200d0d")

        def _stop_b1_motion(e):
            x = self._stop_mini.winfo_pointerx() - self._stop_mini.winfo_rootx()
            y = self._stop_mini.winfo_pointery() - self._stop_mini.winfo_rooty()
            if 0 <= x < self._stop_mini.winfo_width() and 0 <= y < self._stop_mini.winfo_height():
                self._stop_mini.config(bg="#200d0d")
                _stop_lbl.config(bg="#200d0d")
            else:
                self._stop_mini.config(bg="#2a1a1a")
                _stop_lbl.config(bg="#2a1a1a")

        def _stop_click(e):
            self._stop_mini._b1_pressed = False
            x = self._stop_mini.winfo_pointerx() - self._stop_mini.winfo_rootx()
            y = self._stop_mini.winfo_pointery() - self._stop_mini.winfo_rooty()
            if 0 <= x < self._stop_mini.winfo_width() and 0 <= y < self._stop_mini.winfo_height():
                self._stop_mini.config(bg="#3d1a1a")
                _stop_lbl.config(bg="#3d1a1a")
                self._do_stop()
            else:
                self._stop_mini.config(bg="#2a1a1a")
                _stop_lbl.config(bg="#2a1a1a")
            return "break"

        def _pause_enter(e):
            is_b1_down = (getattr(e, 'state', 0) & 0x0100) or getattr(self._pause_mini, '_b1_pressed', False)
            c = self._pause_down_color if is_b1_down else self._pause_hover_color
            self._pause_mini.config(bg=c)
            self._pause_lbl.config(bg=c)

        def _pause_leave(e):
            x = self._pause_mini.winfo_pointerx() - self._pause_mini.winfo_rootx()
            y = self._pause_mini.winfo_pointery() - self._pause_mini.winfo_rooty()
            if 0 <= x < self._pause_mini.winfo_width() and 0 <= y < self._pause_mini.winfo_height():
                return
            self._pause_mini.config(bg=self._pause_base_color)
            self._pause_lbl.config(bg=self._pause_base_color)

        def _pause_mousedown(e):
            self._pause_mini._b1_pressed = True
            self._pause_mini.config(bg=self._pause_down_color)
            self._pause_lbl.config(bg=self._pause_down_color)

        def _pause_b1_motion(e):
            x = self._pause_mini.winfo_pointerx() - self._pause_mini.winfo_rootx()
            y = self._pause_mini.winfo_pointery() - self._pause_mini.winfo_rooty()
            if 0 <= x < self._pause_mini.winfo_width() and 0 <= y < self._pause_mini.winfo_height():
                self._pause_mini.config(bg=self._pause_down_color)
                self._pause_lbl.config(bg=self._pause_down_color)
            else:
                self._pause_mini.config(bg=self._pause_base_color)
                self._pause_lbl.config(bg=self._pause_base_color)

        def _pause_click(e):
            self._pause_mini._b1_pressed = False
            x = self._pause_mini.winfo_pointerx() - self._pause_mini.winfo_rootx()
            y = self._pause_mini.winfo_pointery() - self._pause_mini.winfo_rooty()
            if 0 <= x < self._pause_mini.winfo_width() and 0 <= y < self._pause_mini.winfo_height():
                self._pause_mini.config(bg=self._pause_hover_color)
                self._pause_lbl.config(bg=self._pause_hover_color)
                self._do_pause_resume()
            else:
                self._pause_mini.config(bg=self._pause_base_color)
                self._pause_lbl.config(bg=self._pause_base_color)
            return "break"

        def _scroll_left(e):
            if self.actions_inner.winfo_reqheight() > self._left_canvas.winfo_height():
                self._left_canvas.yview_scroll(int(-1*(e.delta/120)),"units")

        for _w in (self._stop_mini, _stop_lbl):
            _w.bind("<Enter>", _stop_enter)
            _w.bind("<Leave>", _stop_leave)
            _w.bind("<Button-1>", _stop_mousedown)
            _w.bind("<B1-Motion>", _stop_b1_motion)
            _w.bind("<ButtonRelease-1>", _stop_click)
            _w.bind("<MouseWheel>", _scroll_left)
            
        for _w in (self._pause_mini, self._pause_lbl):
            _w.bind("<Enter>", _pause_enter)
            _w.bind("<Leave>", _pause_leave)
            _w.bind("<Button-1>", _pause_mousedown)
            _w.bind("<B1-Motion>", _pause_b1_motion)
            _w.bind("<ButtonRelease-1>", _pause_click)
            _w.bind("<MouseWheel>", _scroll_left)
        self._active_btn_frame: tk.Frame | None = None

        # Right: log panel
        right = tk.Frame(body, bg=BG)
        right.pack(side="left", fill="both", expand=True)

        lbl_row = tk.Frame(right, bg="#141414")
        lbl_row.pack(fill="x", pady=(0, 4))
        
        _term_tab_frame = tk.Frame(lbl_row, bg="#1e1e1e")
        _term_tab_frame.pack(side="left", padx=(0, 2))
        _term_tab_accent = tk.Frame(_term_tab_frame, bg=ACCENT_DARK, height=2)
        _term_tab_accent.pack(side="top", fill="x")
        tk.Label(_term_tab_frame, text=">_  OUTPUT", bg="#1e1e1e", fg="#a0a0a0", font=(THEME_FONT, 9, "bold")).pack(side="left", padx=20, pady=8)
        
        _ws_btn_val = tk.Frame(lbl_row, bg="#141414", cursor="hand2")
        _ws_btn_val.pack(side="left", padx=(12, 16))
        _ws_btn_icon = tk.Label(_ws_btn_val, text="📁", bg="#141414", fg=FG_DIM, font=(THEME_FONT, 12), bd=0, padx=0, pady=0)
        _ws_btn_icon.pack(side="left", padx=0)
        _ws_btn_lbl = tk.Label(_ws_btn_val, text="Open Workspace", bg="#141414", fg=FG_DIM, font=(THEME_FONT, 9), bd=0, padx=0, pady=0)
        _ws_btn_lbl.pack(side="left", padx=(2, 0))

        def _ws_enter(e): 
            is_b1_down = (getattr(e, 'state', 0) & 0x0100) or getattr(_ws_btn_val, '_b1_pressed', False)
            if is_b1_down:
                _ws_btn_lbl.config(fg="#555555")
                _ws_btn_icon.config(fg="#555555")
            else:
                _ws_btn_lbl.config(fg=FG)
                _ws_btn_icon.config(fg=FG)
        def _ws_leave(e): 
            x = _ws_btn_val.winfo_pointerx() - _ws_btn_val.winfo_rootx()
            y = _ws_btn_val.winfo_pointery() - _ws_btn_val.winfo_rooty()
            if 0 <= x < _ws_btn_val.winfo_width() and 0 <= y < _ws_btn_val.winfo_height():
                return
            _ws_btn_lbl.config(fg=FG_DIM)
            _ws_btn_icon.config(fg=FG_DIM)
        def _ws_down(e): 
            _ws_btn_val._b1_pressed = True
            _ws_btn_lbl.config(fg="#555555")
            _ws_btn_icon.config(fg="#555555")
        def _ws_up(e):
            _ws_btn_val._b1_pressed = False
            x = _ws_btn_val.winfo_pointerx() - _ws_btn_val.winfo_rootx()
            y = _ws_btn_val.winfo_pointery() - _ws_btn_val.winfo_rooty()
            if 0 <= x < _ws_btn_val.winfo_width() and 0 <= y < _ws_btn_val.winfo_height():
                _ws_enter(e)
            else:
                _ws_leave(e)
                return "break"
            if e.x < 0 or e.y < 0 or e.x > e.widget.winfo_width() or e.y > e.widget.winfo_height():
                return "break"
            _ws_dir = ROOT / "SRS Workspace"
            _ws_dir.mkdir(parents=True, exist_ok=True)
            import os
            os.startfile(str(_ws_dir))
        def _ws_b1_motion(e):
            x = _ws_btn_val.winfo_pointerx() - _ws_btn_val.winfo_rootx()
            y = _ws_btn_val.winfo_pointery() - _ws_btn_val.winfo_rooty()
            if 0 <= x < _ws_btn_val.winfo_width() and 0 <= y < _ws_btn_val.winfo_height():
                _ws_btn_lbl.config(fg="#555555")
                _ws_btn_icon.config(fg="#555555")
            else:
                _ws_btn_lbl.config(fg=FG_DIM)
                _ws_btn_icon.config(fg=FG_DIM)

        for _w in (_ws_btn_val, _ws_btn_icon, _ws_btn_lbl):
            _w.bind("<Enter>", _ws_enter)
            _w.bind("<Leave>", _ws_leave)
            _w.bind("<Button-1>", _ws_down)
            _w.bind("<ButtonRelease-1>", _ws_up)
            _w.bind("<B1-Motion>", _ws_b1_motion)

        _clear_lbl = tk.Label(lbl_row, text="∅ Clear", bg="#141414", fg=FG_DIM, font=(THEME_FONT, 9), cursor="hand2")
        _clear_lbl.pack(side="right", padx=16)
        
        def _cl_enter(e): 
            is_b1_down = (getattr(e, 'state', 0) & 0x0100) or getattr(_clear_lbl, '_b1_pressed', False)
            _clear_lbl.config(fg="#555555" if is_b1_down else FG)
        def _cl_leave(e): 
            x = _clear_lbl.winfo_pointerx() - _clear_lbl.winfo_rootx()
            y = _clear_lbl.winfo_pointery() - _clear_lbl.winfo_rooty()
            if 0 <= x < _clear_lbl.winfo_width() and 0 <= y < _clear_lbl.winfo_height():
                return
            _clear_lbl.config(fg=FG_DIM)
        def _cl_down(e): 
            _clear_lbl._b1_pressed = True
            _clear_lbl.config(fg="#555555")
        def _cl_up(e):
            _clear_lbl._b1_pressed = False
            x = _clear_lbl.winfo_pointerx() - _clear_lbl.winfo_rootx()
            y = _clear_lbl.winfo_pointery() - _clear_lbl.winfo_rooty()
            if 0 <= x < _clear_lbl.winfo_width() and 0 <= y < _clear_lbl.winfo_height():
                _cl_enter(e)
            else:
                _cl_leave(e)
                return "break"
            if e.x < 0 or e.y < 0 or e.x > e.widget.winfo_width() or e.y > e.widget.winfo_height():
                return "break"
            self._clear_log()
        def _cl_b1_motion(e):
            x = _clear_lbl.winfo_pointerx() - _clear_lbl.winfo_rootx()
            y = _clear_lbl.winfo_pointery() - _clear_lbl.winfo_rooty()
            if 0 <= x < _clear_lbl.winfo_width() and 0 <= y < _clear_lbl.winfo_height():
                _clear_lbl.config(fg="#555555")
            else:
                _clear_lbl.config(fg=FG_DIM)

        _clear_lbl.bind("<Enter>", _cl_enter)
        _clear_lbl.bind("<Leave>", _cl_leave)
        _clear_lbl.bind("<Button-1>", _cl_down)
        _clear_lbl.bind("<ButtonRelease-1>", _cl_up)
        _clear_lbl.bind("<B1-Motion>", _cl_b1_motion)
        def _cl_up(e):
            _clear_lbl.config(fg=FG)
            if e.x < 0 or e.y < 0 or e.x > e.widget.winfo_width() or e.y > e.widget.winfo_height():
                return "break"
            self._clear_log()

        _clear_lbl.bind("<Enter>", _cl_enter)
        _clear_lbl.bind("<Leave>", _cl_leave)
        _clear_lbl.bind("<Button-1>", _cl_down)
        _clear_lbl.bind("<ButtonRelease-1>", _cl_up)

        log_wrap = tk.Frame(right, bg=BG)
        log_wrap.pack(fill="both", expand=True, pady=(4, 0))
        log_wrap.grid_rowconfigure(0, weight=1)
        log_wrap.grid_columnconfigure(0, weight=1)
        log_wrap.grid_columnconfigure(1, weight=0)

        # 1px border wrapper for the text log
        log_border = tk.Frame(log_wrap, bg="#222222")
        log_border.grid(row=0, column=0, sticky="nsew")
        log_border.grid_rowconfigure(0, weight=1)
        log_border.grid_columnconfigure(0, weight=1)

        self.log = tk.Text(
            log_border,
            bg=LOG_BG, fg="#c8c8d8",
            font=FONT_LOG,
            relief="flat", bd=0,
            state="disabled",
            wrap="word",
            insertbackground=ACCENT,
            padx=12, pady=12,
        )
        self.log.grid(row=0, column=0, sticky="nsew", padx=1, pady=1)
        self.log_scroll = ttk.Scrollbar(log_wrap, orient="vertical", command=self.log.yview, style="Dark.Vertical.TScrollbar")
        self.log.configure(yscrollcommand=self._on_log_yscroll)
        self._setup_tags()
        self._setup_log_context_menu()

        self.status_var = tk.StringVar(value="Ready.")
        self.timer_var = tk.StringVar(value="")
        
        sb = tk.Frame(self, bg="#202020")
        sb.pack(fill="x", side="bottom")
        
        tk.Label(
            sb,
            textvariable=self.status_var,
            bg="#202020", fg="#a0a0a0",
            font=(THEME_FONT, 9),
            anchor="w", padx=0, pady=8,
        ).pack(side="left", padx=(10, 8))

        tk.Label(
            sb,
            textvariable=self.timer_var,
            bg="#202020", fg="#dcdcdc",
            font=(THEME_FONT, 9, "bold"),
            anchor="w", padx=0, pady=8,
        ).pack(side="left", fill="x", expand=True)

        tk.Label(
            sb,
            text=f"© {time.localtime().tm_year} GearUp — Modding ToolKit  |  {APP_VERSION}",
            bg="#202020", fg="#7a7a7a",
            font=(THEME_FONT, 8),
            anchor="e", padx=10, pady=8,
        ).pack(side="right")
        self.after(0, self._refresh_wrapping)
        self.after(1000, self._poll_game_status)

    def _poll_game_status(self):
        def _check():
            try:
                if sys.platform == "win32":
                    out = subprocess.check_output(
                        ["tasklist", "/FI", "IMAGENAME eq SRS.EXE", "/NH"],
                        text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
                    )
                    is_running = ("SRS.EXE" in out.upper()) and not ("INFO:" in out.upper() or "INFORMA" in out.upper())
                else:
                    is_running = False
                self.after(0, self._update_launch_btn, is_running)
            except Exception:
                pass
        
        threading.Thread(target=_check, daemon=True).start()
        self.after(2000, self._poll_game_status)

    def _update_launch_btn(self, is_running: bool):
        if hasattr(self, '_launch_btn'):
            if is_running:
                self._launch_btn._disabled = True
                self._launch_btn.update_colors("#183f2a", "#183f2a", "#0e271a")
                self._launch_btn.icon_lbl.config(fg="#4ceb8b")
                self._launch_btn.text_lbl.config(text="Game is Running...", fg="#4ceb8b")
                if hasattr(self._launch_btn, 'desc_lbl') and self._launch_btn.desc_lbl:
                    self._launch_btn.desc_lbl.config(fg="#333333" if getattr(self, '_busy', False) else FG_DIM)
                self._launch_btn.pack_configure(pady=(0, 1))
                self._game_stop_mini.pack(in_=self.actions_inner, fill="x", padx=0, pady=(0, 4), after=self._launch_btn)
            else:
                self._launch_btn._disabled = False
                self._launch_btn.update_colors(BTN_DEF, BTN_HOV, "#141414")
                self._launch_btn._mousedown_color = "#141414"
                
                if getattr(self, '_busy', False) and getattr(self, '_active_btn_frame', None) != self._launch_btn:
                    self._launch_btn.icon_lbl.config(fg="#444444")
                    self._launch_btn.text_lbl.config(text="Launch Game", fg="#555555")
                else:
                    self._launch_btn.icon_lbl.config(fg=ACCENT)
                    self._launch_btn.text_lbl.config(text="Launch Game", fg=FG)
                
                self._launch_btn.pack_configure(pady=(0, 5))
                self._game_stop_mini.pack_forget()

    def _section(self, parent, title: str, sep_line: bool = True):
        f = tk.Frame(parent, bg=PANEL_BG)
        f.pack(fill="x", padx=0, pady=(16, 2))
        lbl = tk.Label(
            f, text=title.upper(),
            bg=PANEL_BG, fg=FG_DIM, font=(THEME_FONT, 9, "bold"),
        )
        lbl.pack(anchor="w", pady=(2, 2))

        def _scroll_left(e):
            if self.actions_inner.winfo_reqheight() > self._left_canvas.winfo_height():
                self._left_canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        for w in (f, lbl):
            w.bind("<MouseWheel>", _scroll_left)

        self._ind_idx = 0

    def _btn(self, parent, icon: str, label: str, desc: str, cmd, accent=True, confirm=True):
        frame = tk.Frame(parent, bg=BTN_DEF, cursor="hand2")
        frame.pack(fill="x", pady=(0, 5))

        frame._base_color = BTN_DEF
        frame._hover_color = BTN_HOV
        frame._mousedown_color = "#141414"

        def update_colors(new_base, new_hover, new_down="#141414"):
            if frame._base_color == new_base and frame._hover_color == new_hover and frame._mousedown_color == new_down:
                return
            frame._base_color = new_base
            frame._hover_color = new_hover
            frame._mousedown_color = new_down
            c = new_base
            frame.config(bg=c)
            for w in frame.winfo_children():
                w.config(bg=c)
                for ww in w.winfo_children():
                    ww.config(bg=c)

        frame.update_colors = update_colors

        top_row = tk.Frame(frame, bg=BTN_DEF)
        top_row.pack(fill="both", expand=True, padx=10, pady=(5, 10))
        
        top_row.columnconfigure(1, weight=1)

        icon_lbl = tk.Label(
            top_row, text=icon,
            bg=BTN_DEF, fg=ACCENT if accent else FG_DIM,
            font=("Segoe UI", 18)
        )
        icon_lbl.grid(row=0, column=0, rowspan=2, padx=(0, 10), pady=(0, 0), sticky="w")

        text_lbl = tk.Label(
            top_row, text=label,
            bg=BTN_DEF, fg="#d6d6d6",
            font=("Segoe UI", 10, "bold")
        )
        text_lbl.grid(row=0, column=1, sticky="w", pady=(0, 0))

        desc_label = None
        if desc:
            desc_label = tk.Label(
                top_row, text=desc,
                bg=BTN_DEF, fg=FG_DIM,
                font=(THEME_FONT, 8),
                anchor="w",
                justify="left"
            ) 
            desc_label.grid(row=1, column=1, sticky="w")
            self._desc_labels.append(desc_label)

        ind_canvas = tk.Canvas(frame, bg=BTN_DEF, height=6, width=36, highlightthickness=0)
        ind_circles = []
        for i in range(4):
            cx = i * 10 + 3
            c = ind_canvas.create_polygon(cx, 0, cx+3, 3, cx, 6, cx-3, 3, fill=ACCENT, outline="")
            ind_canvas.itemconfig(c, state="hidden")
            ind_circles.append(c)

        frame.top_row = top_row
        frame.icon_lbl = icon_lbl
        frame.text_lbl = text_lbl
        frame.desc_lbl = desc_label
        frame.ind_canvas = ind_canvas
        frame.ind_circles = ind_circles

        def _enter(e):
            if self._busy or getattr(frame, '_disabled', False): return "break"
            # We enforce mousedown color if button 1 is pressed (from within tk context, state mask 256 for B1 or frame flag)
            # When mouse enters, state usually has 256 bit flag if B1 is down
            is_b1_down = (getattr(e, 'state', 0) & 0x0100) or getattr(frame, '_b1_pressed', False)
            if is_b1_down:
                c = getattr(frame, '_mousedown_color', "#141414")
            else:
                c = frame._hover_color
            frame.config(bg=c)
            for w in frame.winfo_children():
                w.config(bg=c)
                for ww in w.winfo_children():
                    ww.config(bg=c)

        def _leave(e):
            # check if mouse is actually outside the frame
            x = frame.winfo_pointerx() - frame.winfo_rootx()
            y = frame.winfo_pointery() - frame.winfo_rooty()
            if 0 <= x < frame.winfo_width() and 0 <= y < frame.winfo_height():
                return
            if self._busy or getattr(frame, '_disabled', False): return "break"
            c = frame._base_color
            frame.config(bg=c)
            for w in frame.winfo_children():
                w.config(bg=c)
                for ww in w.winfo_children():
                    ww.config(bg=c)

        def _mousedown(e):
            if self._busy or getattr(frame, '_disabled', False): return "break"
            frame._b1_pressed = True
            c = getattr(frame, '_mousedown_color', "#141414")
            frame.config(bg=c)
            for w in frame.winfo_children():
                w.config(bg=c)
                for ww in w.winfo_children():
                    ww.config(bg=c)
            return "break"

        def _update_hover_override():
            x = frame.winfo_pointerx() - frame.winfo_rootx()
            y = frame.winfo_pointery() - frame.winfo_rooty()
            if 0 <= x < frame.winfo_width() and 0 <= y < frame.winfo_height():
                c = frame._hover_color
            else:
                c = frame._base_color
            frame.config(bg=c)
            for w in frame.winfo_children():
                w.config(bg=c)
                for ww in w.winfo_children():
                    ww.config(bg=c)

        def _click(e):
            if self._busy or getattr(frame, '_disabled', False): return "break"
            frame._b1_pressed = False
            
            # Re-evaluate hover
            _update_hover_override()

            # If the mouse was released outside the widget, abort
            x = frame.winfo_pointerx() - frame.winfo_rootx()
            y = frame.winfo_pointery() - frame.winfo_rooty()
            if not (0 <= x < frame.winfo_width() and 0 <= y < frame.winfo_height()):
                return "break"
                
            if cmd is self._clear_log:
                cmd()
                _update_hover_override()
                return "break"
            if self._busy:
                return "break"
            if confirm and not self._confirm_action(label):
                _update_hover_override()
                return "break"
                
            self._active_btn_frame = frame
            cmd()
            _update_hover_override()
            return "break"

        def _b1_motion(e):
            if self._busy or getattr(frame, '_disabled', False): return "break"
            x = frame.winfo_pointerx() - frame.winfo_rootx()
            y = frame.winfo_pointery() - frame.winfo_rooty()
            is_inside = (0 <= x < frame.winfo_width() and 0 <= y < frame.winfo_height())
            if is_inside:
                c = getattr(frame, '_mousedown_color', "#141414")
            else:
                c = frame._base_color
            frame.config(bg=c)
            for w in frame.winfo_children():
                w.config(bg=c)
                for ww in w.winfo_children():
                    ww.config(bg=c)

        def _scroll_left(e):
            if self.actions_inner.winfo_reqheight() > self._left_canvas.winfo_height():
                self._left_canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")

        def _bind_recursive(widget: tk.Widget):
            widget.bind("<Enter>", _enter)
            widget.bind("<Leave>", _leave)
            widget.bind("<Button-1>", _mousedown)
            widget.bind("<ButtonRelease-1>", _click)
            widget.bind("<B1-Motion>", _b1_motion)
            widget.bind("<MouseWheel>", _scroll_left)
            for child in widget.winfo_children():
                _bind_recursive(child)

        _bind_recursive(frame)
        frame.bind("<Configure>", lambda _e: self._refresh_wrapping(), add="+")

        self._buttons.append(frame)
        return frame

    def _split_btn(self, parent, icon: str, label: str, options: list, desc: str = ""):
        frame = tk.Frame(parent, bg=BTN_DEF)
        frame.pack(fill="x", pady=(0, 5))

        top_row = tk.Frame(frame, bg=BTN_DEF)
        top_row.pack(fill="both", expand=True, padx=10, pady=(5, 10))

        top_row.columnconfigure(1, weight=1)

        icon_lbl = tk.Label(
            top_row, text=icon,
            bg=BTN_DEF, fg=ACCENT,
            font=("Segoe UI", 18)
        )
        icon_lbl.grid(row=0, column=0, rowspan=2, padx=(0, 10), sticky="w")
        frame.icon_lbl = icon_lbl

        text_lbl = tk.Label(
            top_row, text=label,
            bg=BTN_DEF, fg="#d6d6d6",
            font=("Segoe UI", 10, "bold")
        )
        text_lbl.grid(row=0, column=1, sticky="w", pady=(0, 0))
        frame.text_lbl = text_lbl

        opts_frame = tk.Frame(top_row, bg=BTN_DEF)
        opts_frame.grid(row=0, column=2, sticky="e")

        desc_label = None
        if desc:
            desc_label = tk.Label(
                top_row, text=desc,
                bg=BTN_DEF, fg=FG_DIM,
                font=(THEME_FONT, 8),
                anchor="w",
                justify="left",
            )
            desc_label.grid(row=1, column=1, columnspan=2, sticky="w")
            self._desc_labels.append(desc_label)
        frame.desc_lbl = desc_label

        ind_canvas = tk.Canvas(frame, bg=BTN_DEF, height=6, width=36, highlightthickness=0)
        ind_circles = []
        for i in range(4):
            cx = i * 10 + 3
            c = ind_canvas.create_polygon(cx, 0, cx+3, 3, cx, 6, cx-3, 3, fill=ACCENT, outline="")
            ind_canvas.itemconfig(c, state="hidden")
            ind_circles.append(c)

        frame.top_row = top_row
        frame.ind_canvas = ind_canvas
        frame.ind_circles = ind_circles

        frame.opt_labels = []
        for i, (opt_label, cmd, confirm) in enumerate(options):
            opt_lbl = tk.Label(opts_frame, text=opt_label.capitalize(), bg=BTN_DEF, fg=FG_DIM, font=FONT_BOLD, cursor="hand2")
            if i > 0:
                opt_lbl.pack(side="left", padx=(10, 0))
            else:
                opt_lbl.pack(side="left")
            frame.opt_labels.append(opt_lbl)

            def make_events(l=opt_lbl, c=cmd, conf=confirm, lbl_text=opt_label):
                def _enter(e): 
                    if self._busy: return
                    is_b1_down = (getattr(e, 'state', 0) & 0x0100) or getattr(l, '_b1_pressed', False)
                    l.config(fg="#555555" if is_b1_down else FG)
                def _leave(e): 
                    if self._busy: return
                    # check if mouse is actually outside the frame
                    x = l.winfo_pointerx() - l.winfo_rootx()
                    y = l.winfo_pointery() - l.winfo_rooty()
                    if 0 <= x < l.winfo_width() and 0 <= y < l.winfo_height():
                        return
                    l.config(fg=FG_DIM)
                def _mousedown(e): 
                    if self._busy: return
                    l._b1_pressed = True
                    l.config(fg="#555555")
                def _update_hover_override():
                    if self._busy: return
                    x = l.winfo_pointerx() - l.winfo_rootx()
                    y = l.winfo_pointery() - l.winfo_rooty()
                    if 0 <= x < l.winfo_width() and 0 <= y < l.winfo_height():
                        l.config(fg=FG)
                    else:
                        l.config(fg=FG_DIM)

                def _click(e):
                    if self._busy: return "break"
                    l._b1_pressed = False
                    
                    _update_hover_override()
                    
                    x = l.winfo_pointerx() - l.winfo_rootx()
                    y = l.winfo_pointery() - l.winfo_rooty()
                    if not (0 <= x < l.winfo_width() and 0 <= y < l.winfo_height()):
                        return "break"
                    
                    if conf and not self._confirm_action(f"{label} -> {lbl_text}"):
                        _update_hover_override()
                        return "break"
                    
                    self._active_btn_frame = frame
                    c()
                    _update_hover_override()
                    return "break"
                def _b1_motion(e):
                    if self._busy: return
                    x = l.winfo_pointerx() - l.winfo_rootx()
                    y = l.winfo_pointery() - l.winfo_rooty()
                    if 0 <= x < l.winfo_width() and 0 <= y < l.winfo_height():
                        l.config(fg="#555555")
                    else:
                        l.config(fg=FG_DIM)
                        
                l.bind("<Enter>", _enter)
                l.bind("<Leave>", _leave)
                l.bind("<Button-1>", _mousedown)
                l.bind("<ButtonRelease-1>", _click)
                l.bind("<B1-Motion>", _b1_motion)
            make_events()

        def _scroll_left(e):
            if self.actions_inner.winfo_reqheight() > self._left_canvas.winfo_height():
                self._left_canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        def _bind_scroll(widget):
            widget.bind("<MouseWheel>", _scroll_left)
            for child in widget.winfo_children():
                _bind_scroll(child)
        _bind_scroll(frame)

        self._buttons.append(frame)
        return frame

    def _refresh_wrapping(self):
        canvas_width = self._left_canvas.winfo_width()
        if canvas_width > 10:
            wrap = max(100, canvas_width - 80)
            for label in self._desc_labels:
                label.configure(wraplength=wrap)

    def _confirm_action(self, label: str) -> bool:
        return messagebox.askyesno(
            "GearUp Confirmation",
            f"Run this action?\n\n{label}",
            parent=self,
        )

    def _on_left_yscroll(self, first: str, last: str):
        needed = not (float(first) <= 0.0 and float(last) >= 1.0)
        if needed and not self._left_scroll_visible:
            self._left_vsb.grid(row=0, column=1, sticky="ns")
            self._left_scroll_visible = True
        elif not needed and self._left_scroll_visible:
            self._left_vsb.grid_remove()
            self._left_scroll_visible = False
        self._left_vsb.set(first, last)

    def _set_log_scrollbar_visibility(self, first: str, last: str):
        start = float(first)
        end = float(last)
        visible = self._log_scroll_visible
        needed = not (start <= 0.0 and end >= 1.0)

        if needed and not visible:
            self.log_scroll.grid(row=0, column=1, sticky="ns")
            self._log_scroll_visible = True
        elif not needed and visible:
            self.log_scroll.grid_remove()
            self._log_scroll_visible = False

        self.log_scroll.set(first, last)

    def _on_log_yscroll(self, first: str, last: str):
        self._set_log_scrollbar_visibility(first, last)

    def _on_window_configure(self, event=None):
        self._refresh_wrapping()

    def _setup_tags(self):
        self.log.tag_config("head",     foreground="#4B93FF", font=FONT_LOGH)
        self.log.tag_config("launch",   foreground="#ffd166", font=FONT_LOGH)
        self.log.tag_config("ok",       foreground="#3fb950")
        self.log.tag_config("err",      foreground="#f85149")
        self.log.tag_config("skip",     foreground="#ffaa00")
        self.log.tag_config("skip_reason", foreground="#7d8c9a", font=("Consolas", 10, "italic"))
        self.log.tag_config("done_ok",  foreground="#ffffff", font=FONT_LOGH)
        self.log.tag_config("done_yellow", foreground="#e5e510", font=FONT_LOGH)
        self.log.tag_config("done_err", foreground="#f85149", font=FONT_LOGH)
        self.log.tag_config("path",     foreground="#ce93d8")
        self.log.tag_config("info",     foreground="#8888aa")
        self.log.tag_config("dim",      foreground="#555566")
        self.log.tag_config("dim_w",    foreground="#e4e4e4")
        self.log.tag_config("launch_ok",foreground="#3fb950", font=FONT_LOGH)
        
        self.log.tag_config("file_link", foreground="#e4e4e4")
        self.log.tag_config("file_link_hover", foreground=ACCENT, underline=True)
        self.log.tag_bind("file_link", "<Enter>", self._on_link_enter)
        self.log.tag_bind("file_link", "<Leave>", self._on_link_leave)
        self.log.tag_bind("file_link", "<Motion>", self._on_link_motion)
        self.log.tag_bind("file_link", "<Button-1>", self._on_file_press)
        self.log.tag_bind("file_link", "<B1-Motion>", self._on_file_drag)
        self.log.tag_bind("file_link", "<ButtonRelease-1>", self._on_file_release)

        # Guard against text selection drag when press started on a file link.
        self.log.bind("<B1-Motion>", self._on_log_drag_guard, add="+")
        self.log.bind("<ButtonRelease-1>", self._on_log_release_guard, add="+")

    def _on_link_enter(self, event):
        self.log.config(cursor="hand2")
        self._on_link_motion(event)

    def _on_link_leave(self, event):
        self.log.config(cursor="arrow")
        self.log.tag_remove("file_link_hover", "1.0", "end")

    def _on_link_motion(self, event):
        self.log.tag_remove("file_link_hover", "1.0", "end")
        index = self.log.index(f"@{event.x},{event.y}")
        if "file_link" in self.log.tag_names(index):
            ranges = self.log.tag_prevrange("file_link", f"{index}+1c")
            if ranges:
                self.log.tag_add("file_link_hover", ranges[0], ranges[1])

    def _get_file_link_range_at(self, event):
        index = self.log.index(f"@{event.x},{event.y}")
        if "file_link" not in self.log.tag_names(index):
            return None
        ranges = self.log.tag_prevrange("file_link", f"{index}+1c")
        if not ranges:
            return None
        return (str(ranges[0]), str(ranges[1]))

    def _on_file_press(self, event):
        self._pressed_file_link_range = self._get_file_link_range_at(event)
        return "break"

    def _on_file_drag(self, event):
        # Disable text selection drag behavior while dragging on clickable file names.
        return "break"

    def _on_log_drag_guard(self, event):
        if getattr(self, "_pressed_file_link_range", None):
            return "break"

    def _on_log_release_guard(self, event):
        if getattr(self, "_pressed_file_link_range", None):
            # If release happened outside link area, just cancel selection behavior.
            if not self._get_file_link_range_at(event):
                self._pressed_file_link_range = None
                return "break"

    def _on_file_release(self, event):
        index = self.log.index(f"@{event.x},{event.y}")
        released_range = self._get_file_link_range_at(event)
        pressed_range = getattr(self, "_pressed_file_link_range", None)
        self._pressed_file_link_range = None
        if not pressed_range or not released_range or pressed_range != released_range:
            return "break"

        file_name = self.log.get(pressed_range[0], pressed_range[1]).strip()
        line_text = self.log.get(f"{index} linestart", f"{index} lineend")
        line_upper = line_text.upper()
        is_err_line = ("] ERR " in line_upper) or line_upper.strip().startswith("ERR:")
        
        import subprocess

        workspace = ROOT / "SRS Workspace"

        # For any ERR line, clicking the file name should always show the data-missing popup.
        if is_err_line:
            from tkinter import messagebox
            messagebox.showinfo(
                "Data Not Found",
                "The data for this file no longer exists!\n\nThis happens because our code does not keep empty folders or files in case of extraction errors.",
                parent=self.winfo_toplevel()
            )
            return "break"

        candidates: list[Path] = []

        def _push_candidate(p: Path):
            if p and p.exists() and p not in candidates:
                candidates.append(p)

        def _push_name_matches(base: Path, file_name_only: str):
            if not base.exists() or not file_name_only:
                return
            try:
                for hit in base.rglob(file_name_only):
                    if hit.is_file():
                        _push_candidate(hit)
            except Exception:
                pass

        # Prefer direct paths written in the log (absolute or relative).
        raw = file_name.strip().strip('"').strip("'")
        if raw:
            raw_path = Path(raw)
            if raw_path.is_absolute():
                _push_candidate(raw_path)
            else:
                _push_candidate((ROOT / raw_path).resolve())
                _push_candidate((ROOT / "Data" / raw_path).resolve())
                _push_candidate((workspace / raw_path).resolve())

            # Some legacy logs can emit doubled dots in file names (e.g. name..wav).
            normalized_raw = re.sub(r"\.{2,}", ".", raw)
            if normalized_raw and normalized_raw != raw:
                norm_path = Path(normalized_raw)
                if norm_path.is_absolute():
                    _push_candidate(norm_path)
                else:
                    _push_candidate((ROOT / norm_path).resolve())
                    _push_candidate((ROOT / "Data" / norm_path).resolve())
                    _push_candidate((workspace / norm_path).resolve())

        m = re.search(r"->\s*(.+)$", line_text)
        if m:
            tail = m.group(1).strip().strip('"').strip("'")
            if tail:
                tail_existing = _extract_existing_path(tail)
                if tail_existing is not None:
                    _push_candidate(tail_existing)
                else:
                    tail_path = Path(tail)
                    if tail_path.is_absolute():
                        _push_candidate(tail_path)
                    else:
                        _push_candidate((workspace / tail_path).resolve())
                        _push_candidate((ROOT / tail_path).resolve())
                        _push_candidate((ROOT / "Data" / tail_path).resolve())

        if not candidates and file_name:
            name_existing = _extract_existing_path(file_name)
            if name_existing is not None:
                _push_candidate(name_existing)

        if not candidates:
            lm = re.search(r"you can find the file\(s\) in\s*->\s*(.+)$", line_text, flags=re.IGNORECASE)
            if lm:
                line_tail = lm.group(1).strip().strip('"').strip("'")
                full_existing = _extract_existing_path(line_tail)
                if full_existing is not None:
                    _push_candidate(full_existing)
                elif line_tail:
                    line_tail_path = Path(line_tail)
                    if line_tail_path.is_absolute():
                        _push_candidate(line_tail_path)
                    else:
                        _push_candidate((workspace / line_tail_path).resolve())
                        _push_candidate((ROOT / line_tail_path).resolve())
                        _push_candidate((ROOT / "Data" / line_tail_path).resolve())

        # Fallback to extension-based workspace mapping for legacy lines.
        if not candidates:
            p = Path(file_name)
            ext = p.suffix.lower()
            if "→ Model" in line_text:
                _push_candidate(workspace / "modeles" / p.name)
            elif "→ Texture" in line_text:
                _push_candidate(workspace / "textures")
            elif "→ Audio" in line_text:
                # Look for converted .wav or .ogg files with the same stem as the HDR source
                sounds_dir = workspace / "sounds"
                if sounds_dir.exists():
                    stem = p.stem.lower()
                    for sound_file in sounds_dir.glob(f"{stem}.*"):
                        if sound_file.suffix.lower() in (".wav", ".ogg"):
                            _push_candidate(sound_file)
                            break
                _push_candidate(sounds_dir / p.stem)  # fallback: directory
                _push_candidate(sounds_dir)
            elif ext in (".ogg", ".wav"):
                _push_candidate(workspace / "sounds" / p.name)
                _push_candidate(ROOT / "Data" / "sounds" / p.name)
                _push_name_matches(workspace / "sounds", p.name)
                _push_name_matches(ROOT / "Data" / "sounds", p.name)
                normalized_name = re.sub(r"\.{2,}", ".", p.name)
                if normalized_name != p.name:
                    _push_candidate(workspace / "sounds" / normalized_name)
                    _push_candidate(ROOT / "Data" / "sounds" / normalized_name)
                    _push_name_matches(workspace / "sounds", normalized_name)
                    _push_name_matches(ROOT / "Data" / "sounds", normalized_name)
                _push_candidate(workspace / "sounds")
                _push_candidate(ROOT / "Data" / "archive.ar")
                _push_candidate(ROOT / "Data" / "CDFILES.DAT")
                _push_candidate(ROOT / "Data")
            elif ext == ".hdr":
                # HDR lines can refer either to source files in archive.ar or to
                # converted output folders under sounds; try both contexts.
                _push_candidate(workspace / "sounds" / p.stem)
                _push_candidate(workspace / "sounds")
                _push_candidate(workspace / "archive.ar" / p.name)
                _push_candidate(ROOT / "Data" / "sounds" / p.name)
                _push_name_matches(workspace / "archive.ar", p.name)
                _push_name_matches(ROOT / "Data" / "sounds", p.name)
                _push_candidate(workspace / "archive.ar")
                _push_candidate(ROOT / "Data")
            elif ext in (".lda", ".txt"):
                _push_candidate(workspace / "texts" / f"{p.stem}.txt")
            elif ext == ".arc":
                _push_candidate(workspace / "archive.ar" / p.name)
                _push_candidate(ROOT / "Data" / p.name)
            elif ext in (".dds", ".png", ".tga"):
                _push_candidate(workspace / "textures" / p.name)
            elif ext == ".glb":
                _push_candidate(workspace / "modeles" / p.name)

        target = candidates[0] if candidates else None
        if target:
            if sys.platform == "win32":
                try:
                    if not _reveal_in_windows_explorer(target):
                        if target.is_file():
                            subprocess.Popen(["explorer", "/select,", str(target)])
                        else:
                            subprocess.Popen(["explorer", str(target)])
                except Exception:
                    pass
            else:
                try:
                    subprocess.Popen(["xdg-open", str(target if target.is_dir() else target.parent)])
                except Exception:
                    pass
        else:
            pass
        return "break"

    def _setup_log_context_menu(self):
        self._log_menu = tk.Menu(self, tearoff=0, bg="#2a2a2d", fg="#e4e4e4", activebackground="#4B93FF", activeforeground="#ffffff", bd=0, relief="solid")
        self._log_menu.add_command(label="Copy", command=self._copy_log_selection)
        
        self.log.bind("<Button-3>", self._show_log_menu)
        
    def _show_log_menu(self, event):
        try:
            self.log.get(tk.SEL_FIRST, tk.SEL_LAST)
            self._log_menu.tk_popup(event.x_root, event.y_root)
        except tk.TclError:
            pass # do not display if there is no selection

    def _copy_log_selection(self):
        try:
            selected_text = self.log.get(tk.SEL_FIRST, tk.SEL_LAST)
            self.clipboard_clear()
            self.clipboard_append(selected_text)
            self.update()  # Force update so clipboard contents are registered by the OS.
            # Also push via native Windows clipboard tool so content persists after app exit.
            if sys.platform == "win32":
                import subprocess
                subprocess.run("clip", text=True, input=selected_text, shell=True)
        except tk.TclError:
            pass

    def _tag_for(self, line: str) -> str:
        ll = line.lower()
        if line.startswith("====="):
            return "head"
        if line.startswith("—") or line.startswith("\u2014"):
            if "process paused" in ll or "process resumed" in ll or "task ended" in ll:
                return "done_yellow"
        if "you can find the file(s) in ->" in ll:
            return "path"
        if "completed!" in ll:
            return "done_ok"
        if "] ok " in ll:
            return "ok"
        if ("] err " in ll or ll.startswith("err:")):
            return "err"
        if "] skip" in ll:
            return "skip"
        return "info"

    def _append_lines(self, tagged_lines: list[tuple[str, str]], autoscroll: bool = True):
        if not tagged_lines:
            return
        self.log.configure(state="normal")
        # Use a batched Tk insert call to keep logging fast while preserving tag colors.
        args = []
        for text, tag in tagged_lines:
            if tag == "head":
                is_empty = (self.log.index("end-1c") == "1.0" and not args)
                if is_empty:
                    args.extend((text + "\n", tag))
                else:
                    args.extend(("\n" + text + "\n", tag))
            elif tag in ("ok", "err", "skip"):
                import re
                m = re.match(r"^(\[[0-9]+/[0-9]+\]\s*)(ok|err|skip)(\s+.*)$", text, flags=re.IGNORECASE)
                if m:
                    prefix = m.group(1)
                    status = m.group(2).upper()
                    rest = m.group(3)
                    
                    if "→" in rest and " via " in rest and status == "OK":
                        left, right = rest.split("→", 1)
                        file_part, via_part = left.split(" via ", 1)
                        args.extend((
                            prefix, "dim_w",
                            status, tag,
                            " ", "dim_w",
                            file_part.strip(), "file_link",
                            " via ", "done_yellow",
                            via_part.strip(), "file_link",
                            " ", "dim_w",
                            "→", tag,
                            right + "\n", "dim_w"
                        ))
                    elif "→" in rest and status == "OK":
                        parts = rest.split("→", 1)
                        args.extend((
                            prefix, "dim_w",
                            status, tag,
                            " ", "dim_w",
                            parts[0].strip(), "file_link",
                            " ", "dim_w",
                            "→", tag,
                            parts[1] + "\n", "dim_w"
                        ))
                    elif " via " in rest and status == "OK":
                        parts = rest.split(" via ", 1)
                        args.extend((
                            prefix, "dim_w",
                            status, tag,
                            " ", "dim_w",
                            parts[0].strip(), "file_link",
                            " via ", "done_yellow",
                            parts[1].strip(), "file_link",
                            "\n", "dim_w"
                        ))
                    elif " - " in rest:
                        parts = rest.split(" - ", 1)
                        args.extend((
                            prefix, "dim_w",
                            status, tag,
                            " ", "dim_w",
                            parts[0].strip(), "file_link",
                            " - " + parts[1].strip() + "\n", "skip_reason"
                        ))
                    elif "- " in rest:
                        parts = rest.split("- ", 1)
                        args.extend((
                            prefix, "dim_w",
                            status, tag,
                            " ", "dim_w",
                            parts[0].strip(), "file_link",
                            " - " + parts[1].strip() + "\n", "skip_reason"
                        ))
                    else:
                        args.extend((
                            prefix, "dim_w",
                            status, tag,
                            " ", "dim_w",
                            rest.strip(), "file_link",
                            "\n", "dim_w"
                        ))
                else:
                    args.extend((text + "\n", tag))
            elif tag == "done_ok":
                # Custom parse for "completed!" messages
                import re
                m = re.match(r"^(.*?completed!)\s*(.*)$", text, flags=re.IGNORECASE)
                if m:
                    args.extend((m.group(1) + " ", "done_yellow"))
                    rest = m.group(2)
                    # Split rest by "," to colorize the OK, err, skipped
                    parts = re.split(r'(,\s*)', rest)
                    for part in parts:
                        if part in (", ", ","):
                            args.extend((part, "dim_w"))
                        else:
                            # part looks like "[1]=OK", "[1]=skipped", "[1]=err", "[1]=Total"
                            import re as regex
                            pm = regex.match(r"^(\[[0-9]+\]=)(.*?)$", part)
                            if pm:
                                prefix, val = pm.group(1), pm.group(2)
                                args.extend((prefix, "dim_w"))
                                v_lower = val.lower()
                                if v_lower.startswith("ok"):
                                    args.extend((val, "ok"))
                                elif v_lower.startswith("err"):
                                    args.extend((val, "err"))
                                elif v_lower.startswith("skip"):
                                    if val.startswith("SKIP -"):
                                        args.extend(("SKIP", "skip"))
                                        args.extend((" - Already exists", "skip_reason"))
                                    elif val.startswith("skip -"):
                                        args.extend(("skip", "skip"))
                                        args.extend((" - Already exists", "skip_reason"))
                                    else:
                                        args.extend((val, "skip"))
                                else:
                                    args.extend((val, "dim_w"))
                            else:
                                args.extend((part, "dim_w"))
                    args.extend(("\n", "dim_w"))
                else:
                    args.extend((text + "\n", tag))
            elif tag == "path":
                m = re.search(r"^(.*?->\s*)(.+)$", text.strip())
                if m:
                    args.extend((m.group(1), "path", m.group(2), "file_link", "\n", "path"))
                else:
                    args.extend((text + "\n", tag))
            else:
                args.extend((text + "\n", tag))

        if args:
            self.log.tk.call((self.log._w, 'insert', 'end') + tuple(args))
            
        self.log.configure(state="disabled")
        self._line_counter += len(tagged_lines)
        self._trim_log_if_needed()
        if autoscroll:
            self.log.see("end")
        # Update scrollbar visibility after content changes
        first, last = self.log.yview()
        self._on_log_yscroll(first, last)

    def _trim_log_if_needed(self):
        if self._line_counter <= LOG_MAX_LINES:
            return
        self.log.configure(state="normal")
        self.log.delete("1.0", f"{max(1, self._line_counter - LOG_TRIM_TO)}.0")
        self.log.configure(state="disabled")
        self._line_counter = LOG_TRIM_TO

    def _clear_log(self):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        self._line_counter = 0

    def _poll(self):
        lines_to_append: list[tuple[str, str]] = []
        done_code: int | None = None
        processed = 0
        try:
            while processed < MAX_QUEUE_ITEMS_PER_TICK:
                kind, val = self._q.get_nowait()
                processed += 1
                if kind == "line":
                    lines_to_append.append((val, self._tag_for(val)))
                elif kind == "done":
                    done_code = val
        except queue.Empty:
            pass

        if lines_to_append:
            if not self._canceling:
                self._append_lines(lines_to_append)
                for val, tag in lines_to_append:
                    m = re.search(r"\[(\d+)/(\d+)\]", val)
                    if m:
                        done_c = int(m.group(1))
                        total_c = int(m.group(2))
                        if done_c > self._timer_files_done and total_c > 0:
                            self._timer_files_done = done_c
                            elapsed = time.time() - self._timer_start
                            if elapsed > 0 and done_c > 0:
                                rate = done_c / elapsed
                                rem = (total_c - done_c) / rate
                                hrs, rem_sec = divmod(rem, 3600)
                                mins, secs = divmod(rem_sec, 60)
                                
                                fmt = []
                                if hrs >= 1:
                                    fmt.append(f"{int(hrs)}h")
                                if mins >= 1 or hrs >= 1:
                                    fmt.append(f"{int(mins)}m")
                                fmt.append(f"{int(secs)}s")
                                
                                speed = f"{rate:.1f} f/s"
                                self.timer_var.set(f"Est. Time: {' '.join(fmt)}  ({speed})")

        if done_code is not None:
            if self._busy and not self._canceling:
                if done_code == 0:
                    self.status_var.set("✔  Completed successfully.")
                else:
                    self.status_var.set(f"✖  Error  (exit code {done_code})")
                self._set_busy(False)
                self._process_cleanup()
                
                try:
                    import ctypes, sys
                    if sys.platform == "win32":
                        hwnd = int(self.winfo_toplevel().wm_frame(), 16)
                        if ctypes.windll.user32.GetForegroundWindow() != hwnd:
                            class FLASHWINFO(ctypes.Structure):
                                _fields_ = [("cbSize", ctypes.c_uint), ("hwnd", ctypes.c_void_p), ("dwFlags", ctypes.c_uint), ("uCount", ctypes.c_uint), ("dwTimeout", ctypes.c_uint)]
                            info = FLASHWINFO()
                            info.cbSize = ctypes.sizeof(FLASHWINFO)
                            info.hwnd = hwnd
                            info.dwFlags = 2 | 12 # FLASHW_TRAY | FLASHW_TIMERNOFG
                            info.uCount = 5
                            info.dwTimeout = 0
                            ctypes.windll.user32.FlashWindowEx(ctypes.byref(info))
                except Exception:
                    pass

        self.after(POLL_INTERVAL_MS, self._poll)

    def _animate_ind(self):
        active_btn = self._active_btn_frame
        if not active_btn or not hasattr(active_btn, 'ind_circles'):
            self._ind_animating = False
            return

        if not self._ind_animating:
            for c in active_btn.ind_circles:
                active_btn.ind_canvas.itemconfig(c, state="hidden")
            if hasattr(active_btn, 'top_row') and active_btn.ind_canvas.winfo_manager():
                active_btn.ind_canvas.pack_forget()
                active_btn.top_row.pack_configure(pady=(5, 10))
            return

        if getattr(self, '_is_paused', False):
            self.after(300, self._animate_ind)
            return

        # loop right to left gradually filling all circles
        if hasattr(active_btn, 'top_row') and not active_btn.ind_canvas.winfo_manager():
            active_btn.ind_canvas.pack(before=active_btn.top_row, side="top", anchor="e", padx=(0, 12), pady=5)
            active_btn.top_row.pack_configure(pady=(0, 10))

        threshold = 4 - self._ind_idx
        for i, c in enumerate(active_btn.ind_circles):
            if i >= threshold:
                active_btn.ind_canvas.itemconfig(c, state="normal")
            else:
                active_btn.ind_canvas.itemconfig(c, state="hidden")

        self._ind_idx = (self._ind_idx + 1) % 5
        self.after(300, self._animate_ind)

    def _set_busy(self, busy: bool):
        self._busy = busy
        self.configure(cursor="watch" if busy else "")
        _opts_cursor = "no" if busy else "hand2"
        for btn in getattr(self, '_buttons', []):
            if type(btn) is tk.Frame:
                is_active = (btn == getattr(self, '_active_btn_frame', None))
                is_split = hasattr(btn, 'opt_labels')
                
                if busy and not is_active:
                    btn.config(cursor="no")
                else:
                    btn.config(cursor="" if is_split else "hand2")
                
                # Colors for state (dimming non-active buttons)
                if busy and not is_active:
                    _t_color = "#555555"
                    _i_color = "#444444"
                    _d_color = "#333333"
                else:
                    _t_color = "#d6d6d6"
                    _i_color = ACCENT
                    _d_color = FG_DIM

                if hasattr(btn, 'text_lbl'):
                    btn.text_lbl.config(fg=_t_color)
                if hasattr(btn, 'icon_lbl'):
                    btn.icon_lbl.config(fg=_i_color)
                if hasattr(btn, 'desc_lbl') and btn.desc_lbl:
                    btn.desc_lbl.config(fg=_d_color)

                if hasattr(btn, 'opt_labels'):
                    for opt_lbl in btn.opt_labels:
                        opt_lbl.config(cursor=_opts_cursor, fg="#333333" if busy else FG_DIM)
        if busy:
            self.status_var.set("⏳  Working…")
            self.timer_var.set("")
            self._timer_start = time.time()
            self._timer_files_done = 0
            
            if not self._ind_animating and self._active_btn_frame and hasattr(self._active_btn_frame, 'ind_canvas'):
                self._ind_animating = True
                self._ind_idx = 1
                self._animate_ind()
        else:
            if self._active_btn_frame is not None:
                self._active_btn_frame.pack_configure(pady=(0, 5))
            self._action_controls.pack_forget()
            self.timer_var.set("")
            
            if self._active_btn_frame and hasattr(self._active_btn_frame, 'ind_circles'):
                if hasattr(self._active_btn_frame, 'top_row') and self._active_btn_frame.ind_canvas.winfo_manager():
                    self._active_btn_frame.ind_canvas.pack_forget()
                    self._active_btn_frame.top_row.pack_configure(pady=(5, 10))
                    
            self._active_btn_frame = None
            self._ind_animating = False

    def _launch(self, args: list[str], label: str):
        if self._busy:
            return
        self._set_busy(True)
        self._proc_holder.clear()
        # Show action controls under the active action button
        if self._active_btn_frame is not None:
            self._active_btn_frame.pack_configure(pady=(0, 1))
            self._is_paused = False
            self._pause_base_color = "#183f2a"
            self._pause_hover_color = "#24583d"
            self._pause_down_color = "#0e271a"
            self._pause_mini.config(bg=self._pause_base_color)
            self._pause_lbl.config(bg=self._pause_base_color, text="⏸", fg="#4ceb8b")
            self._action_controls.pack(in_=self.actions_inner, fill="x", padx=0, pady=(0, 4),
                                  after=self._active_btn_frame)
        threading.Thread(
            target=_run_worker,
            args=(args, self._q, self._proc_holder),
            daemon=True,
        ).start()

    def _do_stop(self):
        if not self._busy:
            self._append_lines([("— Nothing is running.", "info")])
            return
        if self._proc_holder:
            proc = self._proc_holder[0]
            try:
                if sys.platform == "win32":
                    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                        capture_output=True,
                        creationflags=flags
                    )
                else:
                    proc.kill()
            except Exception:
                pass
        self._canceling = True
        
        self._cancel_action_name = "Action"
        if self._active_btn_frame and hasattr(self._active_btn_frame, 'text_lbl'):
            lbl_text = self._active_btn_frame.text_lbl.cget("text")
            if lbl_text:
                word = lbl_text.split()[0].lower()
                prefix = ""
                if word == "convert":
                    prefix = "Converting"
                elif word == "extract":
                    prefix = "Extracting"
                elif word == "build":
                    prefix = "Building"
                else:
                    prefix = word.capitalize()
                    
                if "→" in lbl_text:
                    suffix = lbl_text.split("  ")[-1].strip()
                    self._cancel_action_name = f"{prefix} {suffix}"
                else:
                    self._cancel_action_name = prefix
                
        self._set_busy(False)
        self.after(300, self._finish_stop)

    def _do_pause_resume(self):
        if not self._busy or not self._proc_holder:
            return
        
        proc = self._proc_holder[0]
        try:
            parent = psutil.Process(proc.pid)
            children = parent.children(recursive=True)

            if self._is_paused:
                for child in children:
                    try: child.resume()
                    except Exception: pass
                parent.resume()
                
                self._is_paused = False
                self._pause_base_color = "#183f2a"
                self._pause_hover_color = "#24583d"
                self._pause_down_color = "#0e271a"
                self._pause_mini.config(bg=self._pause_base_color)
                self._pause_lbl.config(bg=self._pause_base_color, text="⏸", fg="#4ceb8b")
                self._q.put(("line", "— Process Resumed."))
            else:
                for child in children:
                    try: child.suspend()
                    except Exception: pass
                parent.suspend()
                
                self._is_paused = True
                self._pause_base_color = "#2a251a"
                self._pause_hover_color = "#3a331a"
                self._pause_down_color = "#201c0d"
                self._pause_mini.config(bg=self._pause_base_color)
                self._pause_lbl.config(bg=self._pause_base_color, text="▶", fg="#ffd166")
                self._q.put(("line", "— Process Paused."))
        except Exception as e:
            self._q.put(("line", f"— Failed to pause/resume process: {e}"))

    def _finish_stop(self):
        # Drain any remaining queue items from the killed process
        while True:
            try:
                self._q.get_nowait()
            except queue.Empty:
                break
        self._canceling = False
        
        action_name = getattr(self, "_cancel_action_name", "Action")
                
        self._append_lines([(f"\u2014 {action_name} task ended by user.", "done_yellow")])
        self.status_var.set("✖  Task ended.")
        self._process_cleanup()

    def _process_cleanup(self):
        # Cleans up any leftover temp folders ensuring a clean workspace
        import shutil
        ws = ROOT / "SRS Workspace"
        allowed_dirs = {"archive.ar", "modeles", "textures", "sounds", "texts"}
        if ws.exists():
            for item in ws.iterdir():
                if item.is_dir() and item.name.lower() not in allowed_dirs:
                    try:
                        shutil.rmtree(item, ignore_errors=True)
                    except Exception:
                        pass

    def _do_stop_game(self):
        try:
            if sys.platform == "win32":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/IM", "SRS.EXE"],
                    capture_output=True,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
                )
            self._append_lines([("— Game task ended by user.", "done_yellow")])
        except Exception as exc:
            self._append_lines([(f"ERR: could not abort game: {exc}", "err")])

    def _do_launch_game(self):
        srs_exe = Path(ROOT) / "Bin" / "SRS.EXE"
        if not srs_exe.exists():
            self._append_lines([(f"ERR: SRS.EXE not found at {srs_exe}", "err")])
            return
        try:
            subprocess.Popen(
                [str(srs_exe)],
                cwd=str(srs_exe.parent),
                creationflags=getattr(subprocess, "DETACHED_PROCESS", 0x00000008),
            )
            self._append_lines([("Game launched.", "launch_ok")])
        except Exception as exc:
            self._append_lines([(f"ERR: could not launch game: {exc}", "err")])

    def _do_extract(self):
        self._launch(["extract", "archive.ar"], "Extract  archive.ar")

    def _do_convert_all(self):
        self._launch(["convert", "arc--glb"], "Convert ALL  .ARC → .glb")

    def _do_convert_pick(self):
        files = filedialog.askopenfilenames(
            title="Select .ARC files",
            initialdir=str(WS_ARC) if WS_ARC.exists() else str(ROOT),
            filetypes=[("ARC files", "*.ARC *.arc"), ("All files", "*.*")],
        )
        if not files:
            return
        names = ", ".join(Path(f).name for f in files)
        self._launch(
            ["convert", "-arc--glb", names],
            f"Convert  {len(files)} file(s)  .ARC → .glb",
        )

    def _do_convert_tex_all(self):
        self._launch(["convert", "arc--dds"], "Convert ALL  .ARC → .dds")

    def _do_convert_tex_pick(self):
        files = filedialog.askopenfilenames(
            title="Select .ARC files",
            initialdir=str(WS_ARC) if WS_ARC.exists() else str(ROOT),
            filetypes=[("ARC files", "*.ARC *.arc"), ("All files", "*.*")],
        )
        if not files:
            return
        names = ", ".join(Path(f).name for f in files)
        self._launch(
            ["convert", "-arc--dds", names],
            f"Convert  {len(files)} file(s)  .ARC → .dds",
        )

    def _do_convert_sounds_all(self):
        self._launch(["convert", "hdr--wav"], "Convert ALL  .HDR → .wav/.ogg")

    def _do_convert_sounds_pick(self):
        files = filedialog.askopenfilenames(
            title="Select Sounds",
            initialdir=str(WS_ARC) if WS_ARC.exists() else str(ROOT),
            filetypes=[("Sounds", "*.HDR *.hdr *.OGG *.ogg"), ("All files", "*.*")],
        )
        if not files:
            return
        names = ", ".join(Path(f).name for f in files)
        self._launch(
            ["convert", "-hdr--wav", names],
            f"Convert  {len(files)} file(s)  .HDR → .wav/.ogg",
        )

    def _do_convert_texts_all(self):
        self._launch(["convert", "lda--txt"], "Convert ALL  .LDA → .txt")

    def _do_convert_texts_pick(self):
        files = filedialog.askopenfilenames(
            title="Select Texts",
            initialdir=str(WS_ARC) if WS_ARC.exists() else str(ROOT),
            filetypes=[("Texts", "*.LDA *.lda"), ("All files", "*.*")],
        )
        if not files:
            return
        names = ", ".join(Path(f).name for f in files)
        self._launch(
            ["convert", "-lda--txt", names],
            f"Convert  {len(files)} file(s)  .LDA → .txt",
        )

    def _do_build_glb_all(self):
        self._launch(["build", "__all_glb__"], "Build ALL models  .glb")

    def _do_build_glb_pick(self):
        files = filedialog.askopenfilenames(
            title="Select .glb files",
            initialdir=str(WS_MOD) if WS_MOD.exists() else str(ROOT),
            filetypes=[("GLB files", "*.glb"), ("All files", "*.*")],
        )
        if not files:
            return
        names = ", ".join(Path(f).name for f in files)
        self._launch(
            ["build", names],
            f"Build  {len(files)} model(s)  .glb",
        )

    def _do_build_tex_all(self):
        self._launch(["build", "__all_dds__"], "Build ALL textures  .dds")

    def _do_build_tex_pick(self):
        ws_tex = Path(ROOT) / "SRS Workspace" / "textures"
        files = filedialog.askopenfilenames(
            title="Select .dds files",
            initialdir=str(ws_tex) if ws_tex.exists() else str(ROOT),
            filetypes=[("DDS files", "*.dds"), ("All files", "*.*")],
        )
        if not files:
            return
        names = ", ".join(Path(f).name for f in files)
        self._launch(
            ["build", names],
            f"Build  {len(files)} texture(s)  .dds",
        )

    def _do_build_sounds_all(self):
        self._launch(["build", "__all_wav__"], "Build ALL sounds  .wav/.ogg")

    def _do_build_sounds_pick(self):
        ws_snd = Path(ROOT) / "SRS Workspace" / "sounds"
        files = filedialog.askopenfilenames(
            title="Select sound files",
            initialdir=str(ws_snd) if ws_snd.exists() else str(ROOT),
            filetypes=[("All files", "*.*"), ("WAV files", "*.wav"), ("OGG files", "*.ogg")],
        )
        if not files:
            return
        names = ", ".join(Path(f).name for f in files)
        self._launch(
            ["build", names],
            f"Build  {len(files)} sound(s)  .wav/.ogg",
        )

    def _do_build_texts_all(self):
        self._launch(["build", "__all_txt__"], "Build ALL texts  .txt")

    def _do_build_texts_pick(self):
        ws_txt = Path(ROOT) / "SRS Workspace" / "texts"
        files = filedialog.askopenfilenames(
            title="Select .txt files",
            initialdir=str(ws_txt) if ws_txt.exists() else str(ROOT),
            filetypes=[("TXT files", "*.txt"), ("All files", "*.*")],
        )
        if not files:
            return
        names = ", ".join(Path(f).name for f in files)
        self._launch(
            ["build", names],
            f"Build  {len(files)} text(s)  .txt",
        )


if __name__ == "__main__":
    cli_args = sys.argv[1:]
    if cli_args:
        from srs_cli import main as srs_main
        sys.argv = [str(CLI)] + cli_args
        raise SystemExit(srs_main())

    if sys.platform == "win32":
        import ctypes
        _mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "Global\\GearUp_SRS_SingleInstance_Mutex")
        if ctypes.windll.kernel32.GetLastError() == 183:
            sys.exit(0)
    app = SRSApp()
    app.mainloop()
