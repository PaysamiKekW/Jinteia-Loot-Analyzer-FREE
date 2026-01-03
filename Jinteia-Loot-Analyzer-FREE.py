#!/usr/bin/env python3
import datetime as dt
import os
import re
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Optional, Iterable, List, Deque, Dict, Tuple

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

# ---------------------------------------------------------------------------
# Parsing and data structures
# ---------------------------------------------------------------------------

LOG_LINE_RE = re.compile(
    r"\[(\d{2}/\d{2}/\d{2})\] \[(\d{2}:\d{2}:\d{2})\]: You receive (\d+) (.+?)\."
)


@dataclass
class LootEvent:
    ts: dt.datetime
    quantity: int
    item: str

    @property
    def is_yang(self) -> bool:
        return self.item == "Yang"


def parse_datetime_from_log(date_str: str, time_str: str) -> dt.datetime:
    """Parse date/time from the log format: 24/11/25 00:29:29."""
    return dt.datetime.strptime(f"{date_str} {time_str}", "%d/%m/%y %H:%M:%S")


def parse_log_line(line: str) -> Optional[LootEvent]:
    """Parse a single log line into a LootEvent, or return None if it does not match."""
    m = LOG_LINE_RE.search(line)
    if not m:
        return None
    date_str, time_str, qty_str, item = m.groups()
    ts = parse_datetime_from_log(date_str, time_str)
    quantity = int(qty_str)
    return LootEvent(ts=ts, quantity=quantity, item=item)


def iter_events_from_file(path: str) -> Iterable[LootEvent]:
    """Iterate over all events in the given log file."""
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            ev = parse_log_line(line)
            if ev:
                yield ev


def stats_from_events(events: Iterable[LootEvent]) -> Dict:
    """Compute statistics from a list/iterable of events."""
    total_yang = 0
    items_qty = defaultdict(int)      # item -> total quantity
    events_list: List[LootEvent] = []

    for ev in events:
        events_list.append(ev)
        if ev.is_yang:
            total_yang += ev.quantity
        else:
            items_qty[ev.item] += ev.quantity

    if not events_list:
        return {
            "total_yang": 0,
            "items_qty": {},
            "hours": 0.0,
        }

    start = events_list[0].ts
    end = events_list[-1].ts
    elapsed_seconds = max((end - start).total_seconds(), 1)
    hours = elapsed_seconds / 3600.0

    return {
        "total_yang": total_yang,
        "items_qty": dict(items_qty),
        "hours": hours,
        "start": start,
        "end": end,
    }


# ---------------------------------------------------------------------------
# Live monitor worker (background thread)
# ---------------------------------------------------------------------------

class LiveMonitorWorker(threading.Thread):
    """
    Background thread that tails the log file and maintains a sliding window
    of the last N minutes. It periodically calls update_callback(stats_dict).
    """

    def __init__(
        self,
        path: str,
        window_minutes: int,
        refresh_secs: int,
        from_start: bool,
        update_callback,
        stop_event: threading.Event,
    ):
        super().__init__(daemon=True)
        self.path = path
        self.window_minutes = window_minutes
        self.refresh_secs = refresh_secs
        self.from_start = from_start
        self.update_callback = update_callback
        self.stop_event = stop_event

        self.window: Deque[LootEvent] = deque()

    def add_event(self, ev: LootEvent):
        self.window.append(ev)
        cutoff = ev.ts - dt.timedelta(minutes=self.window_minutes)
        while self.window and self.window[0].ts < cutoff:
            self.window.popleft()

    def compute_stats_from_window(self) -> Optional[Dict]:
        if not self.window:
            return None

        events_list = list(self.window)
        total_yang = sum(ev.quantity for ev in events_list if ev.is_yang)
        items_qty: Dict[str, int] = defaultdict(int)
        for ev in events_list:
            if not ev.is_yang:
                items_qty[ev.item] += ev.quantity

        start = events_list[0].ts
        end = events_list[-1].ts
        elapsed = max((end - start).total_seconds(), 1)
        hours = elapsed / 3600.0
        minutes = elapsed / 60.0

        # Build per-item stats including per-hour (rounded to int)
        items_list: List[Tuple[str, int, int]] = []
        for name, qty in items_qty.items():
            per_hour = int(round(qty / hours))
            items_list.append((name, qty, per_hour))

        # Sort by quantity desc
        items_list.sort(key=lambda x: x[1], reverse=True)

        stats = {
            "start": start,
            "end": end,
            "hours": hours,
            "minutes": minutes,
            "total_yang": total_yang,
            "yang_per_hour": int(round(total_yang / hours)),
            "yang_per_minute": int(round(total_yang / minutes)),
            "items": items_list,
        }
        return stats

    def run(self):
        try:
            f = open(self.path, "r", encoding="utf-8", errors="ignore")
        except OSError as e:
            # Send error to UI via callback as None with extra key
            self.update_callback({"error": f"Cannot open log file: {e}"})
            return

        if not self.from_start:
            f.seek(0, os.SEEK_END)

        last_print = time.time()

        while not self.stop_event.is_set():
            line = f.readline()
            if not line:
                # no new data
                time.sleep(0.2)
            else:
                ev = parse_log_line(line)
                if ev:
                    self.add_event(ev)

            now_ts = time.time()
            if now_ts - last_print >= self.refresh_secs:
                last_print = now_ts
                stats = self.compute_stats_from_window()
                if stats is not None:
                    self.update_callback(stats)

        f.close()


# ---------------------------------------------------------------------------
# Tkinter UI - Modern Dark Theme
# ---------------------------------------------------------------------------

class LootMonitorApp(tk.Tk):
    def __init__(self):
        super().__init__()
        
        self.title("💰 Loot Monitor - By Paysami AI slop v1.1 - Download only from there: https://github.com/PaysamiKekW/Jinteia-Loot-Analyzer-FREE/")
        self.geometry("1000x700")
        
        # Set dark theme colors
        self.bg_color = "#1a1a2e"
        self.card_bg = "#16213e"
        self.accent_color = "#0fcc45"
        self.accent_secondary = "#0ea5e9"
        self.text_color = "#e2e8f0"
        self.muted_text = "#94a3b8"
        
        self.configure(bg=self.bg_color)
        
        # Configure styles
        self.style = ttk.Style(self)
        self.style.theme_use("clam")
        
        # Configure ttk styles
        self.style.configure("TFrame", background=self.bg_color)
        self.style.configure("TLabelframe", background=self.bg_color, relief="flat", borderwidth=0)
        self.style.configure("TLabelframe.Label", background=self.card_bg, foreground=self.text_color, 
                           font=("Segoe UI", 11, "bold"), padding=(10, 5))
        self.style.configure("TLabel", background=self.bg_color, foreground=self.text_color, 
                           font=("Segoe UI", 10))
        self.style.configure("Header.TLabel", font=("Segoe UI", 12, "bold"), foreground=self.accent_color)
        self.style.configure("Stats.TLabel", font=("Segoe UI", 18, "bold"), foreground=self.accent_secondary)
        
        # Button styles
        self.style.configure("Accent.TButton", background=self.accent_color, foreground="white",
                           font=("Segoe UI", 10, "bold"), borderwidth=0, padding=10)
        self.style.map("Accent.TButton",
                      background=[("active", "#0db33d"), ("disabled", "#4a5568")])
        
        self.style.configure("Secondary.TButton", background="#4a5568", foreground="white",
                           font=("Segoe UI", 10), borderwidth=0, padding=8)
        
        # Treeview styles
        self.style.configure("Treeview", background="#2d3748", foreground=self.text_color,
                           fieldbackground="#2d3748", borderwidth=0, font=("Segoe UI", 10))
        self.style.configure("Treeview.Heading", background="#1e293b", foreground=self.accent_secondary,
                           font=("Segoe UI", 10, "bold"), borderwidth=0)
        self.style.map("Treeview", background=[("selected", "#4a5568")])
        
        self.stop_event = threading.Event()
        self.worker: Optional[LiveMonitorWorker] = None
        
        self.create_widgets()

    # -------------------- UI layout -------------------- #

    def create_widgets(self):
        # Create a main container with padding
        main_container = ttk.Frame(self)
        main_container.pack(fill="both", expand=True, padx=20, pady=20)
        
        # Header section
        header_frame = ttk.Frame(main_container)
        header_frame.pack(fill="x", pady=(0, 20))
        
        ttk.Label(header_frame, text="💰 Jinteia Loot Analyzer [AI Slop by Paysami]", style="Header.TLabel").pack(side="left")
        ttk.Label(header_frame, text="Real-time Yang & Loot Tracker", 
                 foreground=self.muted_text).pack(side="left", padx=(10, 0))
        
        # Settings Card
        settings_card = tk.Frame(main_container, bg=self.card_bg, relief="flat", borderwidth=0)
        settings_card.pack(fill="x", pady=(0, 20))
        
        # Settings header
        settings_header = tk.Frame(settings_card, bg=self.card_bg)
        settings_header.pack(fill="x", padx=20, pady=(15, 10))
        tk.Label(settings_header, text="⚙️ Settings", bg=self.card_bg, fg=self.text_color,
                font=("Segoe UI", 11, "bold")).pack(side="left")
        
        # Settings content
        settings_content = tk.Frame(settings_card, bg=self.card_bg)
        settings_content.pack(fill="x", padx=20, pady=(0, 20))
        
        # Row 1: Log file selection
        row1 = tk.Frame(settings_content, bg=self.card_bg)
        row1.pack(fill="x", pady=8)
        
        tk.Label(row1, text="Log File:", bg=self.card_bg, fg=self.text_color,
                font=("Segoe UI", 10)).pack(side="left")
        
        self.log_path_var = tk.StringVar(value="info_chat_loot.log")
        log_entry = tk.Entry(row1, textvariable=self.log_path_var, bg="#2d3748", fg=self.text_color,
                           insertbackground=self.text_color, font=("Segoe UI", 10),
                           relief="flat", width=50)
        log_entry.pack(side="left", padx=(10, 5), pady=5)
        
        ttk.Button(row1, text="Browse", command=self.browse_file, 
                  style="Secondary.TButton").pack(side="left", padx=5)
        
        # Row 2: Settings controls
        row2 = tk.Frame(settings_content, bg=self.card_bg)
        row2.pack(fill="x", pady=8)
        
        tk.Label(row2, text="Window:", bg=self.card_bg, fg=self.text_color,
                font=("Segoe UI", 10)).pack(side="left")
        self.window_minutes_var = tk.IntVar(value=60)
        window_spin = tk.Spinbox(row2, from_=1, to=600, textvariable=self.window_minutes_var,
                                bg="#2d3748", fg=self.text_color, insertbackground=self.text_color,
                                font=("Segoe UI", 10), relief="flat", width=8)
        window_spin.pack(side="left", padx=(10, 20))
        
        tk.Label(row2, text="minutes", bg=self.card_bg, fg=self.muted_text,
                font=("Segoe UI", 9)).pack(side="left")
        
        tk.Label(row2, text="Refresh:", bg=self.card_bg, fg=self.text_color,
                font=("Segoe UI", 10)).pack(side="left", padx=(20, 0))
        self.refresh_secs_var = tk.IntVar(value=5)
        refresh_spin = tk.Spinbox(row2, from_=1, to=60, textvariable=self.refresh_secs_var,
                                 bg="#2d3748", fg=self.text_color, insertbackground=self.text_color,
                                 font=("Segoe UI", 10), relief="flat", width=8)
        refresh_spin.pack(side="left", padx=(10, 20))
        
        tk.Label(row2, text="seconds", bg=self.card_bg, fg=self.muted_text,
                font=("Segoe UI", 9)).pack(side="left")
        
        # From start checkbox
        self.from_start_var = tk.BooleanVar(value=False)
        from_start_check = tk.Checkbutton(row2, text="Read from beginning", 
                                         variable=self.from_start_var,
                                         bg=self.card_bg, fg=self.text_color,
                                         selectcolor=self.card_bg,
                                         activebackground=self.card_bg,
                                         activeforeground=self.text_color,
                                         font=("Segoe UI", 10))
        from_start_check.pack(side="left", padx=(20, 0))
        
        # Row 3: Control buttons
        row3 = tk.Frame(settings_content, bg=self.card_bg)
        row3.pack(fill="x", pady=(15, 0))
        
        self.start_button = ttk.Button(row3, text="▶ Start Monitoring", 
                                      command=self.start_monitor, style="Accent.TButton")
        self.start_button.pack(side="left", padx=(0, 10))
        
        self.stop_button = ttk.Button(row3, text="⏹ Stop", 
                                     command=self.stop_monitor, style="Secondary.TButton",
                                     state="disabled")
        self.stop_button.pack(side="left")
        
        # Stats Dashboard
        stats_card = tk.Frame(main_container, bg=self.card_bg, relief="flat", borderwidth=0)
        stats_card.pack(fill="x", pady=(0, 20))
        
        # Stats header
        stats_header = tk.Frame(stats_card, bg=self.card_bg)
        stats_header.pack(fill="x", padx=20, pady=(15, 10))
        tk.Label(stats_header, text="📊 Live Statistics", bg=self.card_bg, fg=self.text_color,
                font=("Segoe UI", 11, "bold")).pack(side="left")
        
        # Stats grid
        stats_grid = tk.Frame(stats_card, bg=self.card_bg)
        stats_grid.pack(fill="x", padx=20, pady=(0, 20))
        
        # Time stats
        time_frame = tk.Frame(stats_grid, bg=self.card_bg)
        time_frame.grid(row=0, column=0, sticky="w", padx=(0, 40), pady=10)
        
        self.interval_label = tk.Label(time_frame, text="Interval: Not started", 
                                      bg=self.card_bg, fg=self.muted_text,
                                      font=("Segoe UI", 10))
        self.interval_label.pack(anchor="w")
        
        self.window_length_label = tk.Label(time_frame, text="Window: 0.00 h", 
                                           bg=self.card_bg, fg=self.muted_text,
                                           font=("Segoe UI", 10))
        self.window_length_label.pack(anchor="w")
        
        # Yang stats
        yang_frame = tk.Frame(stats_grid, bg=self.card_bg)
        yang_frame.grid(row=0, column=1, sticky="w", padx=40, pady=10)
        
        tk.Label(yang_frame, text="Total Yang", bg=self.card_bg, fg=self.muted_text,
                font=("Segoe UI", 10)).pack(anchor="w")
        self.yang_label = tk.Label(yang_frame, text="0", bg=self.card_bg, 
                                  fg=self.accent_color, font=("Segoe UI", 24, "bold"))
        self.yang_label.pack(anchor="w")
        
        # Yang per hour
        yang_rate_frame = tk.Frame(stats_grid, bg=self.card_bg)
        yang_rate_frame.grid(row=0, column=2, sticky="w", padx=40, pady=10)
        
        tk.Label(yang_rate_frame, text="Yang / Hour", bg=self.card_bg, fg=self.muted_text,
                font=("Segoe UI", 10)).pack(anchor="w")
        self.yang_per_hour_label = tk.Label(yang_rate_frame, text="0", bg=self.card_bg,
                                           fg=self.accent_secondary, font=("Segoe UI", 24, "bold"))
        self.yang_per_hour_label.pack(anchor="w")
        
        # Yang per minute
        yang_min_frame = tk.Frame(stats_grid, bg=self.card_bg)
        yang_min_frame.grid(row=0, column=3, sticky="w", padx=40, pady=10)
        
        tk.Label(yang_min_frame, text="Yang / Minute", bg=self.card_bg, fg=self.muted_text,
                font=("Segoe UI", 10)).pack(anchor="w")
        self.yang_per_minute_label = tk.Label(yang_min_frame, text="0", bg=self.card_bg,
                                            fg="#f59e0b", font=("Segoe UI", 24, "bold"))
        self.yang_per_minute_label.pack(anchor="w")
        
        # Loot Items Table
        loot_card = tk.Frame(main_container, bg=self.card_bg, relief="flat", borderwidth=0)
        loot_card.pack(fill="both", expand=True)
        
        # Loot header
        loot_header = tk.Frame(loot_card, bg=self.card_bg)
        loot_header.pack(fill="x", padx=20, pady=(15, 10))
        tk.Label(loot_header, text="📦 Collected Items", bg=self.card_bg, fg=self.text_color,
                font=("Segoe UI", 11, "bold")).pack(side="left")
        
        # Treeview with custom styling
        tree_container = tk.Frame(loot_card, bg=self.card_bg)
        tree_container.pack(fill="both", expand=True, padx=20, pady=(0, 20))
        
        columns = ("item", "quantity", "per_hour")
        self.tree = ttk.Treeview(tree_container, columns=columns, show="headings", height=12)
        
        # Configure columns
        self.tree.heading("item", text="Item Name", anchor="w")
        self.tree.heading("quantity", text="Quantity", anchor="center")
        self.tree.heading("per_hour", text="Quantity / Hour", anchor="center")
        
        self.tree.column("item", width=400, anchor="w")
        self.tree.column("quantity", width=150, anchor="center")
        self.tree.column("per_hour", width=150, anchor="center")
        
        # Scrollbars
        vsb = ttk.Scrollbar(tree_container, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(tree_container, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        
        # Grid layout for tree and scrollbars
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        
        tree_container.grid_rowconfigure(0, weight=1)
        tree_container.grid_columnconfigure(0, weight=1)
        
        # Footer
        footer = tk.Frame(main_container, bg=self.bg_color)
        footer.pack(fill="x", pady=(20, 0))
        tk.Label(footer, text="⚠️ Download only from official repository", 
                bg=self.bg_color, fg=self.muted_text, font=("Segoe UI", 9)).pack()

    # -------------------- UI helpers -------------------- #

    def reset_stats_ui(self):
        """Clear stats and item list for a fresh start."""
        self.interval_label.config(text="Interval: Not started", fg=self.muted_text)
        self.window_length_label.config(text="Window: 0.00 h", fg=self.muted_text)
        self.yang_label.config(text="0", fg=self.accent_color)
        self.yang_per_hour_label.config(text="0", fg=self.accent_secondary)
        self.yang_per_minute_label.config(text="0", fg="#f59e0b")
        self.tree.delete(*self.tree.get_children())

    # -------------------- UI callbacks -------------------- #

    def browse_file(self):
        filename = filedialog.askopenfilename(
            title="Select log file", filetypes=[("Log files", "*.log *.txt"), ("All files", "*.*")]
        )
        if filename:
            self.log_path_var.set(filename)

    def start_monitor(self):
        if self.worker is not None:
            messagebox.showinfo("Info", "Monitor is already running.")
            return

        path = self.log_path_var.get().strip()
        if not path:
            messagebox.showerror("Error", "Please select a log file.")
            return

        # Wipe UI data and start fresh
        self.reset_stats_ui()

        window_minutes = self.window_minutes_var.get()
        refresh_secs = self.refresh_secs_var.get()
        from_start = self.from_start_var.get()

        self.stop_event = threading.Event()
        self.worker = LiveMonitorWorker(
            path=path,
            window_minutes=window_minutes,
            refresh_secs=refresh_secs,
            from_start=from_start,
            update_callback=self.schedule_update_stats,
            stop_event=self.stop_event,
        )
        self.worker.start()

        self.start_button.config(state="disabled")
        self.stop_button.config(state="normal")

    def stop_monitor(self):
        if self.worker is not None:
            self.stop_event.set()
            # Ensure worker has time to close the file
            self.worker.join(timeout=1.0)
            self.worker = None

        # Keep the data in the UI, just re-enable Start
        self.start_button.config(state="normal")
        self.stop_button.config(state="disabled")

    def on_close(self):
        self.stop_monitor()
        self.destroy()

    # -------------------- Stats update -------------------- #

    def schedule_update_stats(self, stats: Dict):
        """
        Called from the worker thread.
        We must schedule the actual UI update on the Tkinter main thread using after().
        """
        self.after(0, self.update_stats, stats)

    def update_stats(self, stats: Dict):
        if "error" in stats:
            messagebox.showerror("Error", stats["error"])
            self.stop_monitor()
            return

        start = stats["start"]
        end = stats["end"]
        hours = stats["hours"]
        minutes = stats["minutes"]
        total_yang = stats["total_yang"]
        yang_per_hour = stats["yang_per_hour"]
        yang_per_minute = stats["yang_per_minute"]
        items_list = stats["items"]

        # Format yang with thousands separator
        yang_formatted = f"{total_yang:,}"
        yang_ph_formatted = f"{yang_per_hour:,}"
        yang_pm_formatted = f"{yang_per_minute:,}"
        
        # Update time info
        self.interval_label.config(
            text=f"Interval: {start.strftime('%H:%M:%S')} → {end.strftime('%H:%M:%S')}",
            fg=self.text_color
        )
        self.window_length_label.config(
            text=f"Window: {hours:.2f} h ({minutes:.1f} min)",
            fg=self.text_color
        )
        
        # Update yang stats
        self.yang_label.config(text=yang_formatted)
        self.yang_per_hour_label.config(text=yang_ph_formatted)
        self.yang_per_minute_label.config(text=yang_pm_formatted)

        # Update items tree
        self.tree.delete(*self.tree.get_children())
        for idx, (name, qty, per_hour) in enumerate(items_list):
            # Alternate row colors
            tag = 'evenrow' if idx % 2 == 0 else 'oddrow'
            
            self.tree.insert(
                "",
                "end",
                values=(
                    name,
                    f"{qty:,}",
                    f"{per_hour:,}",
                ),
                tags=(tag,)
            )
        
        # Configure row colors
        self.tree.tag_configure('evenrow', background='#2d3748', foreground=self.text_color)
        self.tree.tag_configure('oddrow', background='#374151', foreground=self.text_color)


def main():
    app = LootMonitorApp()
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()


if __name__ == "__main__":
    main()
