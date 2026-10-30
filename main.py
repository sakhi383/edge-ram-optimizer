"""
EdgeRAM-Optimizer - Principal Windows Systems Application
Standalone background system-tray application and dashboard for optimizing
Microsoft Edge's memory footprint across Chromium Core, Win32 OS, and Windows Kernel layers.
"""

import os
import sys
import threading
import time
from typing import Optional
from PIL import Image, ImageDraw
import customtkinter as ctk

from core.memory_trimmer import trim_edge_working_set, get_edge_memory_metrics
from core.edge_launcher import (
    launch_optimized_edge,
    is_edge_running_optimized,
    create_optimized_shortcut,
    relaunch_optimized_edge,
)
from core.kernel_mmagent import get_mmagent_status, enable_kernel_features
import pystray

# Set High-DPI awareness on Windows to ensure crisp rendering
try:
    import ctypes
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass

# CustomTkinter Dark Theme Defaults
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


class EdgeRamOptimizerApp:
    def __init__(self):
        self.root = ctk.CTk()
        self.root.title("EdgeRAM-Optimizer")
        self.root.geometry("680 x 590")
        self.root.minsize(640, 560)

        # Threading & State Control
        self.auto_purge_enabled = False
        self.auto_purge_interval_sec = 30
        self._stop_event = threading.Event()
        self._tray_icon: Optional[pystray.Icon] = None
        self.last_freed_msg = "No purge executed yet this session."
        self.current_tray_header = "Edge RAM: -- (0 Processes)"

        # Load or generate application icon
        self.icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.png")
        self.app_icon_img = self._get_or_create_icon()

        # Set Window Icon
        try:
            ico_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.ico")
            if os.path.isfile(ico_path):
                self.root.iconbitmap(ico_path)
        except Exception:
            pass

        # Build GUI
        self._build_ui()
        self._refresh_kernel_status()

        # Intercept window close event to hide to system tray
        self.root.protocol("WM_DELETE_WINDOW", self.hide_to_tray)

        # Start Tray and Background Loops
        self._start_tray_icon()
        self._start_auto_purge_thread()

        # Start periodic GUI metrics refresh (every 2.5 seconds)
        self.root.after(500, self._periodic_gui_refresh)

    def _get_or_create_icon(self) -> Image.Image:
        """Returns PIL Image for system tray and window."""
        if os.path.isfile(self.icon_path):
            try:
                return Image.open(self.icon_path)
            except Exception:
                pass

        # Fallback procedural icon generation
        img = Image.new("RGBA", (64, 64), color=(0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.ellipse([4, 4, 60, 60], fill="#0f172a", outline="#0ea5e9", width=3)
        d.polygon([(32, 12), (20, 36), (30, 36), (26, 52), (44, 28), (34, 28)], fill="#38bdf8")
        return img

    def _build_ui(self):
        """Constructs modern, utilitarian dark-mode dashboard."""
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(0, weight=1)

        # Main Scrollable / Stack Container
        main_frame = ctk.CTkFrame(self.root, corner_radius=12, fg_color="#0f172a")
        main_frame.grid(row=0, column=0, sticky="nsew", padx=14, pady=14)
        main_frame.grid_columnconfigure(0, weight=1)

        # 1. Header Banner
        header_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        header_frame.pack(fill="x", padx=16, pady=(14, 8))

        title_lbl = ctk.CTkLabel(
            header_frame,
            text="⚡ EdgeRAM-Optimizer",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color="#38bdf8",
        )
        title_lbl.pack(anchor="w")

        sub_lbl = ctk.CTkLabel(
            header_frame,
            text="Multi-Tier Working Set Trimming, Chromium Process Limiting & Kernel Memory Compression",
            font=ctk.CTkFont(size=11),
            text_color="#94a3b8",
        )
        sub_lbl.pack(anchor="w", pady=(1, 0))

        # 2. Live Metrics Card
        metrics_card = ctk.CTkFrame(main_frame, corner_radius=10, fg_color="#1e293b", border_width=1, border_color="#334155")
        metrics_card.pack(fill="x", padx=16, pady=8)

        m_inner = ctk.CTkFrame(metrics_card, fg_color="transparent")
        m_inner.pack(fill="x", padx=14, pady=12)
        m_inner.grid_columnconfigure((0, 1, 2), weight=1)

        # Metric 1: Physical RAM (Working Set)
        ctk.CTkLabel(m_inner, text="Physical RAM (Working Set)", font=ctk.CTkFont(size=11), text_color="#94a3b8").grid(row=0, column=0, sticky="w")
        self.lbl_ws_ram = ctk.CTkLabel(m_inner, text="-- MB", font=ctk.CTkFont(size=20, weight="bold"), text_color="#38bdf8")
        self.lbl_ws_ram.grid(row=1, column=0, sticky="w", pady=(2, 0))

        # Metric 2: Private / Commit Bytes
        ctk.CTkLabel(m_inner, text="Private / Commit Bytes", font=ctk.CTkFont(size=11), text_color="#94a3b8").grid(row=0, column=1, sticky="w")
        self.lbl_private_ram = ctk.CTkLabel(m_inner, text="-- MB", font=ctk.CTkFont(size=20, weight="bold"), text_color="#cbd5e1")
        self.lbl_private_ram.grid(row=1, column=1, sticky="w", pady=(2, 0))

        # Metric 3: Active Processes
        ctk.CTkLabel(m_inner, text="Active Edge Processes", font=ctk.CTkFont(size=11), text_color="#94a3b8").grid(row=0, column=2, sticky="w")
        self.lbl_proc_count = ctk.CTkLabel(m_inner, text="--", font=ctk.CTkFont(size=20, weight="bold"), text_color="#a855f7")
        self.lbl_proc_count.grid(row=1, column=2, sticky="w", pady=(2, 0))

        # 3. Primary Working Set Purge Action Card
        action_card = ctk.CTkFrame(main_frame, corner_radius=10, fg_color="#1e293b", border_width=1, border_color="#334155")
        action_card.pack(fill="x", padx=16, pady=8)

        act_inner = ctk.CTkFrame(action_card, fg_color="transparent")
        act_inner.pack(fill="x", padx=14, pady=12)

        self.btn_purge = ctk.CTkButton(
            act_inner,
            text="⚡ Purge Working Set Now (EmptyWorkingSet)",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#0284c7",
            hover_color="#0369a1",
            height=38,
            command=self.on_purge_working_set,
        )
        self.btn_purge.pack(fill="x")

        self.lbl_delta = ctk.CTkLabel(
            act_inner,
            text="Ready. Click Purge to flush inactive physical pages into the standby list.",
            font=ctk.CTkFont(size=11),
            text_color="#34d399",
        )
        self.lbl_delta.pack(anchor="w", pady=(6, 0))

        # 4. Chromium Core Launcher & Process Limiter
        core_card = ctk.CTkFrame(main_frame, corner_radius=10, fg_color="#1e293b", border_width=1, border_color="#334155")
        core_card.pack(fill="x", padx=16, pady=8)

        core_inner = ctk.CTkFrame(core_card, fg_color="transparent")
        core_inner.pack(fill="x", padx=14, pady=12)

        c_header = ctk.CTkFrame(core_inner, fg_color="transparent")
        c_header.pack(fill="x")

        ctk.CTkLabel(c_header, text="Chromium Core Optimization", font=ctk.CTkFont(size=13, weight="bold"), text_color="#f8fafc").pack(side="left")
        self.lbl_core_status = ctk.CTkLabel(c_header, text="Status: Detecting...", font=ctk.CTkFont(size=11, weight="bold"), text_color="#fbbf24")
        self.lbl_core_status.pack(side="right")

        c_desc = ctk.CTkLabel(
            core_inner,
            text="Flags: --renderer-process-limit=8 --process-per-site --enable-features=FreezeIndividualSubframes,AutomaticTabDiscarding",
            font=ctk.CTkFont(size=10),
            text_color="#94a3b8",
            wraplength=600,
            justify="left",
        )
        c_desc.pack(anchor="w", pady=(3, 8))

        c_btns = ctk.CTkFrame(core_inner, fg_color="transparent")
        c_btns.pack(fill="x")
        c_btns.grid_columnconfigure((0, 1), weight=1)

        self.btn_relaunch = ctk.CTkButton(
            c_btns,
            text="Relaunch Edge in Low-RAM Mode",
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#6366f1",
            hover_color="#4f46e5",
            height=32,
            command=self.on_relaunch_edge,
        )
        self.btn_relaunch.grid(row=0, column=0, padx=(0, 6), sticky="ew")

        self.btn_shortcut = ctk.CTkButton(
            c_btns,
            text="Create Desktop Shortcut (.lnk)",
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#334155",
            hover_color="#475569",
            height=32,
            command=self.on_create_shortcut,
        )
        self.btn_shortcut.grid(row=0, column=1, padx=(6, 0), sticky="ew")

        # 5. Windows Kernel (MMAgent) Optimization Card
        kernel_card = ctk.CTkFrame(main_frame, corner_radius=10, fg_color="#1e293b", border_width=1, border_color="#334155")
        kernel_card.pack(fill="x", padx=16, pady=8)

        k_inner = ctk.CTkFrame(kernel_card, fg_color="transparent")
        k_inner.pack(fill="x", padx=14, pady=12)

        k_header = ctk.CTkFrame(k_inner, fg_color="transparent")
        k_header.pack(fill="x")

        ctk.CTkLabel(k_header, text="Windows Kernel Memory Management (MMAgent)", font=ctk.CTkFont(size=13, weight="bold"), text_color="#f8fafc").pack(side="left")

        # Badges row
        k_badges = ctk.CTkFrame(k_inner, fg_color="transparent")
        k_badges.pack(fill="x", pady=(6, 8))

        self.badge_compression = ctk.CTkLabel(
            k_badges,
            text="Memory Compression: CHECKING",
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#334155",
            corner_radius=6,
            padx=8,
            pady=3,
        )
        self.badge_compression.pack(side="left", padx=(0, 8))

        self.badge_combining = ctk.CTkLabel(
            k_badges,
            text="Page Combining: CHECKING",
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#334155",
            corner_radius=6,
            padx=8,
            pady=3,
        )
        self.badge_combining.pack(side="left")

        self.btn_enable_kernel = ctk.CTkButton(
            k_inner,
            text="🛡️ Activate Kernel Deduplication & Compression (UAC Elevation)",
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#0f766e",
            hover_color="#115e59",
            height=30,
            command=self.on_enable_kernel_features,
        )
        self.btn_enable_kernel.pack(fill="x")

        # 6. Background Daemon Settings & Status Bar
        bottom_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        bottom_frame.pack(fill="x", padx=16, pady=(6, 12))

        self.chk_auto_purge = ctk.CTkCheckBox(
            bottom_frame,
            text="Auto-Purge Working Set every 30 seconds (Background Thread)",
            font=ctk.CTkFont(size=12),
            command=self.on_toggle_auto_purge_gui,
        )
        self.chk_auto_purge.pack(anchor="w", pady=(0, 6))

        self.lbl_status_bar = ctk.CTkLabel(
            bottom_frame,
            text="Daemon initialized. Monitoring active msedge.exe processes.",
            font=ctk.CTkFont(size=11),
            text_color="#64748b",
        )
        self.lbl_status_bar.pack(anchor="w")

    # --- System Tray Implementation ---

    def _start_tray_icon(self):
        """Initializes and launches the pystray background daemon."""
        menu = pystray.Menu(
            pystray.MenuItem(lambda text: self.current_tray_header, None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("⚡ Purge RAM Now", lambda: self.root.after(0, self.on_purge_working_set)),
            pystray.MenuItem("🚀 Launch Optimized Edge", lambda: self.root.after(0, self.on_launch_optimized)),
            pystray.MenuItem(
                "⏱️ Auto-Purge Loop (30s)",
                self.on_toggle_auto_purge_tray,
                checked=lambda item: self.auto_purge_enabled,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("🖥️ Open Dashboard", lambda: self.root.after(0, self.show_dashboard), default=True),
            pystray.MenuItem("❌ Exit", lambda: self.root.after(0, self.on_exit)),
        )

        self._tray_icon = pystray.Icon(
            "EdgeRAM-Optimizer",
            self.app_icon_img,
            "EdgeRAM-Optimizer",
            menu=menu,
        )

        tray_thread = threading.Thread(target=self._tray_icon.run, daemon=True)
        tray_thread.start()

    def hide_to_tray(self):
        """Minimizes window to system tray instead of closing application."""
        self.root.withdraw()
        if self._tray_icon and self._tray_icon.visible:
            try:
                self._tray_icon.notify(
                    "EdgeRAM-Optimizer is running in the background.",
                    title="Minimized to System Tray"
                )
            except Exception:
                pass

    def show_dashboard(self):
        """Restores dashboard window to foreground."""
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    # --- Background Auto-Purge Worker ---

    def _start_auto_purge_thread(self):
        """Starts worker thread that periodically executes EmptyWorkingSet."""
        thread = threading.Thread(target=self._auto_purge_worker, daemon=True)
        thread.start()

    def _auto_purge_worker(self):
        """Periodic background working set trimmer."""
        while not self._stop_event.is_set():
            if self.auto_purge_enabled:
                freed_mb, count = trim_edge_working_set()
                if count > 0 and freed_mb > 1.0:
                    self.last_freed_msg = f"Auto-Purge: Freed {freed_mb:.1f} MB across {count} processes."
                    self.root.after(0, lambda: self.lbl_delta.configure(
                        text=f"Last Auto-Purge: Freed {freed_mb:.1f} MB across {count} processes.",
                        text_color="#34d399",
                    ))
            # Sleep in small increments for responsive shutdown
            for _ in range(self.auto_purge_interval_sec * 2):
                if self._stop_event.is_set():
                    break
                time.sleep(0.5)

    def on_toggle_auto_purge_gui(self):
        """Checkbox toggle from dashboard GUI."""
        self.auto_purge_enabled = bool(self.chk_auto_purge.get())
        state_str = "ENABLED" if self.auto_purge_enabled else "DISABLED"
        self.lbl_status_bar.configure(text=f"Auto-purge loop is now {state_str} (30s interval).")

    def on_toggle_auto_purge_tray(self, icon, item):
        """Checkbox toggle from system tray context menu."""
        self.auto_purge_enabled = not self.auto_purge_enabled
        self.root.after(0, lambda: self.chk_auto_purge.select() if self.auto_purge_enabled else self.chk_auto_purge.deselect())
        state_str = "ENABLED" if self.auto_purge_enabled else "DISABLED"
        self.root.after(0, lambda: self.lbl_status_bar.configure(text=f"Auto-purge loop {state_str} from tray."))

    # --- UI Actions ---

    def on_purge_working_set(self):
        """Executes manual Win32 EmptyWorkingSet purge."""
        self.btn_purge.configure(state="disabled", text="Purging Working Sets...")
        self.root.update_idletasks()

        freed_mb, count = trim_edge_working_set()

        if count > 0:
            msg = f"Last Purge: Freed {freed_mb:.1f} MB physical RAM across {count} Edge processes!"
            color = "#34d399"
        else:
            msg = "No active Edge processes found to purge."
            color = "#fbbf24"

        self.last_freed_msg = msg
        self.lbl_delta.configure(text=msg, text_color=color)
        self.lbl_status_bar.configure(text=f"Manual purge complete. {msg}")

        # Update tray tooltip with saved MB
        if self._tray_icon:
            self._tray_icon.title = f"EdgeRAM: Last Freed {freed_mb:.1f} MB"

        self.btn_purge.configure(state="normal", text="⚡ Purge Working Set Now (EmptyWorkingSet)")
        self._refresh_metrics()

    def on_relaunch_edge(self):
        """Relaunches Edge with process limit flags."""
        self.lbl_status_bar.configure(text="Terminating existing instances & launching optimized Edge...")
        self.root.update_idletasks()
        try:
            relaunch_optimized_edge()
            self.lbl_status_bar.configure(text="Microsoft Edge launched in optimized Low-RAM mode.")
        except Exception as e:
            self.lbl_status_bar.configure(text=f"Relaunch error: {e}")
        self.root.after(1200, self._refresh_metrics)

    def on_launch_optimized(self):
        """Spawns an optimized Edge instance from tray or GUI."""
        try:
            launch_optimized_edge()
            self.lbl_status_bar.configure(text="Launched Microsoft Edge with optimized flags.")
        except Exception as e:
            self.lbl_status_bar.configure(text=f"Launch error: {e}")
        self.root.after(1000, self._refresh_metrics)

    def on_create_shortcut(self):
        """Creates desktop shortcut with optimized flags."""
        try:
            path = create_optimized_shortcut()
            self.lbl_status_bar.configure(text=f"Created shortcut: {os.path.basename(path)} on Desktop.")
        except Exception as e:
            self.lbl_status_bar.configure(text=f"Shortcut error: {e}")

    def on_enable_kernel_features(self):
        """Triggers UAC prompt to enable MMAgent MemoryCompression & PageCombining."""
        self.lbl_status_bar.configure(text="Requesting Windows Administrator permission (UAC)...")
        self.btn_enable_kernel.configure(state="disabled", text="Enabling Kernel Compression...")
        self.root.update_idletasks()
        success = enable_kernel_features()
        if success:
            self.lbl_status_bar.configure(text="Kernel optimization applied. Refreshing status...")
            self.root.after(2000, lambda: self._refresh_kernel_status(force_refresh=True))
        else:
            self.lbl_status_bar.configure(text="UAC elevation was cancelled.")
            self._refresh_kernel_status(force_refresh=True)

    # --- Periodic Metrics & Refresh ---

    def _periodic_gui_refresh(self):
        """Scheduled GUI refresh cycle (pure Win32/psutil metrics, zero console popups)."""
        self._refresh_metrics()
        self.root.after(2500, self._periodic_gui_refresh)

    def _refresh_metrics(self):
        """Fetches memory usage and process flag status."""
        try:
            metrics = get_edge_memory_metrics()
            opt_status = is_edge_running_optimized()

            ws_mb = metrics["total_working_set_mb"]
            priv_mb = metrics["total_private_mb"]
            proc_count = metrics["process_count"]

            self.lbl_ws_ram.configure(text=f"{ws_mb:,.1f} MB")
            self.lbl_private_ram.configure(text=f"{priv_mb:,.1f} MB")
            self.lbl_proc_count.configure(text=str(proc_count))

            # Update tray header text
            self.current_tray_header = f"Edge RAM: {ws_mb:,.0f} MB ({proc_count} Processes)"

            # Update Core status label
            if not opt_status["is_running"]:
                self.lbl_core_status.configure(text="Status: Edge Not Running", text_color="#94a3b8")
            elif opt_status["is_optimized"]:
                self.lbl_core_status.configure(text="Status: Optimized (Limit=8 Active)", text_color="#34d399")
            else:
                self.lbl_core_status.configure(text="Status: Standard (Uncapped Process Pool)", text_color="#fbbf24")

        except Exception as e:
            pass

    def _refresh_kernel_status(self, force_refresh: bool = False):
        """Queries MMAgent status and updates badges."""
        try:
            status = get_mmagent_status(force_refresh=force_refresh)
            comp_on = status["memory_compression"]
            comb_on = status["page_combining"]

            if comp_on:
                self.badge_compression.configure(
                    text="Memory Compression: ON", fg_color="#065f46", text_color="#34d399"
                )
            else:
                self.badge_compression.configure(
                    text="Memory Compression: OFF", fg_color="#7f1d1d", text_color="#f87171"
                )

            if comb_on:
                self.badge_combining.configure(
                    text="Page Combining: ON", fg_color="#065f46", text_color="#34d399"
                )
            else:
                self.badge_combining.configure(
                    text="Page Combining: OFF", fg_color="#7f1d1d", text_color="#f87171"
                )

            if comp_on and comb_on:
                self.btn_enable_kernel.configure(
                    text="✔ Kernel Compression & Page Combining Active",
                    fg_color="#064e3b",
                    hover_color="#065f46",
                    state="disabled",
                )
            else:
                self.btn_enable_kernel.configure(
                    text="🛡️ Activate Kernel Deduplication & Compression (UAC Elevation)",
                    fg_color="#0f766e",
                    hover_color="#115e59",
                    state="normal",
                )
        except Exception:
            pass

    def on_exit(self):
        """Clean shutdown handler."""
        self._stop_event.set()
        if self._tray_icon:
            try:
                self._tray_icon.stop()
            except Exception:
                pass
        self.root.destroy()
        sys.exit(0)

    def run(self):
        """Runs the main application loop."""
        self.root.mainloop()


if __name__ == "__main__":
    app = EdgeRamOptimizerApp()
    app.run()
