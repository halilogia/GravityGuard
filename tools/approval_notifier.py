"""Windows heads-up for GravityGuard approval tickets: a plain toast + beep, and an always-on-top Allow / Deny window.

Needs the `windows-toasts` package (and tkinter). `--install` creates a private venv at ~/.gravityguard/notifier-venv,
installs it there and adds a login launcher to the Startup folder; `--uninstall` removes the launcher.

Toast buttons are not used: click routing needs an app identity registered with Windows (Start shortcut + COM
activator), and the borrowed PowerShell identity sends the click elsewhere. The window's buttons run in this process
(no URL scheme), and the decision goes through `engine/approval_control.py`, the same trusted path as the panel.
Another program cannot answer for the user because nothing outside this process listens for the click.
"""
import os
import re
import subprocess
import sys
from pathlib import Path

ENGINE = Path(__file__).resolve().parent.parent / "engine"
sys.path.insert(0, str(ENGINE))

import approval_control as control
from gravityguard_engine import approvals as apr

POLL_SECONDS = 1.5
VENV = Path.home() / ".gravityguard" / "notifier-venv"
STARTUP = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
LAUNCHER = STARTUP / "GravityGuardApprovals.vbs"
CHOICE = re.compile(r"^(allow|deny):([0-9a-f]{16})$")


def answer(arguments: str) -> str:
    """Apply a button press. Returns a short result for the log line; only well-formed button arguments count."""
    match = CHOICE.match(arguments or "")
    if not match:
        return "ignored"
    action, ticket_id = match.groups()
    try:
        control.handle({"action": action, "id": ticket_id})
    except apr.ApprovalError as exc:
        return f"not applied: {exc}"
    return action


# PowerShell's system identity: the one Claude Code's own "done" toast (notify-done.ps1) is known to show with.
# The library default (Command Prompt) and an unregistered custom id were both silently dropped on this machine.
AUMID = r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"


def announce(toaster, ticket: dict) -> None:
    """Plain toast + beep: the heads-up. Toast buttons are not used (click routing needs a registered app identity)."""
    import winsound

    from windows_toasts import Toast
    action = ticket.get("action") or {}
    what = (action.get("command") or action.get("target") or "?")[:160]
    try:
        toaster.show_toast(Toast([f"GravityGuard onay bekliyor: {ticket.get('rule', '?')}", what]))
        winsound.Beep(660, 200)
        winsound.Beep(880, 200)
    except Exception as exc:  # noqa: BLE001 - WinRT raises many types; logged, and the popup still shows
        print(f"toast failed: {exc}", file=sys.stderr)


def open_popup(root, ticket: dict):
    """Always-on-top window, bottom right, two big buttons. The click goes through `answer` (trusted engine path)."""
    import tkinter as tk
    action = ticket.get("action") or {}
    what = (action.get("command") or action.get("target") or "?")[:300]
    win = tk.Toplevel(root)
    win.title("GravityGuard onay")
    win.attributes("-topmost", True)
    win.configure(bg="#1f1f24", padx=18, pady=14)
    win.resizable(False, False)
    tk.Label(win, text=f"{ticket.get('rule', '?')}  ({action.get('tool', '?')})", fg="#ffb454", bg="#1f1f24",
             font=("Segoe UI", 11, "bold"), anchor="w").pack(fill="x")
    tk.Label(win, text=what, fg="#e6e6e6", bg="#1f1f24", font=("Consolas", 10), wraplength=440, justify="left",
             anchor="w").pack(fill="x", pady=(6, 4))
    tk.Label(win, text=str(ticket.get("reason", ""))[:220], fg="#9a9aa5", bg="#1f1f24", font=("Segoe UI", 9),
             wraplength=440, justify="left", anchor="w").pack(fill="x", pady=(0, 12))
    row = tk.Frame(win, bg="#1f1f24")
    row.pack(fill="x")

    def decide(choice: str):
        ticket_id = ticket["id"]
        print(f"{choice} {ticket_id}: {answer(f'{choice}:{ticket_id}')}", file=sys.stderr)
        win.destroy()

    for label, choice, color in (("İzin ver (30 dk, 1 kez)", "allow", "#2e7d32"), ("Reddet", "deny", "#8e2b2b")):
        tk.Button(row, text=label, command=lambda c=choice: decide(c), bg=color, fg="white", relief="flat",
                  font=("Segoe UI", 10, "bold"), padx=14, pady=8, cursor="hand2").pack(side="left", expand=True,
                                                                                         fill="x", padx=4)
    win.update_idletasks()
    slot = (len(root.children) - 1) % 4  # stack up to four windows instead of covering each other
    x = win.winfo_screenwidth() - win.winfo_width() - 24
    y = win.winfo_screenheight() - win.winfo_height() - 72 - slot * (win.winfo_height() + 8)
    win.geometry(f"+{x}+{max(24, y)}")
    return win


def run() -> None:
    import tkinter as tk

    from windows_toasts import WindowsToaster
    toaster = WindowsToaster(AUMID)
    root = tk.Tk()
    root.withdraw()
    shown: dict = {}

    def tick():
        pending = {t["id"]: t for t in apr.list_pending()}
        for ticket_id, ticket in pending.items():
            if ticket_id not in shown:
                announce(toaster, ticket)
                shown[ticket_id] = open_popup(root, ticket)
        for ticket_id, win in list(shown.items()):
            if win is not None and ticket_id not in pending:  # decided here, in the panel or the IDE notification
                if win.winfo_exists():
                    win.destroy()
                shown[ticket_id] = None
        root.after(int(POLL_SECONDS * 1000), tick)

    tick()
    root.mainloop()


def install() -> None:
    if not (VENV / "Scripts" / "pythonw.exe").exists():
        subprocess.run([sys.executable, "-m", "venv", str(VENV)], check=True)
        subprocess.run([str(VENV / "Scripts" / "python.exe"), "-m", "pip", "install", "-q", "windows-toasts"], check=True)
    pythonw = VENV / "Scripts" / "pythonw.exe"
    script = Path(__file__).resolve()
    LAUNCHER.write_text(f'CreateObject("WScript.Shell").Run """{pythonw}"" ""{script}""", 0, False\n', encoding="utf-8")
    print(f"Girişte otomatik başlar: {LAUNCHER}")


def uninstall() -> None:
    LAUNCHER.unlink(missing_ok=True)
    print("Otomatik başlatma kaldırıldı.")


if __name__ == "__main__":
    flag = sys.argv[1] if len(sys.argv) > 1 else ""
    {"--install": install, "--uninstall": uninstall}.get(flag, run)()
