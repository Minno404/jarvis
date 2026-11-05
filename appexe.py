"""Jarvis.exe: Jarvis's own program file, so Task Manager and the taskbar show "Jarvis" with his icon instead of
Python. Jarvis.bat runs this and uses the NAME=value lines it prints.

Jarvis.exe is compiled once with the C# compiler built into Windows (.NET Framework) and runs Python inside
itself (through Python's own DLL), so Jarvis's window really belongs to Jarvis.exe. Works with any Python,
including the Microsoft Store one (whose files other programs aren't allowed to load, so Jarvis keeps his own
copy of that Python in pyruntime/). It's tested before it's used: if anything fails, Jarvis starts with pythonw
as before, and the reason is in jarvis_exe.log.
"""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXE, ICO, STAMP = HERE / "Jarvis.exe", HERE / "jarvis.ico", HERE / "jarvis_exe.json"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
SOURCE = r"""
using System; using System.Reflection; using System.Runtime.InteropServices;
[assembly: AssemblyTitle("Jarvis")] [assembly: AssemblyProduct("Jarvis")]
class Jarvis {
  [DllImport("kernel32", CharSet=CharSet.Unicode)] static extern bool SetDllDirectory(string d);
  [DllImport("kernel32", CharSet=CharSet.Unicode)] static extern IntPtr LoadLibrary(string f);
  [DllImport("PYDLL", CharSet=CharSet.Unicode, CallingConvention=CallingConvention.Cdecl)]
  static extern int Py_Main(int argc, [MarshalAs(UnmanagedType.LPArray, ArraySubType=UnmanagedType.LPWStr)] string[] argv);
  [STAThread] static int Main(string[] args) {
    var home = Environment.GetEnvironmentVariable("PYTHONHOME");
    SetDllDirectory(home);
    LoadLibrary(System.IO.Path.Combine(home, "PYDLL"));
    var argv = new string[args.Length + 1];
    argv[0] = Assembly.GetEntryAssembly().Location; args.CopyTo(argv, 1);
    return Py_Main(argv.Length, argv);
  }
}
"""


def csc():
    root = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET"
    found = sorted(root.glob("Framework64/v4*/csc.exe"))
    return found[-1] if found else None


RUNTIME = HERE / "pyruntime"


def home():
    """Python's home folder for Jarvis.exe. The Microsoft Store Python lives where only its own programs may load
    it from, so that one is copied into pyruntime/ (the standard library, its DLLs and Tcl for the mini core)."""
    base = Path(sys.base_prefix)
    if "windowsapps" not in str(base).lower():
        return base
    stamp = RUNTIME / "version.txt"
    if not (stamp.exists() and stamp.read_text() == sys.version):
        shutil.rmtree(RUNTIME, ignore_errors=True)
        skip = shutil.ignore_patterns("__pycache__", "test", "tests", "idle_test", "site-packages", "*.exe",
                                      "AppxManifest.xml", "AppxSignature.p7x", "AppxBlockMap.xml", "AppxMetadata")
        shutil.copytree(base, RUNTIME, ignore=skip)
        stamp.write_text(sys.version)
    return RUNTIME


def env():
    """What Jarvis.exe needs to find Python: its home folder, and where the packages (pywebview...) live."""
    import webview
    return {"PYTHONHOME": str(home()), "PYTHONPATH": str(Path(webview.__file__).resolve().parents[1])}


def build():
    e = env()
    dll = f"python{sys.version_info.major}{sys.version_info.minor}.dll"
    want = {**e, "python": sys.version, "icon": ICO.stat().st_mtime, "source": SOURCE}
    if EXE.exists() and STAMP.exists() and json.loads(STAMP.read_text()) == want:
        return e
    failed = HERE / "jarvis_exe_failed.json"  # don't retry a failed build on every launch, only after a change
    if failed.exists() and json.loads(failed.read_text()) == want:
        raise RuntimeError("it failed before with this Python (see jarvis_exe.log)")
    STAMP.unlink(missing_ok=True)
    compiler = csc()
    if not compiler:
        raise RuntimeError("no 64-bit .NET Framework C# compiler")
    src = HERE / "jarvis_exe.cs"
    src.write_text(SOURCE.replace("PYDLL", dll), encoding="utf-8")
    try:
        subprocess.run([str(compiler), "/nologo", "/target:winexe", "/platform:x64", f"/win32icon:{ICO}",
                        f"/out:{EXE}", str(src)], check=True, timeout=60, creationflags=NO_WINDOW, capture_output=True)
    finally:
        src.unlink(missing_ok=True)
    # it must really run Jarvis (pywebview and .NET inside it) before Jarvis.bat trusts it
    check = HERE / "jarvis_exe_check.txt"
    check.unlink(missing_ok=True)
    r = subprocess.run([str(EXE), "-c", f"import webview, clr, tkinter, sys; open({str(check)!r}, 'w').write(sys.version)"],
                       env={**os.environ, **e}, timeout=90, creationflags=NO_WINDOW, capture_output=True, text=True)
    ok = check.exists() and check.read_text() == sys.version
    check.unlink(missing_ok=True)
    if not ok:
        failed.write_text(json.dumps(want))
        raise RuntimeError(f"Jarvis.exe didn't pass its check (exit {r.returncode}): {(r.stderr or r.stdout)[-600:]}")
    STAMP.write_text(json.dumps(want))
    return e


def quick():
    """At Windows log-on: if Jarvis.exe is already built for this Python, its settings straight from the stamp
    (no need to load pywebview just to find them)."""
    try:
        st = json.loads(STAMP.read_text())
        if EXE.exists() and st.get("python") == sys.version and st.get("source") == SOURCE \
                and st.get("icon") == ICO.stat().st_mtime:
            return {k: st[k] for k in ("PYTHONHOME", "PYTHONPATH")}
    except (OSError, ValueError, KeyError):
        pass
    return None


if __name__ == "__main__":
    try:
        for k, v in (quick() or build()).items():
            print(f"{k}={v}")
        print(f"JEXE={EXE}")
    except Exception as e:
        print("Jarvis.exe unavailable, using pythonw:", repr(e), file=sys.stderr)
        if "failed before" not in str(e):
            (HERE / "jarvis_exe.log").write_text(f"{time.ctime()}: {e!r}\n", encoding="utf-8")
        print("JEXE=pythonw")
