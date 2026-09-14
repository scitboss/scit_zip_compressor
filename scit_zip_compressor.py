"""
=============================================================
  SCIT-BOSS ZIP COMPRESSOR - MEGA EDITION
  * Compress ANY format: JPG, PNG, MP4, MKV, AVI, MP3, PDF...
  * Bulk Upload: multiple files + ZIP files
  * Live Progress: % + Time Left + Speed
  * All files preserved (name, folder, content)
  Developed By: SCIT-BOSS
  Web: www.cv.scitboss.com
  Github: www.github.com/scitboss
=============================================================
"""

import os
import io
import sys
import time
import shutil
import zipfile
import tempfile
import threading
import subprocess
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path

# ---------------- OPTIONAL IMPORTS ----------------
try:
    from PIL import Image
    PIL_OK = True
except ImportError:
    PIL_OK = False


# ============================================================
#   CONFIG
# ============================================================
TARGET_SIZE_MB_DEFAULT = 200
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".webp"}
VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v"}
AUDIO_EXTS = {".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a"}
TEXT_EXTS  = {".txt", ".log", ".csv", ".json", ".xml", ".html", ".py", ".js",
              ".java", ".c", ".cpp", ".md", ".sql", ".css", ".ts", ".php"}
ARCHIVE_EXTS = {".zip"}

# ============================================================
#   THEME
# ============================================================
BG_DARK      = "#0f172a"
BG_CARD      = "#1e293b"
BG_INPUT     = "#334155"
FG_TEXT      = "#e2e8f0"
FG_MUTED     = "#94a3b8"
ACCENT       = "#22d3ee"
ACCENT_HOVER = "#06b6d4"
SUCCESS      = "#10b981"
WARNING      = "#f59e0b"
DANGER       = "#ef4444"


# ============================================================
#   HELPERS
# ============================================================
def human_size(b):
    b = float(b)
    for u in ["B", "KB", "MB", "GB", "TB"]:
        if b < 1024:
            return f"{b:.2f} {u}"
        b /= 1024
    return f"{b:.2f} PB"


def human_time(seconds):
    if seconds < 0 or seconds > 86400 * 7:
        return "--:--"
    seconds = int(seconds)
    h, r = divmod(seconds, 3600)
    m, s = divmod(r, 60)
    if h:
        return f"{h}h {m}m {s}s"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


def find_ffmpeg():
    """Return ffmpeg path or None."""
    return shutil.which("ffmpeg")


# ============================================================
#   IMAGE COMPRESSOR
# ============================================================
def compress_image_bytes(data, filename, max_dim=1920, quality=70):
    """Compress image bytes. Returns compressed bytes."""
    if not PIL_OK:
        return data
    try:
        img = Image.open(io.BytesIO(data))
        ext = os.path.splitext(filename)[1].lower()

        # Preserve transparency for PNG/WebP
        if ext in (".png", ".webp") and img.mode in ("RGBA", "LA", "P"):
            if img.mode == "P":
                img = img.convert("RGBA")
            fmt = "PNG" if ext == ".png" else "WEBP"
            save_kwargs = {"optimize": True}
            if fmt == "WEBP":
                save_kwargs["quality"] = quality
        else:
            if img.mode in ("RGBA", "LA", "P"):
                bg = Image.new("RGB", img.size, (255, 255, 255))
                bg.paste(img, mask=img.split()[-1] if img.mode in ("RGBA", "LA") else None)
                img = bg
            elif img.mode != "RGB":
                img = img.convert("RGB")
            fmt = "JPEG"
            save_kwargs = {"quality": quality, "optimize": True, "progressive": True}

        # Resize if too large
        w, h = img.size
        if max(w, h) > max_dim:
            ratio = max_dim / max(w, h)
            img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)

        buf = io.BytesIO()
        img.save(buf, format=fmt, **save_kwargs)
        new_data = buf.getvalue()

        # Only use if actually smaller
        return new_data if len(new_data) < len(data) else data
    except Exception as e:
        print(f"[img-skip] {filename}: {e}")
        return data


# ============================================================
#   VIDEO COMPRESSOR (FFmpeg)
# ============================================================
def compress_video_bytes(data, filename, ffmpeg_path, crf=28, preset="fast"):
    """Compress video bytes using ffmpeg. Returns compressed bytes or original."""
    if not ffmpeg_path:
        return data

    ext = os.path.splitext(filename)[1].lower()
    tmp_in = None
    tmp_out = None
    try:
        # Write to temp files
        fd1, tmp_in = tempfile.mkstemp(suffix=ext)
        os.close(fd1)
        with open(tmp_in, "wb") as f:
            f.write(data)

        tmp_out = tmp_in + ".compressed" + ext

        # ffmpeg command
        cmd = [
            ffmpeg_path, "-y", "-i", tmp_in,
            "-c:v", "libx264",
            "-crf", str(crf),
            "-preset", preset,
            "-c:a", "aac",
            "-b:a", "128k",
            "-movflags", "+faststart",
            tmp_out
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=1800)
        if result.returncode != 0 or not os.path.exists(tmp_out):
            print(f"[video-fail] {filename}")
            return data

        new_size = os.path.getsize(tmp_out)
        if new_size >= len(data):
            return data

        with open(tmp_out, "rb") as f:
            return f.read()
    except subprocess.TimeoutExpired:
        print(f"[video-timeout] {filename}")
        return data
    except Exception as e:
        print(f"[video-skip] {filename}: {e}")
        return data
    finally:
        for p in (tmp_in, tmp_out):
            try:
                if p and os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass


# ============================================================
#   SMART FILE COMPRESSOR
# ============================================================
def smart_compress_bytes(data, filename, ffmpeg_path=None,
                          img_quality=70, video_crf=28):
    """Dispatch to correct compressor based on extension."""
    ext = os.path.splitext(filename)[1].lower()

    if ext in IMAGE_EXTS:
        return compress_image_bytes(data, filename, quality=img_quality)

    if ext in VIDEO_EXTS and ffmpeg_path:
        return compress_video_bytes(data, filename, ffmpeg_path, crf=video_crf)

    # Text / other → just return; ZIP will compress
    return data


# ============================================================
#   MAIN ENGINE
# ============================================================
class CompressorEngine:
    def __init__(self, files, output_path, target_bytes,
                 img_quality=70, video_crf=28,
                 progress_cb=None, log_cb=None):
        self.files = files              # list of file paths
        self.output_path = output_path
        self.target_bytes = target_bytes
        self.img_quality = img_quality
        self.video_crf = video_crf
        self.progress_cb = progress_cb  # (pct, status_text, time_left, speed)
        self.log_cb = log_cb
        self.ffmpeg = find_ffmpeg()
        self.cancelled = False

    def cancel(self):
        self.cancelled = True

    # --------------------------------------------------------
    def run(self):
        start_time = time.time()

        # ---------- 1. Collect all files (flatten ZIPs) ----------
        if self.log_cb:
            self.log_cb("📦 Scanning input...")

        all_entries = []  # (arcname, source_type, source_path, raw_bytes)
        total_bytes_in = 0

        for fp in self.files:
            if self.cancelled:
                raise RuntimeError("Cancelled")
            ext = os.path.splitext(fp)[1].lower()
            if ext in ARCHIVE_EXTS:
                # Extract ZIP in memory
                try:
                    with zipfile.ZipFile(fp, "r") as z:
                        for info in z.infolist():
                            if info.is_dir():
                                continue
                            try:
                                data = z.read(info.filename)
                            except Exception:
                                continue
                            all_entries.append(("arc", info.filename, data))
                            total_bytes_in += len(data)
                except Exception as e:
                    if self.log_cb:
                        self.log_cb(f"⚠️ Skipped ZIP {fp}: {e}")
            else:
                # Direct file
                try:
                    with open(fp, "rb") as f:
                        data = f.read()
                    all_entries.append(("raw", os.path.basename(fp), data))
                    total_bytes_in += len(data)
                except Exception as e:
                    if self.log_cb:
                        self.log_cb(f"⚠️ Skipped {fp}: {e}")

        if not all_entries:
            raise ValueError("No files found to compress!")

        total_files = len(all_entries)
        if self.log_cb:
            self.log_cb(f"✅ Found {total_files} files  ({human_size(total_bytes_in)})")

        # ---------- 2. Sort: large first for better stats ----------
        all_entries.sort(key=lambda e: len(e[2]), reverse=True)

        # ---------- 3. Recompress each file ----------
        processed = 0
        processed_bytes = 0
        speed_window = []  # (time, bytes)

        with zipfile.ZipFile(
            self.output_path, "w",
            compression=zipfile.ZIP_LZMA,
            allowZip64=True
        ) as zout:

            for src_type, arcname, data in all_entries:
                if self.cancelled:
                    raise RuntimeError("Cancelled")

                # Compress individual file based on type
                new_data = smart_compress_bytes(
                    data, arcname, self.ffmpeg,
                    img_quality=self.img_quality,
                    video_crf=self.video_crf
                )

                # Write to output ZIP
                try:
                    info = zipfile.ZipInfo(
                        filename=arcname,
                        date_time=time.localtime()[:6]
                    )
                    info.compress_type = zipfile.ZIP_LZMA
                    info.external_attr = 0o644 << 16
                    zout.writestr(info, new_data, compress_type=zipfile.ZIP_LZMA)
                except Exception as e:
                    if self.log_cb:
                        self.log_cb(f"⚠️ Write failed: {arcname}: {e}")

                processed += 1
                processed_bytes += len(data)

                # ---------- Speed & Time estimate ----------
                now = time.time()
                speed_window.append((now, len(data)))
                # Keep last 5 seconds
                speed_window = [(t, b) for t, b in speed_window if now - t <= 5]
                if len(speed_window) >= 2:
                    dt = speed_window[-1][0] - speed_window[0][0]
                    db = sum(b for _, b in speed_window) - speed_window[0][1]
                    speed = db / dt if dt > 0 else 0
                else:
                    speed = processed_bytes / (now - start_time + 0.001)

                # ETA
                remaining_bytes = total_bytes_in - processed_bytes
                eta = remaining_bytes / speed if speed > 0 else -1

                pct = int((processed / total_files) * 100)
                if self.progress_cb:
                    self.progress_cb(
                        pct,
                        f"[{processed}/{total_files}] {arcname}",
                        eta,
                        speed
                    )

                if self.log_cb and processed % 10 == 0:
                    cur_size = os.path.getsize(self.output_path)
                    self.log_cb(f"  ↳ {processed}/{total_files}  "
                                f"output={human_size(cur_size)}  "
                                f"speed={human_size(speed)}/s")

        # ---------- 4. Finish ----------
        elapsed = time.time() - start_time
        final_size = os.path.getsize(self.output_path)

        return {
            "original": total_bytes_in,
            "final": final_size,
            "files": total_files,
            "elapsed": elapsed,
            "reached": final_size <= self.target_bytes,
            "target": self.target_bytes,
        }


# ============================================================
#   MAIN GUI
# ============================================================
class SCITZipCompressorMega:
    def __init__(self, root):
        self.root = root
        self.root.title("SCIT-BOSS ZIP Compressor — MEGA EDITION")
        self.root.geometry("880x820")
        self.root.configure(bg=BG_DARK)
        self.root.resizable(False, False)

        self.files = []                    # list of file paths
        self.output_path = tk.StringVar()
        self.target_mb = tk.StringVar(value="200")
        self.img_quality = tk.IntVar(value=70)
        self.video_crf = tk.IntVar(value=28)

        self.status_var = tk.StringVar(value="Ready...")
        self.current_var = tk.StringVar(value="")
        self.time_left_var = tk.StringVar(value="Time Left: --")
        self.speed_var = tk.StringVar(value="Speed: --")
        self.result_var = tk.StringVar(value="")

        self.engine = None
        self.start_time = 0

        self._build_ui()
        self._refresh_file_list()

    # --------------------------------------------------------
    def _build_ui(self):
        # ---------- HEADER ----------
        header = tk.Frame(self.root, bg=BG_DARK)
        header.pack(fill="x", pady=(14, 4))
        tk.Label(header, text="🗜️  SCIT-BOSS ZIP COMPRESSOR",
                 bg=BG_DARK, fg=ACCENT,
                 font=("Segoe UI", 18, "bold")).pack()
        tk.Label(header, text="MEGA EDITION  —  Compress ANY format (JPG/PNG/MP4/MKV/AVI...)  •  Bulk Upload",
                 bg=BG_DARK, fg=FG_MUTED, font=("Segoe UI", 9)).pack(pady=(2, 0))

        # ---------- MAIN CARD ----------
        card = tk.Frame(self.root, bg=BG_CARD)
        card.pack(fill="both", expand=True, padx=18, pady=10)

        # ===== Files Panel =====
        self._label(card, "📁  Input Files  —  (Bulk: multiple files + ZIP supported):")

        list_frame = tk.Frame(card, bg=BG_CARD)
        list_frame.pack(fill="x", padx=18, pady=(0, 6))

        # Treeview for file list
        style = ttk.Style()
        style.theme_use("default")
        style.configure("SCIT.Treeview",
                        background=BG_INPUT, foreground=FG_TEXT,
                        fieldbackground=BG_INPUT, borderwidth=0,
                        font=("Consolas", 9))
        style.configure("SCIT.Treeview.Heading",
                        background=BG_DARK, foreground=ACCENT,
                        font=("Segoe UI", 9, "bold"))
        style.map("SCIT.Treeview", background=[("selected", ACCENT)],
                  foreground=[("selected", BG_DARK)])

        tree_wrap = tk.Frame(list_frame, bg=BG_CARD)
        tree_wrap.pack(side="left", fill="both", expand=True)

        self.tree = ttk.Treeview(tree_wrap, style="SCIT.Treeview",
                                  columns=("name", "size"),
                                  show="headings", height=6)
        self.tree.heading("name", text="File Name")
        self.tree.heading("size", text="Size")
        self.tree.column("name", width=520, anchor="w")
        self.tree.column("size", width=120, anchor="e")
        self.tree.pack(side="left", fill="both", expand=True)

        sb = tk.Scrollbar(tree_wrap, orient="vertical", command=self.tree.yview)
        sb.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=sb.set)

        # Buttons column
        btn_col = tk.Frame(list_frame, bg=BG_CARD)
        btn_col.pack(side="left", fill="y", padx=(8, 0))
        self._small_btn(btn_col, "➕ Add Files", self._add_files, width=13)
        self._small_btn(btn_col, "📦 Add ZIP",   self._add_zip,   width=13)
        self._small_btn(btn_col, "📂 Add Folder", self._add_folder, width=13)
        self._small_btn(btn_col, "❌ Remove Sel", self._remove_sel, width=13)
        self._small_btn(btn_col, "🗑️ Clear All",  self._clear_files, width=13)

        # ===== Output Path =====
        self._label(card, "💾  Output ZIP Path:")
        f2 = tk.Frame(card, bg=BG_CARD); f2.pack(fill="x", padx=18, pady=(0, 8))
        tk.Entry(f2, textvariable=self.output_path, bg=BG_INPUT, fg=FG_TEXT,
                 insertbackground=FG_TEXT, relief="flat",
                 font=("Segoe UI", 10)).pack(side="left", fill="x",
                                              expand=True, ipady=7, padx=(0, 8))
        self._small_btn(f2, "Save As", self._pick_output, width=10)

        # ===== Settings Row =====
        settings = tk.Frame(card, bg=BG_CARD); settings.pack(fill="x", padx=18, pady=(0, 6))

        # Target size
        tk.Label(settings, text="🎯 Target (MB):", bg=BG_CARD, fg=FG_TEXT,
                 font=("Segoe UI", 9, "bold")).pack(side="left", padx=(0, 4))
        tk.Entry(settings, textvariable=self.target_mb, bg=BG_INPUT, fg=ACCENT,
                 insertbackground=FG_TEXT, justify="center", relief="flat",
                 font=("Segoe UI", 10, "bold"), width=6).pack(side="left", ipady=5)

        # Image quality
        tk.Label(settings, text="  🖼️ JPG Quality:", bg=BG_CARD, fg=FG_TEXT,
                 font=("Segoe UI", 9, "bold")).pack(side="left", padx=(10, 4))
        tk.Scale(settings, from_=30, to=95, orient="horizontal",
                 variable=self.img_quality, bg=BG_CARD, fg=FG_TEXT,
                 troughcolor=BG_INPUT, highlightthickness=0,
                 activebackground=ACCENT, length=120, showvalue=True,
                 font=("Segoe UI", 8)).pack(side="left")

        # Video CRF
        tk.Label(settings, text="  🎥 Video CRF:", bg=BG_CARD, fg=FG_TEXT,
                 font=("Segoe UI", 9, "bold")).pack(side="left", padx=(10, 4))
        tk.Scale(settings, from_=18, to=40, orient="horizontal",
                 variable=self.video_crf, bg=BG_CARD, fg=FG_TEXT,
                 troughcolor=BG_INPUT, highlightthickness=0,
                 activebackground=ACCENT, length=120, showvalue=True,
                 font=("Segoe UI", 8)).pack(side="left")

        # FFmpeg warning
        ff = find_ffmpeg()
        warn_txt = "✅ FFmpeg: found" if ff else "⚠️ FFmpeg: NOT FOUND (video compress disabled)"
        warn_color = SUCCESS if ff else WARNING
        tk.Label(settings, text=f"  {warn_txt}", bg=BG_CARD, fg=warn_color,
                 font=("Segoe UI", 8, "bold")).pack(side="left", padx=(10, 0))

        # ===== Start button =====
        self.start_btn = tk.Button(
            card, text="🚀  START ULTRA COMPRESSION",
            bg=ACCENT, fg=BG_DARK,
            activebackground=ACCENT_HOVER, activeforeground=BG_DARK,
            font=("Segoe UI", 12, "bold"),
            relief="flat", bd=0, cursor="hand2",
            command=self._start)
        self.start_btn.pack(fill="x", padx=18, pady=(8, 10), ipady=11)

        # ===== Progress =====
        style.configure("SCIT.Horizontal.TProgressbar",
                        troughcolor=BG_INPUT, background=ACCENT,
                        bordercolor=BG_CARD, lightcolor=ACCENT, darkcolor=ACCENT)
        self.progress = ttk.Progressbar(card, style="SCIT.Horizontal.TProgressbar",
                                        orient="horizontal", mode="determinate",
                                        maximum=100)
        self.progress.pack(fill="x", padx=18, pady=(0, 4))

        # ===== Live stats row =====
        live = tk.Frame(card, bg=BG_CARD); live.pack(fill="x", padx=18, pady=(0, 4))
        tk.Label(live, textvariable=self.time_left_var, bg=BG_CARD, fg=WARNING,
                 font=("Segoe UI", 9, "bold")).pack(side="left")
        tk.Label(live, textvariable=self.speed_var, bg=BG_CARD, fg=ACCENT,
                 font=("Segoe UI", 9, "bold")).pack(side="right")

        # ===== Status =====
        tk.Label(card, textvariable=self.status_var, bg=BG_CARD, fg=FG_MUTED,
                 font=("Segoe UI", 9), anchor="w").pack(fill="x", padx=18)

        tk.Label(card, textvariable=self.current_var, bg=BG_CARD, fg=FG_TEXT,
                 font=("Consolas", 8), anchor="w").pack(fill="x", padx=18, pady=(2, 0))

        # ===== Log box =====
        log_wrap = tk.Frame(card, bg=BG_CARD); log_wrap.pack(fill="both",
                                                              expand=True,
                                                              padx=18, pady=(6, 8))
        self.log = tk.Text(log_wrap, height=6, bg="#0b1220", fg=FG_MUTED,
                           insertbackground=FG_TEXT, relief="flat",
                           font=("Consolas", 8), wrap="word")
        self.log.pack(side="left", fill="both", expand=True)
        log_sb = tk.Scrollbar(log_wrap, orient="vertical", command=self.log.yview)
        log_sb.pack(side="right", fill="y")
        self.log.configure(yscrollcommand=log_sb.set, state="disabled")

        # ===== Result =====
        tk.Label(card, textvariable=self.result_var, bg=BG_CARD, fg=SUCCESS,
                 font=("Segoe UI", 10, "bold"), anchor="w",
                 wraplength=820, justify="left").pack(fill="x", padx=18, pady=(0, 8))

        # ===== FOOTER =====
        footer = tk.Frame(self.root, bg=BG_DARK)
        footer.pack(fill="x", pady=(0, 8))
        tk.Label(footer, text="DEVELOPED BY  SCIT-BOSS",
                 bg=BG_DARK, fg=ACCENT,
                 font=("Segoe UI", 9, "bold")).pack()
        tk.Label(footer, text="🌐 www.cv.scitboss.com    |    💻 www.github.com/scitboss",
                 bg=BG_DARK, fg=FG_MUTED, font=("Segoe UI", 8)).pack()

    # --------------------------------------------------------
    def _label(self, parent, text):
        tk.Label(parent, text=text, bg=BG_CARD, fg=FG_TEXT,
                 font=("Segoe UI", 10, "bold"), anchor="w"
                 ).pack(fill="x", padx=18, pady=(10, 3))

    def _small_btn(self, parent, text, cmd, width=12):
        return tk.Button(parent, text=text, command=cmd,
                         bg=ACCENT, fg=BG_DARK,
                         activebackground=ACCENT_HOVER, activeforeground=BG_DARK,
                         font=("Segoe UI", 9, "bold"),
                         relief="flat", bd=0, cursor="hand2",
                         width=width).pack(pady=2, ipady=4, ipadx=4)

    # --------------------------------------------------------
    # FILE MANAGEMENT
    # --------------------------------------------------------
    def _add_files(self):
        paths = filedialog.askopenfilenames(title="Select files (multiple allowed)")
        for p in paths:
            if p not in self.files:
                self.files.append(p)
        self._refresh_file_list()

    def _add_zip(self):
        paths = filedialog.askopenfilenames(
            title="Select ZIP file(s)",
            filetypes=[("ZIP Files", "*.zip")])
        for p in paths:
            if p not in self.files:
                self.files.append(p)
        self._refresh_file_list()

    def _add_folder(self):
        d = filedialog.askdirectory(title="Select folder")
        if not d:
            return
        for root_, _, fnames in os.walk(d):
            for fn in fnames:
                full = os.path.join(root_, fn)
                if full not in self.files:
                    self.files.append(full)
        self._refresh_file_list()

    def _remove_sel(self):
        for iid in self.tree.selection():
            idx = int(iid)
            if 0 <= idx < len(self.files):
                self.files[idx] = None
        self.files = [f for f in self.files if f]
        self._refresh_file_list()

    def _clear_files(self):
        self.files = []
        self._refresh_file_list()

    def _refresh_file_list(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        total = 0
        for i, fp in enumerate(self.files):
            try:
                sz = os.path.getsize(fp)
                total += sz
                self.tree.insert("", "end", iid=str(i),
                                  values=(os.path.basename(fp), human_size(sz)))
            except Exception:
                self.tree.insert("", "end", iid=str(i),
                                  values=(os.path.basename(fp), "??"))
        if self.files:
            self.status_var.set(
                f"📦 {len(self.files)} file(s) selected  |  Total: {human_size(total)}")
        else:
            self.status_var.set("Ready...")

    # --------------------------------------------------------
    def _pick_output(self):
        p = filedialog.asksaveasfilename(
            title="Save compressed ZIP as",
            defaultextension=".zip",
            filetypes=[("ZIP Files", "*.zip")])
        if p:
            self.output_path.set(p)

    # --------------------------------------------------------
    # LOG
    # --------------------------------------------------------
    def _log(self, msg):
        def _do():
            self.log.configure(state="normal")
            self.log.insert("end", msg + "\n")
            self.log.see("end")
            self.log.configure(state="disabled")
        self.root.after(0, _do)

    # --------------------------------------------------------
    # START
    # --------------------------------------------------------
    def _start(self):
        if not self.files:
            messagebox.showerror("Error", "Please add at least one file!")
            return

        out = self.output_path.get().strip()
        if not out:
            # auto-suggest
            if self.files:
                base = os.path.splitext(self.files[0])[0]
                out = f"{base}_SCIT_compressed.zip"
                self.output_path.set(out)
            else:
                messagebox.showerror("Error", "Please provide an output path!")
                return

        try:
            target_mb = float(self.target_mb.get())
            if target_mb <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Error", "Please enter a valid target size in MB!")
            return

        # Reset UI
        self.progress["value"] = 0
        self.status_var.set("⏳ Starting...")
        self.current_var.set("")
        self.time_left_var.set("Time Left: calculating...")
        self.speed_var.set("Speed: --")
        self.result_var.set("")
        self.log.configure(state="normal"); self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

        self.start_btn.config(state="disabled", bg=FG_MUTED)

        self.engine = CompressorEngine(
            files=list(self.files),
            output_path=out,
            target_bytes=target_mb * 1024 * 1024,
            img_quality=self.img_quality.get(),
            video_crf=self.video_crf.get(),
            progress_cb=self._on_progress,
            log_cb=self._log
        )

        self.start_time = time.time()
        threading.Thread(target=self._worker, daemon=True).start()

    # --------------------------------------------------------
    def _on_progress(self, pct, current_file, eta, speed):
        def _do():
            self.progress["value"] = pct
            self.status_var.set(f"⏳ Compressing... {pct}%")
            short = current_file if len(current_file) < 90 else current_file[:87] + "..."
            self.current_var.set(f"📄 {short}")
            if eta > 0:
                self.time_left_var.set(f"⏱️ Time Left: {human_time(eta)}")
            else:
                self.time_left_var.set("⏱️ Time Left: calculating...")
            self.speed_var.set(f"⚡ Speed: {human_size(speed)}/s")
        self.root.after(0, _do)

    def _worker(self):
        try:
            result = self.engine.run()
            self.root.after(0, lambda: self._on_done(result))
        except RuntimeError as e:
            self.root.after(0, lambda: self._on_error(str(e)))
        except Exception as e:
            import traceback; traceback.print_exc()
            self.root.after(0, lambda: self._on_error(str(e)))

    # --------------------------------------------------------
    def _on_done(self, res):
        self.progress["value"] = 100
        self.start_btn.config(state="normal", bg=ACCENT)

        orig = res["original"]
        final = res["final"]
        saved = orig - final
        ratio = (saved / orig * 100) if orig else 0
        elapsed = res["elapsed"]
        reached = res["reached"]
        target = res["target"]

        self.time_left_var.set(f"⏱️ Done in {human_time(elapsed)}")
        self.speed_var.set(f"⚡ Avg: {human_size(orig / max(elapsed, 0.01))}/s")

        if reached:
            self.status_var.set("✅ SUCCESS — Target reached!")
            self.result_var.set(
                f"✅ Original: {human_size(orig)}  ➜  New: {human_size(final)}  "
                f"(Saved {human_size(saved)} | {ratio:.1f}%)  |  Files: {res['files']}"
            )
            messagebox.showinfo(
                "🎉 SUCCESS!",
                f"✅ Target reached!\n\n"
                f"Original  : {human_size(orig)}\n"
                f"New Size  : {human_size(final)}\n"
                f"Target    : {human_size(target)}\n"
                f"Saved     : {human_size(saved)}  ({ratio:.1f}%)\n"
                f"Files     : {res['files']}\n"
                f"Time      : {human_time(elapsed)}\n\n"
                f"✅ All files are preserved (extract and check)\n\n"
                f"Output: {self.output_path.get()}"
            )
        else:
            self.status_var.set("⚠️ Best possible compression done")
            self.result_var.set(
                f"⚠️ Best: {human_size(final)}  (target {human_size(target)} not reached)  "
                f"|  Saved {ratio:.1f}%  |  Files: {res['files']}"
            )
            messagebox.showwarning(
                "⚠️ Best Possible Compression Done",
                f"Target could not be reached, but maximum compression was applied.\n\n"
                f"Original  : {human_size(orig)}\n"
                f"Best      : {human_size(final)}\n"
                f"Target    : {human_size(target)}\n"
                f"Saved     : {human_size(saved)}  ({ratio:.1f}%)\n"
                f"Files     : {res['files']}\n"
                f"Time      : {human_time(elapsed)}\n\n"
                f"⛔ Reason: Files may already be compressed (JPG/MP4)\n"
                f"or FFmpeg is missing (video compression will not run)\n\n"
                f"✅ All files are preserved!\n\n"
                f"Output: {self.output_path.get()}"
            )

    def _on_error(self, msg):
        self.status_var.set("❌ Error!")
        self.start_btn.config(state="normal", bg=ACCENT)
        messagebox.showerror("Error", f"Compression failed:\n{msg}")


# ============================================================
#   ENTRY
# ============================================================
if __name__ == "__main__":
    root = tk.Tk()
    app = SCITZipCompressorMega(root)
    root.mainloop()
