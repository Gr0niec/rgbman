"""Windows plumbing for the rgbman app: logon task, elevation, lock state, starting OpenRGB."""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
import socket
import subprocess
import sys
import tempfile
from pathlib import Path
from xml.sax.saxutils import escape

TASK = "rgbman"
NO_WINDOW = subprocess.CREATE_NO_WINDOW  # pythonw: don't flash a console for every schtasks call
ERROR_CANCELLED = 1223                   # user said no to the UAC prompt

_shell32 = ctypes.WinDLL("shell32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_wts = ctypes.WinDLL("wtsapi32")


def is_admin():
    return bool(_shell32.IsUserAnAdmin())


# ---------------------------------------------------------------- elevation
class _ShellExecuteInfo(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("fMask", wt.ULONG), ("hwnd", wt.HWND),
                ("lpVerb", wt.LPCWSTR), ("lpFile", wt.LPCWSTR), ("lpParameters", wt.LPCWSTR),
                ("lpDirectory", wt.LPCWSTR), ("nShow", ctypes.c_int), ("hInstApp", wt.HINSTANCE),
                ("lpIDList", ctypes.c_void_p), ("lpClass", wt.LPCWSTR), ("hkeyClass", wt.HKEY),
                ("dwHotKey", wt.DWORD), ("hIcon", wt.HANDLE), ("hProcess", wt.HANDLE)]


_shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(_ShellExecuteInfo)]
_kernel32.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
_kernel32.GetExitCodeProcess.argtypes = [wt.HANDLE, ctypes.POINTER(wt.DWORD)]
_kernel32.CloseHandle.argtypes = [wt.HANDLE]


def run_elevated(exe, args, cwd=None, wait=True, show=False):
    """Run exe as admin: directly if we already are, otherwise through a UAC prompt.

    Returns the exit code, or None when not waiting. Raises OSError (winerror 1223 when
    the prompt was declined)."""
    if is_admin():
        p = subprocess.Popen([exe, *args], cwd=cwd, creationflags=0 if show else NO_WINDOW)
        return p.wait() if wait else None
    sei = _ShellExecuteInfo(cbSize=ctypes.sizeof(_ShellExecuteInfo),
                            fMask=0x40 | 0x100,  # SEE_MASK_NOCLOSEPROCESS | SEE_MASK_NOASYNC
                            lpVerb="runas", lpFile=str(exe), lpParameters=subprocess.list2cmdline(args),
                            lpDirectory=cwd, nShow=1 if show else 0)
    if not _shell32.ShellExecuteExW(ctypes.byref(sei)):
        raise ctypes.WinError(ctypes.get_last_error())
    if not sei.hProcess:
        return None
    try:
        if not wait:
            return None
        _kernel32.WaitForSingleObject(sei.hProcess, 0xFFFFFFFF)
        code = wt.DWORD()
        _kernel32.GetExitCodeProcess(sei.hProcess, ctypes.byref(code))
        return code.value
    finally:
        _kernel32.CloseHandle(sei.hProcess)


# ---------------------------------------------------------------- logon task
def _task_xml(pythonw, script):
    """Logon task XML. Unlike `schtasks /SC ONLOGON` it has no 72 h time limit and keeps
    running on battery; the user is written out so a UAC prompt with other admin
    credentials still registers the task for this account."""
    user = escape(f"{os.environ.get('USERDOMAIN', '')}\\{os.environ.get('USERNAME', '')}")
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>rgbman: podświetlenie RGB w zasobniku</Description></RegistrationInfo>
  <Triggers>
    <LogonTrigger><Enabled>true</Enabled><UserId>{user}</UserId></LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{user}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>HighestAvailable</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>5</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{escape(str(pythonw))}</Command>
      <Arguments>{escape(subprocess.list2cmdline([str(script), "--hidden"]))}</Arguments>
      <WorkingDirectory>{escape(str(Path(script).parent))}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def autostart_state(script):
    """'on' = our logon task starts this app, 'legacy' = a task named rgbman runs something
    else (e.g. the old CLI `apply default`), 'off' = no task."""
    r = subprocess.run(["schtasks", "/Query", "/TN", TASK, "/XML"],
                       capture_output=True, creationflags=NO_WINDOW)
    if r.returncode:
        return "off"
    xml = r.stdout.decode("mbcs", errors="replace").lower()
    return "on" if str(script).lower() in xml and "<executiontimelimit>pt0s" in xml else "legacy"


def set_autostart(on, script):
    if not on:
        if autostart_state(script) == "off":
            return
        code = run_elevated("schtasks.exe", ["/Delete", "/TN", TASK, "/F"])
    else:
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        xml = Path(tempfile.gettempdir()) / "rgbman_task.xml"
        xml.write_text(_task_xml(pythonw, script), encoding="utf-16")
        try:
            code = run_elevated("schtasks.exe", ["/Create", "/TN", TASK, "/XML", str(xml), "/F"])
        finally:
            xml.unlink(missing_ok=True)
    if code:
        raise OSError(f"schtasks zakończył się kodem {code}")


# ---------------------------------------------------------------- lock state
class _Level1(ctypes.Structure):  # WTSINFOEX_LEVEL1_W, up to the first 8-byte field (sets alignment)
    _fields_ = [("SessionId", wt.ULONG), ("SessionState", ctypes.c_int), ("SessionFlags", wt.LONG),
                ("WinStationName", wt.WCHAR * 33), ("UserName", wt.WCHAR * 21),
                ("DomainName", wt.WCHAR * 18), ("LogonTime", ctypes.c_longlong)]


class _InfoEx(ctypes.Structure):  # WTSINFOEXW
    _fields_ = [("Level", wt.DWORD), ("Data", _Level1)]


_wts.WTSQuerySessionInformationW.argtypes = [wt.HANDLE, wt.DWORD, ctypes.c_int,
                                             ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wt.DWORD)]
_wts.WTSFreeMemory.argtypes = [ctypes.c_void_p]


def screen_locked():
    buf, size = ctypes.c_void_p(), wt.DWORD()
    # current server, current session, WTSSessionInfoEx
    if not _wts.WTSQuerySessionInformationW(None, 0xFFFFFFFF, 25, ctypes.byref(buf), ctypes.byref(size)):
        return False
    try:
        return ctypes.cast(buf, ctypes.POINTER(_InfoEx)).contents.Data.SessionFlags == 0  # WTS_SESSIONSTATE_LOCK
    finally:
        _wts.WTSFreeMemory(buf)


# ---------------------------------------------------------------- OpenRGB
def find_openrgb():
    for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"),
                 os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs")):
        if base and (p := Path(base, "OpenRGB", "OpenRGB.exe")).exists():
            return str(p)
    return ""


def port_open(host, port):
    try:
        socket.create_connection((host, port), timeout=0.5).close()
        return True
    except OSError:
        return False


def process_running(image):
    r = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {image}", "/NH", "/FO", "CSV"],
                       capture_output=True, creationflags=NO_WINDOW)
    return f'"{image.lower()}"' in r.stdout.decode("mbcs", errors="replace").lower()


def shutting_down():
    """True while Windows is signing out / shutting down (SM_SHUTTINGDOWN)."""
    return bool(ctypes.windll.user32.GetSystemMetrics(0x2000))


def start_openrgb(path):
    """Start OpenRGB with its SDK server, minimized to the tray. Raises OSError with a
    message for the panel when that can't be done."""
    if not path or not Path(path).is_file():
        raise OSError("nie znaleziono OpenRGB.exe, wskaż ścieżkę w ustawieniach")
    run_elevated(path, ["--server", "--startminimized"], cwd=str(Path(path).parent), wait=False, show=True)
