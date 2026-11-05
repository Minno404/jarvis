"""Jarvis.exe: a tiny launcher with the Jarvis name and icon, so Task Manager and the taskbar show "Jarvis"
instead of Python. Jarvis.bat runs this and starts whatever it prints.

It's compiled once with the C# compiler built into Windows (.NET Framework), and starts pythonw server.py
and waits, so Jarvis shows in Task Manager as "Jarvis" with Python grouped underneath. Works with any Python,
including the Microsoft Store one. If anything fails, it prints "pythonw" and Jarvis starts as before.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXE, ICO, STAMP = HERE / "Jarvis.exe", HERE / "jarvis.ico", HERE / "jarvis_exe.json"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
SOURCE = r"""
using System.Diagnostics; using System.Reflection;
[assembly: AssemblyTitle("Jarvis")] [assembly: AssemblyProduct("Jarvis")]
class Jarvis { static int Main() {
  var here = System.AppDomain.CurrentDomain.BaseDirectory;
  var p = Process.Start(new ProcessStartInfo(@"PYTHONW", "server.py") { WorkingDirectory = here, UseShellExecute = false });
  p.WaitForExit(); return p.ExitCode; } }
"""


def csc():
    root = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET"
    found = sorted(root.glob("Framework64/v4*/csc.exe")) + sorted(root.glob("Framework/v4*/csc.exe"))
    return found[-1] if found else None


def build():
    pyw = shutil.which("pythonw") or str(Path(sys.executable).with_name("pythonw.exe"))
    want = {"pythonw": pyw, "icon": ICO.stat().st_mtime, "source": SOURCE}
    if EXE.exists() and STAMP.exists() and json.loads(STAMP.read_text()) == want:
        return EXE
    compiler = csc()
    if not compiler:
        raise RuntimeError("no .NET Framework C# compiler")
    src = HERE / "jarvis_exe.cs"
    src.write_text(SOURCE.replace("PYTHONW", pyw.replace('"', "")), encoding="utf-8")
    try:
        subprocess.run([str(compiler), "/nologo", "/target:winexe", f"/win32icon:{ICO}", f"/out:{EXE}", str(src)],
                       check=True, timeout=60, creationflags=NO_WINDOW, capture_output=True)
    finally:
        src.unlink(missing_ok=True)
    STAMP.write_text(json.dumps(want))
    return EXE


if __name__ == "__main__":
    try:
        print(build())
    except Exception as e:
        print("Jarvis.exe unavailable, using pythonw:", repr(e), file=sys.stderr)
        print("pythonw")
