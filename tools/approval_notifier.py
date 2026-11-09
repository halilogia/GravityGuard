"""Windows popup for GravityGuard approval tickets: one click allows or denies, no terminal.

Run `pythonw tools/approval_notifier.py` (or `--install` once to start it at login). A new pending ticket opens a
small always-on-top window with the rule, the blocked action and two buttons. The click goes through the same trusted
entry point the panel uses (`engine/approval_control.py`); agents cannot reach it, so a click still means the user said yes.
"""
import os
import sys
import tkinter as tk
from pathlib import Path

if sys.platform == "win32":
    import winsound

ENGINE = Path(__file__).resolve().parent.parent / "engine"
sys.path.insert(0, str(ENGINE))

import approval_control as control
from gravityguard_engine import approvals as apr

POLL_MS = 1500
STARTUP = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
LAUNCHER = STARTUP / "GravityGuardApprovals.vbs"


def describe(ticket: dict) -> str:
    action = ticket.get("action") or {}
    what = action.get("command") or action.get("target") or "?"
    return f"{ticket.get('rule', '?')}  ·  {action.get('tool', '?')}\n{what[:220]}\n\n{str(ticket.get('reason', ''))[:260]}"


class Popup:
    def __init__(self, root: tk.Tk, ticket: dict, on_close) -> None:
        self.id = ticket["id"]
        self.on_close = on_close
        self.win = tk.Toplevel(root)
        self.win.title("GravityGuard onayı")
        self.win.attributes("-topmost", True)
        self.win.configure(bg="#1f1f24")
        self.win.protocol("WM_DELETE_WINDOW", self.close)
        tk.Label(self.win, text=describe(ticket), justify="left", anchor="w", wraplength=420, bg="#1f1f24",
                 fg="#e8e8ec", font=("Segoe UI", 10), padx=14, pady=12).pack(fill="x")
        self.note = tk.Label(self.win, text="", anchor="w", bg="#1f1f24", fg="#e0a050", padx=14)
        self.note.pack(fill="x")
        bar = tk.Frame(self.win, bg="#1f1f24")
        bar.pack(fill="x", padx=14, pady=(0, 12))
        for text, color, action in (("İzin ver (30 dk, 1 kez)", "#2f7d4f", "allow"), ("Reddet", "#8a3a3a", "deny")):
            tk.Button(bar, text=text, bg=color, fg="white", relief="flat", padx=10, pady=4,
                      command=lambda a=action: self.decide(a)).pack(side="left", padx=(0, 8))
        tk.Button(bar, text="Sonra", bg="#3a3a42", fg="white", relief="flat", padx=10, pady=4,
                  command=self.close).pack(side="right")
        self.win.update_idletasks()
        x = self.win.winfo_screenwidth() - self.win.winfo_width() - 24
        y = self.win.winfo_screenheight() - self.win.winfo_height() - 72
        self.win.geometry(f"+{x}+{y}")

    def decide(self, action: str) -> None:
        answer = control.handle({"action": action, "id": self.id}) if action == "deny" or self._ticket_open() else None
        if answer is None:
            self.note.config(text="Bu kayıt artık onaya açık değil.")
            return
        self.close()

    def _ticket_open(self) -> bool:
        return any(t["id"] == self.id for t in apr.list_pending())

    def close(self) -> None:
        self.win.destroy()
        self.on_close(self.id)


def run() -> None:
    root = tk.Tk()
    root.withdraw()
    shown: dict[str, Popup | None] = {}

    def forget(ticket_id: str) -> None:
        shown[ticket_id] = None

    def poll() -> None:
        pending = {t["id"]: t for t in apr.list_pending()}
        for ticket_id, ticket in pending.items():
            if ticket_id not in shown:
                shown[ticket_id] = Popup(root, ticket, forget)
                if sys.platform == "win32":
                    winsound.MessageBeep(winsound.MB_ICONASTERISK)
        for ticket_id, popup in list(shown.items()):
            if popup and ticket_id not in pending:  # decided in the panel or terminal meanwhile
                popup.close()
        root.after(POLL_MS, poll)

    poll()
    root.mainloop()


def install() -> None:
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    script = Path(__file__).resolve()
    LAUNCHER.write_text(f'CreateObject("WScript.Shell").Run """{pythonw}"" ""{script}""", 0, False\n', encoding="utf-8")
    print(f"Girişte otomatik başlar: {LAUNCHER}")


def uninstall() -> None:
    LAUNCHER.unlink(missing_ok=True)
    print("Otomatik başlatma kaldırıldı.")


if __name__ == "__main__":
    flag = sys.argv[1] if len(sys.argv) > 1 else ""
    {"--install": install, "--uninstall": uninstall}.get(flag, run)()
