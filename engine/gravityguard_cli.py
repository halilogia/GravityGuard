"""GravityGuard command line for the user (trusted side).

    gravityguard hooks list                 pending hook proposals and installed ones
    gravityguard hooks show <id>            rationale, test command and diff of one proposal
    gravityguard hooks approve <id>         review the diff, type the id to install it
    gravityguard hooks reject <id> [-r ..]  drop a proposal, keeping a receipt
    gravityguard hooks revert <id>          remove a hook an approval installed
    gravityguard gate run <compile|tests> -- <command>
                                            run the command, record pass/fail from its exit code
    gravityguard gate preview --screenshot <png> --console-errors <n>
                                            record the live preview stage
    gravityguard gate show                  print the recorded verification stages

`approve` and `revert` ask for confirmation on an interactive terminal; an agent's shell has none, and GravityGuard's
shell rule denies agents these two commands as well (POLICY_INTEGRITY).
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gravityguard_engine import hook_proposals as hp
from gravityguard_engine import verification_gate as vg


def _print_view(view: dict) -> None:
    proposal = view.get("proposal") or {}
    print(f"\n== {view['id']}  ({'geçerli' if view['valid'] else 'GEÇERSİZ'})")
    for label, key in (("Hedef", "target"), ("Olay", "event"), ("Matcher", "matcher"), ("Komut", "command"),
                       ("Test", "test"), ("Gerekçe", "rationale"), ("Şikâyet", "complaint"), ("Öneren", "created_by")):
        if isinstance(proposal, dict) and proposal.get(key):
            print(f"  {label:8}: {proposal[key]}")
    if view.get("error"):
        print(f"  Neden   : {view['error']}")
    if view.get("diff"):
        print(f"  Dosya   : {view['target_file']}\n")
        print(view["diff"])


def _confirm(prompt: str, expected: str) -> bool:
    if not sys.stdin.isatty():
        print("Bu işlem yalnızca etkileşimli bir terminalde onaylanabilir.", file=sys.stderr)
        return False
    return input(f"{prompt} ").strip() == expected


def _gate(args) -> int:
    root = Path(args.root).resolve()
    if args.action == "run":
        command = [part for part in args.command if part != "--"]
        if args.stage not in vg.RUN_STAGES or not command:
            print("Kullanım: gravityguard gate run <compile|tests> -- <komut>", file=sys.stderr)
            return 2
        entry = vg.run_stage(root, args.stage, command)
        print(f"{args.stage}: {entry['status']} ({entry['detail']})")
        return 0 if entry["status"] == "pass" else 1
    if args.action == "preview":
        if not args.screenshot or args.console_errors is None:
            print("Kullanım: gravityguard gate preview --screenshot <png> --console-errors <n>", file=sys.stderr)
            return 2
        entry = vg.record_preview(root, args.screenshot, args.console_errors)
        print(f"preview: {entry['status']} ({entry['detail']})")
        return 0 if entry["status"] == "pass" else 1
    for line in vg.stage_summary(vg.load_report(root)):
        print(line)
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="gravityguard")
    sub = parser.add_subparsers(dest="group", required=True)
    hooks = sub.add_parser("hooks", help="agent hook proposals")
    hooks.add_argument("action", choices=("list", "show", "approve", "reject", "revert"))
    hooks.add_argument("id", nargs="?")
    hooks.add_argument("--root", default=os.getcwd(), help="project root (default: current folder)")
    hooks.add_argument("-r", "--reason", default="", help="reason for a rejection")
    gate = sub.add_parser("gate", help="verification stages shown in the webview")
    gate.add_argument("action", choices=("run", "preview", "show"))
    gate.add_argument("stage", nargs="?", default="")
    gate.add_argument("command", nargs=argparse.REMAINDER)
    gate.add_argument("--root", default=os.getcwd(), help="project root (default: current folder)")
    gate.add_argument("--screenshot", default="")
    gate.add_argument("--console-errors", type=int, default=None)
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")
    if args.group == "gate":
        return _gate(args)
    root = Path(args.root).resolve()
    if args.action != "list" and not args.id:
        parser.error(f"'{args.action}' bir öneri kimliği ister")
    try:
        if args.action == "list":
            pending = hp.list_pending(root)
            print(f"Bekleyen kanca önerileri ({root}): {len(pending) or 'yok'}")
            for view in pending:
                state = "geçerli" if view["valid"] else f"GEÇERSİZ: {view.get('error')}"
                print(f"  {view['id']:32} {state}")
            installed = [r for r in hp.list_receipts(root) if r.get("status") == "installed"]
            if installed:
                print("Kurulu öneriler:")
                for receipt in installed:
                    print(f"  {receipt['id']:32} {receipt['proposal']['event']} -> {receipt['target_file']}")
        elif args.action == "show":
            _print_view(hp.preview(root, args.id))
        elif args.action == "approve":
            view = hp.preview(root, args.id)
            _print_view(view)
            if not view["valid"]:
                return 1
            if not _confirm(f"Kurmak için öneri kimliğini yazın ({args.id}):", args.id):
                print("Onaylanmadı; hiçbir şey değişmedi.")
                return 1
            receipt = hp.approve(root, args.id, view["sha256"], actor="user-terminal")
            print(f"Kuruldu: {receipt['target_file']}. Geri almak için: gravityguard hooks revert {args.id}")
        elif args.action == "reject":
            hp.reject(root, args.id, args.reason, actor="user-terminal")
            print(f"Reddedildi: {args.id}")
        else:
            if not _confirm(f"Geri almak için öneri kimliğini yazın ({args.id}):", args.id):
                print("Onaylanmadı; hiçbir şey değişmedi.")
                return 1
            receipt = hp.revert(root, args.id, actor="user-terminal")
            print(f"Geri alındı: {receipt['target_file']}")
    except FileNotFoundError:
        print(f"Öneri bulunamadı: {args.id}", file=sys.stderr)
        return 1
    except hp.ProposalError as exc:
        print(f"Reddedildi: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
