"""Native Windows notification for GravityGuard approval tickets: Allow / Deny buttons right in the toast.

Needs the `windows-toasts` package. `--install` creates a private venv at ~/.gravityguard/notifier-venv, installs it
there and adds a login launcher to the Startup folder; `--uninstall` removes the launcher.

The toast buttons call back into this running process (no URL scheme, no extra command), and the decision goes through
`engine/approval_control.py`, the same trusted path as the panel. Another program cannot answer for the user because
nothing outside this process listens for the click.
"""
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ENGINE = Path(__file__).resolve().parent.parent / "engine"
sys.path.insert(0, str(ENGINE))

from gravityguard_engine import approvals as apr
import approval_control as control

POLL_SECONDS = 1.5
VENV = Path.home() / ".gravityguard" / "notifier-venv"
STARTUP = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
LAUNCHER = STARTUP / "GravityGuardApprovals.vbs"
CHOICE = re.compile(r"^(allow|deny):([0-9a-f]{16})$")


def build_toast(ticket: dict, on_click):
    from windows_toasts import Toast, ToastButton, ToastScenario
    action = ticket.get("action") or {}
    what = (action.get("command") or action.get("target") or "?")[:160]
    toast = Toast(
        [f"GravityGuard: {ticket.get('rule', '?')} ({action.get('tool', '?')})", what, str(ticket.get("reason", ""))[:200]],
        scenario=ToastScenario.Reminder,  # stays on screen until the user answers
        group="gravityguard-approvals",
    )
    toast.AddAction(ToastButton("İzin ver (30 dk, 1 kez)", f"allow:{ticket['id']}"))
    toast.AddAction(ToastButton("Reddet", f"deny:{ticket['id']}"))
    toast.on_activated = on_click
    return toast


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


def run() -> None:
    from windows_toasts import InteractableWindowsToaster
    toaster = InteractableWindowsToaster("GravityGuard")
    shown = {}
    while True:
        pending = {t["id"]: t for t in apr.list_pending()}
        for ticket_id, ticket in pending.items():
            if ticket_id not in shown:
                shown[ticket_id] = build_toast(ticket, lambda args: answer(args.arguments))
                toaster.show_toast(shown[ticket_id])
        for ticket_id, toast in list(shown.items()):
            if toast is not None and ticket_id not in pending:  # decided in the panel, a toast or the terminal
                toaster.remove_toast(toast)
                shown[ticket_id] = None
        time.sleep(POLL_SECONDS)


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
