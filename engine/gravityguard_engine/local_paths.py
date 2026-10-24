"""Yerel kullanici yolu kapisi: commit'e `C:\\Users\\<ad>\\...`, `/Users/<ad>/...`, `/home/<ad>/...` girmesini engeller.

Neden: Yerel yol kisinin kullanici adini (ve makine duzenini) herkese acik depoya tasir.
Yalnizca EKLENEN satirlar taranir; eski satirlardaki yollar, o dosyaya dokunuldu diye commit'i engellemez.

Ayar (`.gravityguard.json`, repo kokunde):
  "publication": { "localPaths": "block" | "warn" | "off", "allowLocalPaths": ["test/**", "docs/**"] }
Gecici kacis: ortam degiskeni GRAVITYGUARD_ALLOW_LOCAL_PATHS=1 ya da `git commit --no-verify`.
"""
import fnmatch
import json
import os
import re

# Windows: C:\Users\<ad>\ , C:/Users/<ad>/ , JSON/JS icinde C:\\Users\\<ad>\\
_WIN = re.compile(r"(?i)\b[A-Z]:[\\/]+(?:Users|Documents and Settings)[\\/]+([^\\/\r\n\"'`<>|:*?]+)")
_MAC = re.compile(r"(?<![\w.~-])/Users/([^/\s\"'`<>|:*?]+)/")
_LINUX = re.compile(r"(?<![\w.~-])/home/([^/\s\"'`<>|:*?]+)/")

# Gercek kisi olmayan hesaplar ve yer tutucular
_SAFE_NAMES = {
    "public", "default", "default user", "all users", "defaultuser0", "shared",
    "user", "username", "your-name", "yourname", "your_name", "name", "me", "you", "foo", "bar", "example",
    "kullanici", "kullanıcı", "ad", "runner", "ubuntu", "node", "vscode", "circleci", "build", "jenkins", "root",
}


def _is_placeholder(name: str) -> bool:
    n = name.strip().lower()
    return (not n) or n in _SAFE_NAMES or n[0] in "<%${[(" or n.endswith(">") or n.startswith("{{") or "*" in n


def find_local_paths(text: str) -> list[str]:
    """Metindeki gercek kullanici adli yollari dondurur (bulgu basina ad; yolun geri kalani yazilmaz)."""
    found: list[str] = []
    for rx, label in ((_WIN, "C:\\Users\\"), (_MAC, "/Users/"), (_LINUX, "/home/")):
        for m in rx.finditer(text):
            if not _is_placeholder(m.group(1)):
                found.append(f"{label}{m.group(1)}")
    return found


def load_policy(root: str = ".") -> dict:
    """`.gravityguard.json` -> {"mode": "block", "allow": [...]}"""
    mode, allow = "block", []
    try:
        with open(os.path.join(root, ".gravityguard.json"), encoding="utf-8") as f:
            pub = (json.load(f) or {}).get("publication") or {}
        if pub.get("localPaths") in ("block", "warn", "off"):
            mode = pub["localPaths"]
        allow = [g for g in (pub.get("allowLocalPaths") or []) if isinstance(g, str)]
    except (OSError, ValueError):
        pass
    if os.environ.get("GRAVITYGUARD_ALLOW_LOCAL_PATHS") in ("1", "true", "TRUE"):
        mode = "off"
    return {"mode": mode, "allow": allow}


def is_allowed(rel_path: str, allow: list[str]) -> bool:
    p = rel_path.replace("\\", "/")
    return any(fnmatch.fnmatch(p, g) or fnmatch.fnmatch(p, g.rstrip("/") + "/*") for g in allow)


def check_local_paths(rel_path: str, added_text: str, policy: dict) -> list[str]:
    """Bir dosyanin EKLENEN satirlari icin bulgu mesajlari (bos liste = temiz)."""
    if policy["mode"] == "off" or is_allowed(rel_path, policy["allow"]):
        return []
    names = sorted(set(find_local_paths(added_text)))
    return [f"Yerel kullanici yolu ({n}...) commit'e giriyor" for n in names]
