"""GravityGuard command line for the user (trusted side).

    gravityguard hooks list                 pending hook proposals and installed ones
    gravityguard hooks show <id>            rationale, test command and diff of one proposal
    gravityguard hooks approve <id>         review the diff, type the id to install it
    gravityguard hooks reject <id> [-r ..]  drop a proposal, keeping a receipt
    gravityguard hooks revert <id>          remove a hook an approval installed
    gravityguard gate run tests -- <command>
                                            run the command, record pass/fail from its exit code
    gravityguard gate show                  print the recorded verification stages
    gravityguard approvals list             operations a rule blocked, waiting for the user's decision
    gravityguard approvals show <id>        what was blocked, which rule, how long the ticket lives
    gravityguard approvals allow <id>       lift the block for that one exact action (type the id)
    gravityguard approvals deny <id>        keep the block, keeping a receipt
    gravityguard approvals revoke <id>      withdraw a live approval before it is spent

`approve`, `revert`, `allow`, `deny` and `revoke` ask for confirmation on an interactive terminal; an agent's shell
has none, and GravityGuard's shell rule denies agents these commands as well (POLICY_INTEGRITY).
"""
import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gravityguard_engine import approvals as apr
from gravityguard_engine import hook_proposals as hp
from gravityguard_engine import pause_switch as ps
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


def _debt(args) -> int:
    from gravityguard_engine import debt_ratchet
    root = str(Path(args.root).resolve())
    if args.scan:
        print(f"{debt_ratchet.scan_project(root, threshold=args.threshold)} kaynak dosya tarandi.")
    summary = debt_ratchet.get_project_debt_summary(root, threshold=args.threshold)
    print(f"\n== GravityGuard Teknik Borc & Ratchet Raporu ({root}) ==")
    print(f"Esik: {summary['threshold']} satir | Borclu Dosyalar: {summary['total_files_with_debt']} | Toplam Borc: {summary['total_debt_loc']} LOC | Regresyon: {summary['total_regressions']}")
    if not summary['files']:
        print("  [TEMIZ] Ratchet uzerinde kayitli asiri buyuk veya borclu dosya yok.")
        return 0
    print("\n  Dosya                                              Mevcut / Tavan   Borc   Durum")
    print("  " + "-" * 75)
    for f in summary['files']:
        status_badge = "[GUVENLI]" if f["status"] == "LOCKED" else ("[IYILESTI]" if f["status"] == "IMPROVED" else "[REGRESYON / BLOKE]")
        print(f"  {f['path']:48} {f['current_loc']:4d} / {f['baseline_loc']:4d} LOC   +{f['debt_loc']:4d}   {status_badge}")
    return 1 if summary['total_regressions'] > 0 else 0


def _gate(args) -> int:
    root = Path(args.root).resolve()
    if args.action == "run":
        command = [part for part in args.command if part != "--"]
        if args.stage not in vg.RUN_STAGES or not command:
            print("Kullanım: gravityguard gate run tests -- <komut>", file=sys.stderr)
            return 2
        entry = vg.run_stage(root, args.stage, command)
        print(f"{args.stage}: {entry['status']} ({entry['detail']})")
        return 0 if entry["status"] == "pass" else 1
    for line in vg.stage_summary(vg.load_report(root)):
        print(line)
    return 0


def _pause(args) -> int:
    if args.action == "off":
        state = ps.pause(args.minutes, args.reason)
        print(f"GravityGuard {state['minutes']} dk duraklatıldı (sır/.env koruması açık). Geri açmak: gravityguard pause on")
    elif args.action == "on":
        print("GravityGuard yeniden açıldı." if ps.resume() else "Zaten açıktı.")
    else:
        state = ps.status()
        print(f"DURAKLATILDI, {state['remaining'] // 60} dk kaldı." if state else "AÇIK.")
    return 0


def _approvals(args) -> int:
    if args.action == "list":
        pending = apr.list_pending()
        print(f"Onay bekleyen işlemler: {len(pending) or 'yok'}")
        for ticket in pending[:25]:
            action = ticket.get("action") or {}
            what = action.get("target") or action.get("command") or ""
            left = int(float(ticket.get("expires_at") or 0) - time.time()) // 60
            print(f"  {ticket['id']:18} [{ticket.get('rule')}] {action.get('tool', '')} {what}"[:160])
            print(f"  {'':18} {max(left, 0)} dk kaldı, {ticket.get('seen', 1)} kez denendi")
        if len(pending) > 25:
            print(f"  ... {len(pending) - 25} tane daha (hepsi: gravityguard approvals show <id>)")
        live = [r for r in apr.list_receipts() if r.get("status") == "approved"]
        if live:
            print("Aktif onaylar:")
            for receipt in live:
                print(f"  {receipt['id']:18} [{receipt.get('rule')}] kalan kullanım {receipt.get('remaining')}")
        return 0
    if not args.id:
        print(f"'{args.action}' bir onay kimliği ister", file=sys.stderr)
        return 2
    view = apr.preview(args.id)
    ticket = view.get("ticket") or {}
    action = ticket.get("action") or {}
    status = (view.get("receipt") or {}).get("status") or ticket.get("status")
    print(f"\n== {args.id}  ({status})")
    for label, value in (("Kural", ticket.get("rule")), ("Araç", action.get("tool")), ("Hedef", action.get("target")),
                         ("Komut", action.get("command")), ("Neden", ticket.get("reason"))):
        if value:
            print(f"  {label:8}: {value}")
    if args.action == "show":
        return 0
    if args.action == "deny":
        apr.reject(args.id, args.reason, actor="user-terminal")
        print(f"Reddedildi: {args.id}. Kural yürürlükte kalır.")
        return 0
    if not _confirm(f"{'Onaylamak' if args.action == 'allow' else 'Geri almak'} için kimliği yazın ({args.id}):",
                    args.id):
        print("Onaylanmadı; hiçbir şey değişmedi.")
        return 1
    if args.action == "allow":
        receipt = apr.approve(args.id, actor="user-terminal", minutes=args.minutes, uses=args.uses)
        print(f"Onaylandı: {receipt['remaining']} kullanım, {args.minutes} dk. "
              f"Geri almak için: gravityguard approvals revoke {args.id}")
        return 0
    apr.revoke(args.id, actor="user-terminal")
    print(f"Geri alındı: {args.id}")
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
    gate.add_argument("action", choices=("run", "show"))
    gate.add_argument("stage", nargs="?", default="")
    gate.add_argument("command", nargs=argparse.REMAINDER)
    gate.add_argument("--root", default=os.getcwd(), help="project root (default: current folder)")
    pz = sub.add_parser("pause", help="switch GravityGuard off for a while (secrets/.env stay protected)")
    pz.add_argument("action", choices=("on", "off", "status"), help="off = pause, on = resume")
    pz.add_argument("--minutes", type=int, default=ps.DEFAULT_MINUTES, help=f"pause length (max {ps.MAX_MINUTES})")
    pz.add_argument("-r", "--reason", default="")
    av = sub.add_parser("approvals", help="review the operations a rule blocked (the user decides)")
    av.add_argument("action", choices=("list", "show", "allow", "deny", "revoke"))
    av.add_argument("id", nargs="?")
    av.add_argument("--minutes", type=int, default=apr.DEFAULT_TTL_MINUTES,
                    help=f"how long the approval stays valid (max {apr.MAX_TTL_MINUTES})")
    av.add_argument("--uses", type=int, default=apr.DEFAULT_USES,
                    help=f"how many identical calls it covers (max {apr.MAX_USES})")
    av.add_argument("-r", "--reason", default="", help="reason for a denial")
    debt = sub.add_parser("debt", help="technical debt ratchet report")
    debt.add_argument("--root", default=os.getcwd(), help="project root (default: current folder)")
    debt.add_argument("--threshold", type=int, default=500, help="monolith line threshold (default: 500)")
    debt.add_argument("--scan", action="store_true", help="walk the project and register every file over the threshold")
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")
    if args.group == "pause":
        return _pause(args)
    if args.group == "approvals":
        return _approvals(args)
    if args.group == "gate":
        return _gate(args)
    if args.group == "debt":
        return _debt(args)
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
