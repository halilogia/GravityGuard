"""Windows heads-up for GravityGuard approval tickets: a plain toast + beep, and a premium always-on-top Allow / Deny HUD.

Needs the `windows-toasts` package (and tkinter). `--install` creates a private venv at ~/.gravityguard/notifier-venv,
installs it there and adds a login launcher to the Startup folder; `--uninstall` removes the launcher.

Toast buttons are not used: click routing needs an app identity registered with Windows (Start shortcut + COM
activator), and the borrowed PowerShell identity sends the click elsewhere. The window's buttons run in this process
(no URL scheme), and the decision goes through `engine/approval_control.py`, the same trusted path as the panel.
Another program cannot answer for the user because nothing outside this process listens for the click.
"""
import ctypes
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

# Palette — Obsidian Dark Minimalist HUD
BG_OUTER = "#232d3f"
BG_CARD = "#0b0f19"
BG_SURFACE = "#111827"
BG_CODE = "#060911"
BORDER_CODE = "#1e293b"
ACCENT_AMBER = "#f59e0b"
ACCENT_CYAN = "#38bdf8"
TEXT_MAIN = "#f8fafc"
TEXT_BODY = "#cbd5e1"
TEXT_MUTED = "#64748b"
BTN_ALLOW = "#10b981"
BTN_ALLOW_HOVER = "#059669"
BTN_DENY = "#1e293b"
BTN_DENY_HOVER = "#dc2626"


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


def _clean_reason(raw: str, rule: str) -> str:
    """Strip noisy rule prefixes, leading stop symbols, and trailing ticket footer hints."""
    text = str(raw or "").strip()
    text = re.sub(r"^[\U0001f6d1\u26a0\ufe0f\s]+", "", text)
    if rule:
        text = re.sub(rf"^\[{re.escape(rule)}\]\s*:?\s*", "", text)
    text = re.sub(r"^\[[A-Z0-9_]+\]\s*:?\s*", "", text)
    text = text.split("\n\nBu eylemi bir kez")[0].split("\nOnay:")[0].split(" (Onay bileti:")[0].strip()
    return text[:260]


def _apply_win11_chrome(win) -> None:
    """Enable Windows 11 DWM native rounded corners and dark border on a frameless Toplevel."""
    if sys.platform != "win32":
        return
    try:
        win.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id()) or win.winfo_id()
        dwmapi = ctypes.windll.dwmapi
        corner_pref = ctypes.c_int(2)  # DWMWCP_ROUND
        dwmapi.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(corner_pref), ctypes.sizeof(corner_pref))
        dark_mode = ctypes.c_int(1)
        dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(dark_mode), ctypes.sizeof(dark_mode))
    except (OSError, AttributeError, ValueError) as exc:
        print(f"dwm chrome skipped: {exc}", file=sys.stderr)


def announce(toaster, ticket: dict) -> None:
    """Plain toast + beep: the heads-up. Toast buttons are not used (click routing needs a registered app identity)."""
    import winsound

    from windows_toasts import Toast
    action = ticket.get("action") or {}
    what = (action.get("command") or action.get("target") or "?")[:160]
    try:
        toaster.show_toast(Toast([f"GravityGuard onay bekliyor: {ticket.get('rule', '?')}", what]))
        winsound.Beep(660, 160)
        winsound.Beep(880, 160)
    except Exception as exc:  # noqa: BLE001 - WinRT raises many types; logged, and the popup still shows
        print(f"toast failed: {exc}", file=sys.stderr)


def open_popup(root, ticket: dict):
    """Frameless, always-on-top security card at bottom-right. Decision routes through `answer`."""
    import tkinter as tk
    action = ticket.get("action") or {}
    rule = str(ticket.get("rule") or "RULE")
    tool = str(action.get("tool") or "tool")
    what = str(action.get("command") or action.get("target") or "?")[:320]
    reason = _clean_reason(ticket.get("reason", ""), rule)
    ticket_id = str(ticket.get("id") or "")

    win = tk.Toplevel(root)
    win.title("GravityGuard Onay")
    win.overrideredirect(True)
    win.attributes("-topmost", True)
    win.configure(bg=BG_OUTER, padx=1, pady=1)
    win.resizable(False, False)

    # Top accent hairline
    tk.Frame(win, bg=ACCENT_AMBER, height=2).pack(fill="x")

    card = tk.Frame(win, bg=BG_CARD, padx=18, pady=15, width=460)
    card.pack(fill="both", expand=True)

    # Header bar (draggable)
    hdr = tk.Frame(card, bg=BG_CARD, cursor="fleur")
    hdr.pack(fill="x", pady=(0, 10))
    brand = tk.Label(hdr, text="GRAVITYGUARD", fg=ACCENT_CYAN, bg=BG_CARD, font=("Segoe UI Semibold", 8))
    brand.pack(side="left")
    badge = tk.Label(hdr, text="ONAY BEKLİYOR", fg=ACCENT_AMBER, bg="#261b07",
                     font=("Segoe UI", 8, "bold"), padx=7, pady=1)
    badge.pack(side="left", padx=(8, 0))

    close_btn = tk.Label(hdr, text="×", fg=TEXT_MUTED, bg=BG_CARD, font=("Segoe UI", 12, "bold"), padx=4, cursor="hand2")
    close_btn.pack(side="right")
    close_btn.bind("<Enter>", lambda _e: close_btn.configure(fg=TEXT_MAIN))
    close_btn.bind("<Leave>", lambda _e: close_btn.configure(fg=TEXT_MUTED))
    close_btn.bind("<ButtonRelease-1>", lambda _e: win.destroy())

    drag = {"x": 0, "y": 0}
    for w in (hdr, brand, badge):
        w.bind("<ButtonPress-1>", lambda e: drag.update(x=e.x_root - win.winfo_x(), y=e.y_root - win.winfo_y()))
        w.bind("<B1-Motion>", lambda e: win.geometry(f"+{e.x_root - drag['x']}+{e.y_root - drag['y']}"))

    # Rule title + tool pill row
    title_row = tk.Frame(card, bg=BG_CARD)
    title_row.pack(fill="x", pady=(0, 10))
    tk.Label(title_row, text=rule, fg=TEXT_MAIN, bg=BG_CARD, font=("Segoe UI", 11, "bold"), anchor="w").pack(side="left")
    tk.Label(title_row, text=tool, fg=ACCENT_CYAN, bg=BG_SURFACE, font=("Consolas", 9, "bold"),
             padx=8, pady=2).pack(side="right")

    # Recessed terminal box for command / target path
    code_border = tk.Frame(card, bg=BORDER_CODE, padx=1, pady=1)
    code_border.pack(fill="x", pady=(0, 10))
    code_box = tk.Frame(code_border, bg=BG_CODE, padx=11, pady=8)
    code_box.pack(fill="x")
    tk.Label(code_box, text="KOMUT / HEDEF", fg=TEXT_MUTED, bg=BG_CODE,
             font=("Segoe UI", 7, "bold"), anchor="w").pack(fill="x", pady=(0, 3))
    tk.Label(code_box, text=what, fg=TEXT_MAIN, bg=BG_CODE, font=("Consolas", 9),
             wraplength=418, justify="left", anchor="w").pack(fill="x")

    # Clean explanation text
    if reason:
        tk.Label(card, text=reason, fg=TEXT_BODY, bg=BG_CARD, font=("Segoe UI", 9),
                 wraplength=424, justify="left", anchor="w").pack(fill="x", pady=(0, 14))

    # Action buttons row
    row = tk.Frame(card, bg=BG_CARD)
    row.pack(fill="x")

    def decide(choice: str):
        print(f"{choice} {ticket_id}: {answer(f'{choice}:{ticket_id}')}", file=sys.stderr)
        win.destroy()

    allow_btn = tk.Button(
        row, text="Bir Kez İzin Ver (30 dk)", command=lambda: decide("allow"),
        bg=BTN_ALLOW, fg="#042f2e", activebackground=BTN_ALLOW_HOVER, activeforeground="#ffffff",
        relief="flat", bd=0, highlightthickness=0, font=("Segoe UI", 9, "bold"),
        padx=14, pady=8, cursor="hand2",
    )
    allow_btn.pack(side="left", expand=True, fill="x", padx=(0, 6))
    allow_btn.bind("<Enter>", lambda _e: allow_btn.configure(bg=BTN_ALLOW_HOVER, fg="#ffffff"))
    allow_btn.bind("<Leave>", lambda _e: allow_btn.configure(bg=BTN_ALLOW, fg="#042f2e"))

    deny_btn = tk.Button(
        row, text="Reddet", command=lambda: decide("deny"),
        bg=BTN_DENY, fg=TEXT_BODY, activebackground=BTN_DENY_HOVER, activeforeground="#ffffff",
        relief="flat", bd=0, highlightthickness=0, font=("Segoe UI", 9, "bold"),
        padx=14, pady=8, cursor="hand2",
    )
    deny_btn.pack(side="left", fill="x")
    deny_btn.bind("<Enter>", lambda _e: deny_btn.configure(bg=BTN_DENY_HOVER, fg="#ffffff"))
    deny_btn.bind("<Leave>", lambda _e: deny_btn.configure(bg=BTN_DENY, fg=TEXT_BODY))

    win.bind("<Escape>", lambda _e: win.destroy())
    _apply_win11_chrome(win)
    win.update_idletasks()
    slot = (len(root.children) - 1) % 4  # stack up to four windows instead of covering each other
    width = max(462, win.winfo_reqwidth())
    height = win.winfo_reqheight()
    x = win.winfo_screenwidth() - width - 24
    y = win.winfo_screenheight() - height - 68 - slot * (height + 10)
    win.geometry(f"{width}x{height}+{x}+{max(24, y)}")
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


def preview() -> None:
    """Render a live preview of the approval popup and save a screenshot to screenshots/approval_popup_preview.png."""
    import tkinter as tk
    from PIL import ImageGrab
    default_out = Path(__file__).resolve().parent.parent / "screenshots" / "approval_popup_preview.png"
    out = Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else default_out
    out.parent.mkdir(parents=True, exist_ok=True)
    root = tk.Tk()
    root.withdraw()
    sample = {
        "id": "0123456789abcdef",
        "rule": "ARCH_RATCHET_GROWTH_DENY",
        "reason": "Dosya 500 satır tavanını aştığı için doğrudan büyütme reddedildi; yeni sorumluluğu alt modüle ayırın.",
        "action": {"tool": "edit_file", "target": "engine/gravityguard_engine/dispatcher.py"},
    }
    win = open_popup(root, sample)
    win.update()

    def capture() -> None:
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id()) or win.winfo_id()
        img = ImageGrab.grab(window=hwnd)
        img.save(str(out))
        root.destroy()

    root.after(250, capture)
    root.mainloop()
    print(f"Preview saved: {out}")


if __name__ == "__main__":
    flag = sys.argv[1] if len(sys.argv) > 1 else ""
    {"--install": install, "--uninstall": uninstall, "--preview": preview}.get(flag, run)()
