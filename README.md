# EdgeRAM-Optimizer

A lightweight, standalone Windows background system-tray application strictly in Python that optimizes Microsoft Edge's memory footprint across the **Chromium Core**, **Win32 OS**, and **Windows Kernel** layers without requiring external C++ compilers.

---

## 🏗️ Multi-Tier Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                    EdgeRAM-Optimizer                         │
│   (CustomTkinter Dark Dashboard & Pystray Background Tray)    │
└─────────────────┬────────────────────┬───────────────────────┘
                  │                    │
                  ▼                    ▼
     ┌────────────────────────┐  ┌────────────────────────┐
     │ 1. Chromium Core Layer │  │ 2. Win32 OS Layer      │
     │ (core/edge_launcher.py)│  │ (core/memory_trimmer)  │
     ├────────────────────────┤  ├────────────────────────┤
     │ • --renderer-process-  │  │ • ctypes Win32 API     │
     │   limit=8              │  │ • OpenProcess()        │
     │ • --process-per-site   │  │ • EmptyWorkingSet()    │
     │ • Tab freeze & discard │  │ • GetProcessMemoryInfo │
     │ • Desktop .lnk creator │  │ • Instant RAM flush    │
     └────────────────────────┘  └────────────────────────┘
                  │
                  ▼
     ┌────────────────────────┐
     │ 3. Kernel Layer        │
     │ (core/kernel_mmagent)  │
     ├────────────────────────┤
     │ • PowerShell Interop   │
     │ • MemoryCompression    │
     │ • PageCombining (dedup)│
     │ • UAC RunAs Activation │
     └────────────────────────┘
```

### 1. Chromium Core Process Limiting (`core/edge_launcher.py`)
- Auto-discovers `msedge.exe` across standard 64-bit and 32-bit Program Files, Local AppData, and Windows Registry App Paths.
- Spawns Edge with process consolidation flags:
  `--renderer-process-limit=8 --process-per-site --enable-features=FreezeIndividualSubframes,AutomaticTabDiscarding`
- Caps maximum renderer process instances to 8 (instead of spawning dozens of individual processes for every tab), dramatically reducing total system thread overhead.
- Inspects active `msedge.exe` processes via `psutil` to verify whether process limitation flags are actively engaged.
- Provides a Windows Script Host COM (`WScript.Shell`) helper to create a persistent desktop shortcut: `"Edge (Optimized RAM).lnk"`.

### 2. Win32 Working Set Trimming (`core/memory_trimmer.py`)
- Pure Python `ctypes` bindings for `kernel32.dll` and `psapi.dll`:
  - `OpenProcess(PROCESS_SET_QUOTA | PROCESS_QUERY_INFORMATION, False, pid)`
  - `psapi.EmptyWorkingSet(hProcess)`
  - `psapi.GetProcessMemoryInfo(hProcess, byref(pmc), sizeof(pmc))` with `PROCESS_MEMORY_COUNTERS`
  - `CloseHandle(hProcess)`
- Traverses all `msedge.exe` processes, flushes unneeded physical pages into the Windows standby list, and calculates the exact delta of reclaimed RAM (often freeing **1 to 3+ GB** instantly).
- Non-destructive: Does not kill renderer threads or disrupt active sessions.

### 3. Windows Kernel Optimization (`core/kernel_mmagent.py`)
- Queries Windows Memory Manager Agent (`Get-MMAgent`) for in-memory compression (`MemoryCompression`) and page deduplication (`PageCombining`).
- Provides 1-click elevation via `Start-Process powershell -Verb RunAs -ArgumentList 'Enable-MMAgent -MemoryCompression -PageCombining'` to activate kernel memory compression and page combining.

### 4. Background System Tray Daemon & GUI Dashboard (`main.py`)
- **System Tray (`pystray` + `PIL`):**
  - Live header with current Edge RAM and process count.
  - `⚡ Purge RAM Now`: Instant one-click flush.
  - `🚀 Launch Optimized Edge`: Starts Edge with low-RAM flags.
  - `⏱️ Auto-Purge Loop (30s)`: Background worker thread toggled on/off.
  - `🖥️ Open Dashboard`: Restores CustomTkinter GUI.
  - `❌ Exit`: Clean thread termination and shutdown.
- **CustomTkinter GUI:**
  - Modern dark-mode layout with real-time physical RAM vs. commit memory indicators.
  - Live purge feedback delta (`Freed X MB across N processes`).
  - Kernel optimization badges (`Memory Compression: ON`, `Page Combining: ON`).
  - Window minimize-to-tray behavior on close (`WM_DELETE_WINDOW`).

---

## 📁 File Structure

```
edge-ram-optimizer/
├── main.py                  # CustomTkinter dashboard & pystray system-tray daemon
├── core/
│   ├── __init__.py          # Core package exports
│   ├── memory_trimmer.py    # ctypes Win32 EmptyWorkingSet & process memory metrics
│   ├── edge_launcher.py     # Edge executable discovery, CLI flags, & shortcut builder
│   └── kernel_mmagent.py    # Windows Kernel MMAgent compression & combining interop
├── requirements.txt         # Dependency declarations (psutil, pystray, pillow, customtkinter, pywin32)
├── build.bat                # PyInstaller single portable EXE build script
├── icon.png                 # Application tray and window icon
├── icon.ico                 # Multi-resolution Windows executable icon
└── README.md                # Technical guide & documentation
```

---

## 🚀 Getting Started

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Run the Application
```bash
python main.py
```

### 3. Build Portable Standalone EXE
Run `build.bat` or execute:
```cmd
pyinstaller --noconsole --onefile --icon=icon.ico --name="EdgeRAM-Optimizer" --collect-all customtkinter main.py
```
The standalone executable will be output to `dist\EdgeRAM-Optimizer.exe`.
