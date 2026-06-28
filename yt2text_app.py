#!/usr/bin/env python3
"""
yt2text_app.py — Download YouTube video subtitles as clean text, via a modern dark-themed desktop GUI.

Install (one-time):
    python3 -m venv ~/yt2text-env
    source ~/yt2text-env/bin/activate
    pip install yt-dlp customtkinter

Run:
    source ~/yt2text-env/bin/activate
    python3 yt2text_app.py
"""

import json
import re
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

try:
    import customtkinter as ctk
except ImportError:
    print("ERROR: the 'customtkinter' package is not installed.")
    print("Install it with: pip install customtkinter")
    sys.exit(1)

from tkinter import filedialog, messagebox


# ---------- yt-dlp logic ----------

def get_video_info(url: str) -> dict:
    result = subprocess.run(
        ["yt-dlp", "--dump-json", "--no-warnings", url],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Unknown error while fetching video info.")
    return json.loads(result.stdout)


def pick_subtitle_lang(info: dict, preferred: list[str]) -> tuple[str, bool]:
    manual = info.get("subtitles", {})
    auto = info.get("automatic_captions", {})

    for lang in preferred:
        if lang in manual:
            return lang, True
    for lang in preferred:
        if lang in auto:
            return lang, False

    if manual:
        return next(iter(manual)), True
    if auto:
        return next(iter(auto)), False

    return "", False


def download_subtitle(url: str, lang: str, is_manual: bool, workdir: Path) -> Path:
    cmd = [
        "yt-dlp",
        "--skip-download",
        "--sub-format", "vtt",
        "--sub-langs", lang,
        "-o", str(workdir / "%(id)s.%(ext)s"),
        "--no-warnings",
    ]
    cmd += ["--write-subs"] if is_manual else ["--write-auto-subs"]
    cmd.append(url)

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Unknown error while downloading the subtitle.")

    vtt_files = list(workdir.glob("*.vtt"))
    if not vtt_files:
        raise RuntimeError("No .vtt file was produced after download.")
    return vtt_files[0]


def vtt_to_clean_text(vtt_path: Path) -> str:
    raw = vtt_path.read_text(encoding="utf-8", errors="ignore")
    lines_out = []
    seen = set()

    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith(("WEBVTT", "Kind:", "Language:", "NOTE")):
            continue
        if "-->" in line:
            continue
        if re.match(r"^\d+$", line):
            continue

        line = re.sub(r"<[^>]+>", "", line)
        line = re.sub(r"\{[^}]+\}", "", line)
        line = line.strip()
        if not line or line in seen:
            continue
        seen.add(line)
        lines_out.append(line)

    text = " ".join(lines_out)
    return re.sub(r"\s+", " ", text).strip()


def fetch_transcript(url: str, preferred_lang: str) -> tuple[str, str, str]:
    info = get_video_info(url)
    title = info.get("title", "unknown title")

    preferred_langs = [preferred_lang, f"{preferred_lang}-orig", "en", "hu"]
    lang, is_manual = pick_subtitle_lang(info, preferred_langs)

    if not lang:
        raise RuntimeError("No subtitles available for this video.")

    with tempfile.TemporaryDirectory() as tmp:
        vtt_path = download_subtitle(url, lang, is_manual, Path(tmp))
        text = vtt_to_clean_text(vtt_path)

    if not text:
        raise RuntimeError("The subtitle downloaded, but the extracted text is empty.")

    kind = "manual" if is_manual else "auto-generated"
    info_line = f"{lang.upper()} · {kind} subtitles · ~{len(text.split())} words"
    return title, text, info_line


# ---------- GUI ----------

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

ACCENT = "#FF3B30"          # bold red-orange accent color
ACCENT_HOVER = "#E0291F"
BG_CARD = "#1C1C1E"
BG_ROOT = "#101012"
TEXT_MUTED = "#9A9AA0"


class YT2TextApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("yt2text — YouTube → text")
        self.geometry("760x620")
        self.minsize(620, 480)
        self.configure(fg_color=BG_ROOT)

        self.video_title = ""

        self._build_header()
        self._build_input_row()
        self._build_action_row()
        self._build_status_row()
        self._build_text_area()

    # --- UI layout ---

    def _build_header(self):
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=24, pady=(24, 12))

        ctk.CTkLabel(
            header, text="yt2text",
            font=ctk.CTkFont(family="Helvetica", size=22, weight="bold"),
            text_color="white"
        ).pack(side="left")

        ctk.CTkLabel(
            header, text="  YouTube subtitles → clean text",
            font=ctk.CTkFont(size=13),
            text_color=TEXT_MUTED
        ).pack(side="left", padx=(4, 0))

    def _build_input_row(self):
        card = ctk.CTkFrame(self, fg_color=BG_CARD, corner_radius=14)
        card.pack(fill="x", padx=24, pady=(0, 12))

        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=16)

        self.url_entry = ctk.CTkEntry(
            row, placeholder_text="https://www.youtube.com/watch?v=...",
            height=40, corner_radius=10,
            font=ctk.CTkFont(size=13)
        )
        self.url_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.url_entry.bind("<Return>", lambda e: self.start_fetch())

        self.lang_menu = ctk.CTkOptionMenu(
            row, values=["en", "hu", "de", "es", "fr"],
            width=70, height=40, corner_radius=10,
            fg_color="#2C2C2E", button_color="#3A3A3C", button_hover_color="#48484A"
        )
        self.lang_menu.set("en")
        self.lang_menu.pack(side="left")

    def _build_action_row(self):
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=24, pady=(0, 8))

        self.fetch_btn = ctk.CTkButton(
            row, text="Fetch", height=38, corner_radius=10,
            fg_color=ACCENT, hover_color=ACCENT_HOVER,
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self.start_fetch
        )
        self.fetch_btn.pack(side="left")

        self.copy_btn = ctk.CTkButton(
            row, text="Copy", height=38, corner_radius=10,
            fg_color="#2C2C2E", hover_color="#3A3A3C",
            font=ctk.CTkFont(size=13),
            command=self.copy_to_clipboard
        )
        self.copy_btn.pack(side="left", padx=8)

        self.save_btn = ctk.CTkButton(
            row, text="Save .txt", height=38, corner_radius=10,
            fg_color="#2C2C2E", hover_color="#3A3A3C",
            font=ctk.CTkFont(size=13),
            command=self.save_to_file
        )
        self.save_btn.pack(side="left")

        self.spinner = ctk.CTkProgressBar(row, mode="indeterminate", width=120, height=4)
        # only packed into view while a fetch is running

    def _build_status_row(self):
        self.status_label = ctk.CTkLabel(
            self, text="Waiting for a link...",
            font=ctk.CTkFont(size=12), text_color=TEXT_MUTED,
            anchor="w"
        )
        self.status_label.pack(fill="x", padx=26, pady=(2, 10))

    def _build_text_area(self):
        self.text_box = ctk.CTkTextbox(
            self, corner_radius=14, fg_color=BG_CARD,
            font=ctk.CTkFont(size=13), wrap="word",
            border_width=0
        )
        self.text_box.pack(fill="both", expand=True, padx=24, pady=(0, 24))

    # --- behavior ---

    def set_status(self, msg: str, color: str = TEXT_MUTED):
        self.status_label.configure(text=msg, text_color=color)
        self.update_idletasks()

    def start_fetch(self):
        url = self.url_entry.get().strip()
        if not url:
            messagebox.showwarning("Missing link", "Paste a YouTube link first.")
            return

        self.fetch_btn.configure(state="disabled", text="Fetching...")
        self.text_box.delete("1.0", "end")
        self.spinner.pack(side="left", padx=(8, 0))
        self.spinner.start()
        self.set_status("Looking up and downloading subtitles...")

        thread = threading.Thread(target=self._fetch_worker, args=(url,), daemon=True)
        thread.start()

    def _fetch_worker(self, url: str):
        try:
            title, text, info_line = fetch_transcript(url, self.lang_menu.get())
            self.after(0, self._on_success, title, text, info_line)
        except Exception as e:
            self.after(0, self._on_error, str(e))

    def _on_success(self, title: str, text: str, info_line: str):
        self.video_title = title
        self.text_box.delete("1.0", "end")
        self.text_box.insert("1.0", f"{title}\n{info_line}\n{'─' * 50}\n\n{text}")
        self.set_status(f"✓ Done — {info_line}", "#34C759")
        self._reset_fetch_btn()

    def _on_error(self, error_msg: str):
        self.set_status("✗ Something went wrong — see the popup.", ACCENT)
        self._reset_fetch_btn()
        messagebox.showerror("Error", error_msg)

    def _reset_fetch_btn(self):
        self.spinner.stop()
        self.spinner.pack_forget()
        self.fetch_btn.configure(state="normal", text="Fetch")

    def copy_to_clipboard(self):
        content = self.text_box.get("1.0", "end").strip()
        if not content:
            messagebox.showinfo("Nothing to copy", "There's no content to copy yet.")
            return
        self.clipboard_clear()
        self.clipboard_append(content)
        self.set_status("Copied to clipboard.", "#34C759")

    def save_to_file(self):
        content = self.text_box.get("1.0", "end").strip()
        if not content:
            messagebox.showinfo("Nothing to save", "There's no content to save yet.")
            return
        default_name = re.sub(r"[^\w\s-]", "", self.video_title).strip().replace(" ", "_")[:60] or "transcript"
        path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            initialfile=f"{default_name}.txt",
            filetypes=[("Text file", "*.txt")]
        )
        if path:
            Path(path).write_text(content, encoding="utf-8")
            self.set_status(f"Saved: {path}", "#34C759")


def check_ytdlp_available():
    try:
        subprocess.run(["yt-dlp", "--version"], capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def main():
    if not check_ytdlp_available():
        print("ERROR: yt-dlp is not installed or not found on PATH.")
        print("Install it with: pip install yt-dlp")
        sys.exit(1)

    app = YT2TextApp()
    app.mainloop()


if __name__ == "__main__":
    main()
