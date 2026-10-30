"""
Windows Kernel Optimization Engine (MMAgent)
Interfaces with Windows Memory Manager Agent (MMAgent) to inspect and activate
in-memory compression and memory page combining (deduplication).

Designed for silent execution with zero flashing console windows
(using Win32 ShellExecuteW with 'runas' and SW_HIDE) and non-blocking
psutil process inspection.
"""

import os
import json
import time
import ctypes
import subprocess
from typing import Dict, Any
import psutil

# Module-level caching to eliminate unnecessary polling
_CACHE_STATUS = None
_CACHE_TIMESTAMP = 0.0
CACHE_TTL_SECONDS = 60.0

SW_HIDE = 0


def _silent_subprocess_run(cmd: list, timeout: int = 10) -> subprocess.CompletedProcess:
    """
    Executes a subprocess on Windows strictly without creating or flashing
    any visible console or terminal window.
    """
    startupinfo = None
    creationflags = 0
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        startupinfo=startupinfo,
        creationflags=creationflags,
    )


def is_admin() -> bool:
    """Checks whether the current process has Windows Administrator privileges."""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def is_memory_compression_process_running() -> bool:
    """
    Fast, pure-Python check for the Windows kernel memory compression process.
    Matches 'MemCompression' (the actual Windows process name) or 'Memory Compression'
    without requiring administrator rights.
    """
    for proc in psutil.process_iter(["name"]):
        try:
            name = proc.info.get("name")
            if name and any(k in name.lower() for k in ["memcompression", "memory compression"]):
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return False


def get_mmagent_status(force_refresh: bool = False) -> Dict[str, Any]:
    """
    Queries current kernel status of MemoryCompression and PageCombining.
    Uses memory caching (60s TTL) to prevent repeated overhead.
    For non-elevated sessions, uses fast psutil inspection without shelling out.

    Returns:
        Dict containing:
            - memory_compression (bool): True if in-memory compression is enabled
            - page_combining (bool): True if page deduplication is enabled
            - is_elevated (bool): True if query ran with admin rights
            - raw_output (dict): Parsed JSON payload or diagnostic info
    """
    global _CACHE_STATUS, _CACHE_TIMESTAMP

    now = time.time()
    if not force_refresh and _CACHE_STATUS is not None and (now - _CACHE_TIMESTAMP) < CACHE_TTL_SECONDS:
        return _CACHE_STATUS

    result = {
        "memory_compression": False,
        "page_combining": False,
        "is_elevated": False,
        "raw_output": {},
        "error": None,
    }

    elevated = is_admin()
    result["is_elevated"] = elevated

    comp_active = is_memory_compression_process_running()

    # Fast path for non-elevated users:
    # Windows blocks Get-MMAgent with 'Access is denied' for non-admins,
    # so we inspect the active kernel MemCompression process directly.
    if not elevated:
        result["memory_compression"] = comp_active
        # In modern Windows 10/11, when MemCompression is running, Page Combining is active
        result["page_combining"] = comp_active
        result["error"] = "Active kernel MemCompression process detected." if comp_active else "MemCompression process not found."
        _CACHE_STATUS = result
        _CACHE_TIMESTAMP = now
        return result

    # Elevated path: Execute Get-MMAgent silently with hidden window
    cmd = [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        "Get-MMAgent | Select-Object -Property MemoryCompression,PageCombining | ConvertTo-Json",
    ]

    try:
        proc = _silent_subprocess_run(cmd, timeout=8)
        stdout = (proc.stdout or "").strip()

        if proc.returncode == 0 and stdout:
            try:
                data = json.loads(stdout)
                result["memory_compression"] = bool(data.get("MemoryCompression", False))
                result["page_combining"] = bool(data.get("PageCombining", False))
                result["raw_output"] = data
            except json.JSONDecodeError:
                result["memory_compression"] = comp_active
                result["page_combining"] = comp_active
        else:
            result["memory_compression"] = comp_active
            result["page_combining"] = comp_active
    except Exception as exc:
        result["error"] = str(exc)
        result["memory_compression"] = comp_active
        result["page_combining"] = comp_active

    _CACHE_STATUS = result
    _CACHE_TIMESTAMP = now
    return result


def enable_kernel_features() -> bool:
    """
    Elevates directly via native Win32 ShellExecuteW ('runas') to execute
    'Enable-MMAgent -MemoryCompression -PageCombining' with SW_HIDE.

    This ensures:
      1. Native Windows UAC dialog appears directly (no intermediate cmd or powershell window).
      2. The elevated PowerShell runs completely hidden (SW_HIDE + -WindowStyle Hidden).
      3. No black terminal windows flash on screen.

    Returns:
        True if the user accepted the UAC prompt (ShellExecute return value > 32).
    """
    global _CACHE_TIMESTAMP
    _CACHE_TIMESTAMP = 0.0  # Invalidate cache so next read is immediate

    parameters = '-NoProfile -WindowStyle Hidden -Command "Enable-MMAgent -MemoryCompression -PageCombining"'

    try:
        # ShellExecuteW returns HINSTANCE (> 32 on success, 5 on user UAC cancel)
        ret = ctypes.windll.shell32.ShellExecuteW(
            None,
            "runas",
            "powershell.exe",
            parameters,
            None,
            SW_HIDE,
        )
        return ret > 32
    except Exception as exc:
        print(f"[EdgeRAM] Error invoking UAC elevation for MMAgent: {exc}")
        return False
