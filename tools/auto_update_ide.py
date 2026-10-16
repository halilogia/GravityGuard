import os
import sys
import shutil
import json
import time
import subprocess
from pathlib import Path

# Ensure UTF-8 output
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

repo_root = Path(__file__).resolve().parent.parent
package_json_path = repo_root / 'package.json'

with open(package_json_path, 'r', encoding='utf-8') as f:
    pkg = json.load(f)

version = pkg.get('version', '1.4.16')
extension_id = f"halilogia.gravityguard-{version}"

print(f"🚀 [GravityGuard Auto-Updater] Deploying v{version} to IDE...")

# 1. Compile TypeScript
print("🔨 1/4 TypeScript derleniyor (npm run build)...")
build_res = subprocess.run(['npm.cmd' if os.name == 'nt' else 'npm', 'run', 'build'], cwd=str(repo_root), capture_output=True, text=True)
if build_res.returncode != 0:
    print(f"❌ Derleme hatası:\n{build_res.stderr}")
    sys.exit(1)
print("✔ Derleme başarılı.")

# 2. Deploy to .antigravity-ide/extensions
home = Path.home()
targets = [
    home / '.antigravity-ide' / 'extensions',
    home / '.vscode' / 'extensions'
]

files_to_copy = [
    ('dist', True),
    ('media', True),
    ('engine', True),
    ('package.json', False),
    ('.gravityguard.json', False),
    ('README.md', False),
    ('LICENSE.txt', False)
]

for ext_dir in targets:
    if not ext_dir.parent.exists():
        continue
    ext_dir.mkdir(parents=True, exist_ok=True)
    target_install = ext_dir / extension_id

    # Clean old versions
    for item in ext_dir.iterdir():
        if item.is_dir() and item.name.startswith('halilogia.gravityguard-') and item.name != extension_id:
            try:
                shutil.rmtree(item, ignore_errors=True)
                print(f"🧹 Eski sürüm silindi: {item.name}")
            except Exception as e:
                print(f"⚠️ Eski sürüm silinemedi ({item.name}): {e}")

    # Copy new version
    target_install.mkdir(parents=True, exist_ok=True)
    for src_rel, is_dir in files_to_copy:
        src_path = repo_root / src_rel
        dest_path = target_install / src_rel
        if not src_path.exists():
            continue
        if is_dir:
            if dest_path.exists():
                shutil.rmtree(dest_path, ignore_errors=True)
            shutil.copytree(src_path, dest_path)
        else:
            shutil.copy2(src_path, dest_path)

    # Update extensions.json
    ext_json = ext_dir / 'extensions.json'
    if ext_json.exists():
        try:
            with open(ext_json, 'r', encoding='utf-8') as f:
                extensions = json.load(f)
            extensions = [e for e in extensions if e.get('identifier', {}).get('id') != 'halilogia.gravityguard']
            extensions.append({
                'identifier': {'id': 'halilogia.gravityguard'},
                'version': version,
                'location': {
                    '$mid': 1,
                    'fsPath': str(target_install),
                    '_sep': 1,
                    'external': f"file:///{str(target_install).replace(os.sep, '/')}",
                    'path': f"/{str(target_install).replace(os.sep, '/')}",
                    'scheme': 'file'
                },
                'relativeLocation': extension_id,
                'metadata': {
                    'isApplicationScoped': False,
                    'isMachineScoped': False,
                    'isBuiltin': False,
                    'installedTimestamp': int(time.time() * 1000),
                    'pinned': True,
                    'source': 'vsix'
                }
            })
            with open(ext_json, 'w', encoding='utf-8') as f:
                json.dump(extensions, f, ensure_ascii=False)
            print(f"✔ extensions.json güncellendi ({ext_dir.parent.name})")
        except Exception as e:
            print(f"⚠️ extensions.json güncellenemedi: {e}")

print("✔ 2/4 Uzantı dosyaları başarıyla IDE dizinine kopyalandı.")

# 3. Clean Corrupted Chromium Service Worker Cache
print("🧹 3/4 Bozulan Chromium ServiceWorker ve Webview önbelleği temizleniyor...")
sw_dirs = [
    home / 'AppData' / 'Roaming' / 'Antigravity IDE' / 'Service Worker',
    home / 'AppData' / 'Roaming' / 'Antigravity' / 'Service Worker',
    home / 'AppData' / 'Roaming' / 'Antigravity IDE' / 'Code Cache',
    home / 'AppData' / 'Roaming' / 'Antigravity' / 'Code Cache'
]

cleaned_sw = 0
for d in sw_dirs:
    if d.exists():
        try:
            shutil.rmtree(d, ignore_errors=True)
            cleaned_sw += 1
            print(f"   ✔ Temizlendi: {d.parent.name}\\{d.name}")
        except Exception as e:
            print(f"   ⚠️ Temizleme atlandı ({d.name}): {e}")

print(f"✔ 3/4 Önbellek temizliği tamamlandı ({cleaned_sw} dizin).")

# 4. Result & Instructions
print("\n" + "=" * 60)
print(f"🎉 GRAVITYGUARD v{version} BAŞARIYLA GÜNCELLENDİ!")
print("=" * 60)
print("💡 Değişikliklerin IDE'ye yansıması için:")
print("   Antigravity IDE penceresinde 'Ctrl+Shift+P' tuşlarına basın")
print("   ve 'Developer: Reload Window' seçeneğini çalıştırın.")
print("   (Veya Antigravity IDE'yi kapatıp yeniden açın).")
print("=" * 60)
