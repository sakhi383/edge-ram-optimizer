"""
Chromium Core Process Limiting & Edge Launcher Engine
Provides automatic executable discovery, process consolidation argument injection,
active CLI flag inspection, and Windows Shell (.lnk) shortcut creation.
"""

import os
import subprocess
import winreg
from typing import List, Dict, Any, Optional
import psutil
import win32com.client

# Standard process consolidation and aggressive tab freeze flags
OPTIMIZED_FLAGS = [
    "--renderer-process-limit=8",
    "--process-per-site",
    "--enable-features=FreezeIndividualSubframes,AutomaticTabDiscarding",
]


def locate_edge_executable() -> str:
    """
    Locates msedge.exe across standard 64-bit/32-bit directories,
    user AppData directories, and the Windows Registry App Paths.

    Returns:
        Absolute path to msedge.exe

    Raises:
        FileNotFoundError: If Microsoft Edge installation is not found.
    """
    candidate_paths = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%PROGRAMFILES(X86)%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%PROGRAMFILES%\Microsoft\Edge\Application\msedge.exe"),
    ]

    for path in candidate_paths:
        if path and os.path.isfile(path):
            return os.path.abspath(path)

    # Secondary lookup via Windows Registry App Paths
    registry_keys = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe"),
    ]

    for root, subkey in registry_keys:
        try:
            with winreg.OpenKey(root, subkey) as key:
                val, _ = winreg.QueryValueEx(key, "")
                if val and os.path.isfile(val):
                    return os.path.abspath(val)
        except OSError:
            continue

    raise FileNotFoundError("Microsoft Edge executable (msedge.exe) was not found on this system.")


def launch_optimized_edge(extra_args: Optional[List[str]] = None) -> subprocess.Popen:
    """
    Spawns Microsoft Edge with optimized process-consolidation arguments
    in an independent process group.

    Args:
        extra_args: Optional additional command-line parameters (e.g. URLs).

    Returns:
        subprocess.Popen instance.
    """
    edge_exe = locate_edge_executable()
    cmd = [edge_exe] + OPTIMIZED_FLAGS + (extra_args or [])

    # Launch in a detached/independent process group
    creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP
    if hasattr(subprocess, "DETACHED_PROCESS"):
        creation_flags |= subprocess.DETACHED_PROCESS

    proc = subprocess.Popen(
        cmd,
        creationflags=creation_flags,
        close_fds=True,
    )
    return proc


def is_edge_running_optimized() -> Dict[str, Any]:
    """
    Inspects all active msedge.exe processes to check if they are running
    with the --renderer-process-limit parameter.

    Returns:
        Dict with keys:
            - is_running (bool)
            - is_optimized (bool)
            - total_processes (int)
            - optimized_processes (int)
            - pids (list of int)
    """
    pids = []
    optimized_count = 0

    for proc in psutil.process_iter(["pid", "name"]):
        try:
            name = proc.info.get("name")
            if not name or name.lower() != "msedge.exe":
                continue

            pid = proc.info["pid"]
            pids.append(pid)

            # Inspect command line flags
            try:
                cmdline = proc.cmdline()
                cmd_str = " ".join(cmdline).lower()
                if "--renderer-process-limit" in cmd_str:
                    optimized_count += 1
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                pass

        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    total = len(pids)
    is_running = total > 0
    # If any process (or the root browser process) has the flag, Edge is running optimized
    is_optimized = is_running and (optimized_count > 0)

    return {
        "is_running": is_running,
        "is_optimized": is_optimized,
        "total_processes": total,
        "optimized_processes": optimized_count,
        "pids": pids,
    }


def create_optimized_shortcut(
    target_folder: Optional[str] = None,
    shortcut_name: str = "Edge (Optimized RAM).lnk"
) -> str:
    """
    Creates a desktop shortcut (.lnk) pointing to msedge.exe configured
    with the memory-reducing process consolidation arguments.

    Args:
        target_folder: Destination directory. Defaults to the user's Desktop.
        shortcut_name: File name for the shortcut.

    Returns:
        Full absolute path to the generated shortcut file.
    """
    edge_exe = locate_edge_executable()
    shell = win32com.client.Dispatch("WScript.Shell")

    if not target_folder:
        target_folder = shell.SpecialFolders("Desktop")

    os.makedirs(target_folder, exist_ok=True)
    shortcut_path = os.path.join(target_folder, shortcut_name)

    shortcut = shell.CreateShortCut(shortcut_path)
    shortcut.TargetPath = edge_exe
    shortcut.Arguments = " ".join(OPTIMIZED_FLAGS)
    shortcut.Description = "Microsoft Edge with Low-RAM Process Consolidation"
    shortcut.WorkingDirectory = os.path.dirname(edge_exe)
    shortcut.IconLocation = f"{edge_exe},0"
    shortcut.Save()

    return shortcut_path


def relaunch_optimized_edge() -> bool:
    """
    Gracefully terminates currently running instances of msedge.exe
    and starts a fresh instance with process-consolidation flags enabled.

    Returns:
        True if successfully relaunched.
    """
    # 1. Terminate existing Edge processes
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            name = proc.info.get("name")
            if name and name.lower() == "msedge.exe":
                proc.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    # Wait up to 3 seconds for clean exit, then force kill if needed
    gone, alive = psutil.wait_procs(
        [p for p in psutil.process_iter() if p.name().lower() == "msedge.exe"],
        timeout=3
    )
    for p in alive:
        try:
            p.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    # 2. Launch with optimized flags
    launch_optimized_edge()
    return True
