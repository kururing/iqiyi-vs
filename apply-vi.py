# -*- coding: utf-8 -*-
"""Gan tieng Viet vao skin XML va trang chu LWA cua app iQIYI noi dia."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from iqiyi_common import atomic_write, installation_lock, iqiyi_install_roots, lwa_backup_dir, subtitle_hook, patch_subtitle_tag

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent
DICT_PATH = ROOT / "vi.json"
BACKUP = ROOT / "backup-skin"
BACKUP_LWA = ROOT / "backup-lwa"
ATTRS = ("text", "tooltip", "hint", "placeholder", "disabledtext")
ATTR_RE = re.compile(
    r'(?P<attr>' + "|".join(ATTRS) + r')\s*=\s*(?P<q>["\'])(?P<val>.*?)(?P=q)',
    re.DOTALL,
)
# Text node giua hai the (trang HTML tinh nhu net/VodOtherErr_White.html khong nap
# duoc ui-engine.js nen phai sua thang noi dung file).
TEXT_NODE_RE = re.compile(r">([^<>]+)<")
CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")

SKIN_CANDIDATES = [
    Path(os.environ[name]) / "IQIYI Video" / "LStyle"
    for name in ("ProgramFiles", "ProgramFiles(x86)") if os.environ.get(name)
]
APPDATA_LWA = Path(os.environ.get("APPDATA", "")) / "IQIYI Video" / "localwebapp"
PPSTREAM_INI = Path(os.environ.get("APPDATA", "")) / "IQIYI Video" / "LStyle" / "PPStream.ini"

MARKER = "/* iqiyi-vi */"
LWA_JS = ROOT / "lwa-vi.js"
LWA_ENGINE = ROOT / "ui-engine.js"
WEB_DICT = ROOT / "web-vi.json"
OVERRIDE_DICT = ROOT / "vi-overrides.json"
SCRIPT_TAG = '<script src="./lwa-vi.js"></script>'
WRAPPER_APP = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/iQIYI/resources/app"
SIGNED_LWA_HTML = frozenset({
    "compactplayer.html", "compactplayer_mac.html", "download.html", "index.html", "login.html",
    "mac.html", "mini.html", "placeholder.html", "player.html", "player_mac.html",
})


def find_skin() -> Path | None:
    bases = iqiyi_install_roots(ROOT) + SKIN_CANDIDATES
    seen: set[str] = set()
    for base in bases:
        key = os.path.normcase(str(base))
        if key in seen:
            continue
        seen.add(key)
        if not base.exists():
            continue
        versions = sorted(
            [p for p in base.iterdir() if p.is_dir() and (p / "skin").exists()],
            key=lambda p: tuple(int(n) for n in re.findall(r"\d+", p.name)),
            reverse=True,
        )
        if versions:
            return versions[0] / "skin"
    return None


def find_iqiyi_client() -> Path | None:
    for root in iqiyi_install_roots(ROOT):
        client = root / "QyClient.exe"
        if client.is_file():
            return client
    return None


def find_lwa_dirs() -> list[Path]:
    found: list[Path] = []
    if APPDATA_LWA.exists():
        for index in APPDATA_LWA.rglob("index.html"):
            found.append(index.parent)
    skin = find_skin()
    if skin:
        pf = skin / "LwaRes" / "iqiyi_webapp"
        if pf.exists() and (pf / "index.html").exists():
            found.append(pf)
    # newest first
    return sorted(found, key=lambda p: p.name, reverse=True)


def load_dict() -> dict[str, str]:
    data: dict[str, str] = {}
    for path in (DICT_PATH, WEB_DICT, OVERRIDE_DICT):
        if not path.exists():
            # Từ điển phát triển nằm ở .local/ (không commit); bản phát hành ở ROOT.
            path = ROOT / ".local" / path.name
        if not path.exists():
            continue
        try:
            part = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(part, dict):
            data.update({k: v for k, v in part.items() if k and v and k != v})
    return data


def load_titles() -> dict[str, str]:
    """Tên Việt chính thức của phim (titles-vi.json); rỗng nếu chưa có."""
    data: dict[str, str] = {}
    for path in (ROOT / "titles-vi.json", ROOT / ".local" / "titles-vi.json"):
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        rows = payload.get("titles") if isinstance(payload, dict) else None
        if isinstance(rows, dict):
            data.update({str(k).strip(): str(v).strip() for k, v in rows.items()
                         if isinstance(v, str) and str(k).strip() and str(v).strip()})
    return data


def build_lwa_js(mapping: dict[str, str]) -> str:
    engine = LWA_ENGINE.read_text(encoding="utf-8")
    dumped = json.dumps(mapping, ensure_ascii=False, separators=(",", ":"))
    titles = json.dumps(load_titles(), ensure_ascii=False, separators=(",", ":"))
    return ("window.__iqiyiViDict = " + dumped + ";\n"
            + "window.__iqiyiViTitles = " + titles + ";\n" + engine)


def backup_file(base: Path, dest_root: Path, rel: Path) -> None:
    dest = dest_root / rel
    if dest.exists():
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(base / rel, dest)


def restore_tree(backup: Path, dest_root: Path) -> int:
    if not backup.exists():
        return 0
    n = 0
    for src in backup.rglob("*"):
        if not src.is_file():
            continue
        dest = dest_root / src.relative_to(backup)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        n += 1
    return n


def skin_backup_dir(skin: Path) -> Path:
    return BACKUP / "versions" / skin.parent.name


def patch_text(raw: str, mapping: dict[str, str]) -> tuple[str, int]:
    hits = 0

    def repl(m: re.Match) -> str:
        nonlocal hits
        val = m.group("val")
        vi = mapping.get(val)
        if vi is None and "\r" in val:
            vi = mapping.get(val.replace("\r\n", "\n").replace("\r", "\n"))
        if vi is None:
            return m.group(0)
        hits += 1
        return f'{m.group("attr")}={m.group("q")}{vi}{m.group("q")}'

    return ATTR_RE.sub(repl, raw), hits


def patch_text_nodes(raw: str, mapping: dict[str, str]) -> tuple[str, int]:
    """Dịch text node còn chữ Hán trong file HTML tĩnh (không chạy được script).

    Chỉ đổi khi khớp TRỌN chuỗi trong từ điển để tránh câu lai; giữ nguyên
    khoảng trắng thụt lề hai đầu của text node.
    """
    hits = 0

    def repl(m: re.Match) -> str:
        nonlocal hits
        inner = m.group(1)
        stripped = inner.strip()
        if not stripped or not CJK_RE.search(stripped):
            return m.group(0)
        vi = mapping.get(stripped)
        if vi is None:
            normalized = " ".join(stripped.split())
            vi = mapping.get(normalized)
            if vi is not None:
                stripped, normalized = normalized, vi
        if vi is None:
            return m.group(0)
        hits += 1
        lead = inner[: len(inner) - len(inner.lstrip())]
        trail = inner[len(inner.rstrip()):]
        return f">{lead}{vi}{trail}<"

    return TEXT_NODE_RE.sub(repl, raw), hits


def read_text(path: Path) -> tuple[str, str]:
    data = path.read_bytes()
    if data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff"):
        return data.decode("utf-16"), "utf-16"
    head = data[:200].decode("ascii", errors="ignore").lower()
    declared = "gb18030" if ("gb18030" in head or "gbk" in head or "gb2312" in head) else "utf-8"
    for enc in (declared, "utf-8-sig", "utf-8", "gb18030"):
        try:
            return data.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="ignore"), "utf-8"


LWA_INI_FLAGS = {
    "lwa_disable_checksign_pcafx": "1",
    "lwa_disable_update": "1",
    "lwa_disable_repalce_update": "1",
    "lwa_disable_load_copy": "1",
}



def disable_lwa_sign() -> None:
    if not PPSTREAM_INI.exists():
        return
    last_error: OSError | None = None
    for _ in range(8):
        try:
            raw = PPSTREAM_INI.read_text(encoding="utf-8", errors="ignore")
            new = raw
            for key, val in LWA_INI_FLAGS.items():
                if re.search(rf"(?m)^{re.escape(key)}=.*$", new):
                    new = re.sub(rf"(?m)^{re.escape(key)}=.*$", f"{key}={val}", new)
                else:
                    new += f"\n{key}={val}\n"
            if new != raw:
                bak = ROOT / "backup-ppstream.ini"
                if not bak.exists():
                    bak.write_text(raw, encoding="utf-8")
                PPSTREAM_INI.write_text(new, encoding="utf-8")
                print("Da tat chu ky + update goi web (PPStream.ini).")
            return
        except OSError as exc:
            last_error = exc
            time.sleep(0.5)
    if last_error:
        print("Khong ghi duoc PPStream.ini:", last_error)


def restore_lwa_sign() -> None:
    bak = ROOT / "backup-ppstream.ini"
    if bak.exists() and PPSTREAM_INI.exists():
        PPSTREAM_INI.write_text(bak.read_text(encoding="utf-8"), encoding="utf-8")


def startup_vbs() -> Path:
    return Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs/Startup/iqiyi-vi-watch.vbs"


def python_exe() -> str:
    for name in ("pythonw.exe", "python.exe"):
        path = ROOT / ".venv" / "Scripts" / name
        if path.exists():
            return str(path)
    return sys.executable


def install_autostart() -> None:
    py = python_exe()
    watch = ROOT / "watch-iqiyi-vi.py"
    vbs = startup_vbs()
    try:
        vbs.parent.mkdir(parents=True, exist_ok=True)
        vbs.write_text(
            f'Set s=CreateObject("WScript.Shell")\ns.Run """{py}"" ""{watch}""", 0, False\n',
            encoding="ascii",
            errors="replace",
        )
    except OSError as exc:
        print(f"Khong cai duoc tu dong khoi dong: {exc}")
    subprocess.Popen(
        [py, str(watch)],
        cwd=str(ROOT),
        close_fds=True,
        creationflags=0x08000000,
    )
    print("Da khoi dong watchdog.")


def inject_lwa_dir(webapp: Path, payload: str) -> int:
    n = 0
    hook = subtitle_hook(ROOT)
    atomic_write(webapp / "sub-hook.js", hook)
    dest_js = webapp / "lwa-vi.js"
    atomic_write(dest_js, payload)
    n += 1

    for path in webapp.glob("*.html"):
        raw, _ = read_text(path)
        backup_file(webapp, lwa_backup_dir(BACKUP_LWA, webapp), Path(path.name))
        raw = patch_subtitle_tag(raw, hook)
        if "lwa-vi.js" in raw:
            atomic_write(path, raw)
            continue
        # Chèn vào </head> để từ điển có mặt trước khi React render chuỗi tiếng Trung.
        if "</head>" in raw:
            raw = raw.replace("</head>", SCRIPT_TAG + "</head>", 1)
        elif "</body>" in raw:
            raw = raw.replace("</body>", SCRIPT_TAG + "</body>", 1)
        elif "<body>" in raw:
            raw = raw.replace("<body>", SCRIPT_TAG + "<body>", 1)
        else:
            raw += SCRIPT_TAG
        atomic_write(path, raw)
        n += 1

    return n


def patch_wrapper_app(app_dir: Path = WRAPPER_APP) -> bool:
    """Load the subtitle hook before iQ.com player scripts in the desktop wrapper."""
    main = app_dir / "main.js"
    if not main.is_file():
        return False
    hook_dest = app_dir / "iqiyi-vi-subtitle.js"
    atomic_write(hook_dest, subtitle_hook(ROOT))
    raw = main.read_text(encoding="utf-8")
    marker = "// IQIYI-VI EARLY SUBTITLE HOOK"
    if marker in raw:
        return True
    read_anchor = "const userscript = fs.readFileSync(path.join(__dirname, 'theater.user.js'), 'utf8');"
    event_anchor = "app.on('web-contents-created', (_event, contents) => {"
    execute_anchor = "contents.executeJavaScript(userscript, true)"
    if read_anchor not in raw or event_anchor not in raw:
        return False
    if execute_anchor not in raw:
        return False
    backup = app_dir / "main.js.iqiyi-vi.bak"
    if not backup.exists():
        shutil.copy2(main, backup)
    raw = raw.replace(read_anchor, read_anchor + "\nconst subtitleHook = fs.readFileSync(path.join(__dirname, 'iqiyi-vi-subtitle.js'), 'utf8');", 1)
    raw = raw.replace(
        event_anchor,
        event_anchor + "\n    " + marker + "\n    try {\n"
        "        if (!contents.debugger.isAttached()) contents.debugger.attach('1.3');\n"
        "        contents.debugger.sendCommand('Page.addScriptToEvaluateOnNewDocument', { source: subtitleHook })\n"
        "            .catch(error => console.error('[iqiyi-vi] early hook failed:', error));\n"
        "    } catch (error) {\n"
        "        console.error('[iqiyi-vi] early hook unavailable:', error);\n"
        "    }",
        1,
    )
    raw = raw.replace(execute_anchor, "contents.executeJavaScript(userscript + '\\n' + subtitleHook, true)", 1)
    atomic_write(main, raw)
    return True


def restore_wrapper_app(app_dir: Path = WRAPPER_APP) -> bool:
    """Restore the wrapper entry point changed by patch_wrapper_app."""
    main = app_dir / "main.js"
    backup = app_dir / "main.js.iqiyi-vi.bak"
    if not backup.is_file():
        return False
    shutil.copy2(backup, main)
    hook = app_dir / "iqiyi-vi-subtitle.js"
    if hook.exists():
        hook.unlink()
    return True


def apply_skin(skin: Path, mapping: dict[str, str]) -> tuple[int, int, int]:
    files = hits = skipped = 0
    for path in list(skin.rglob("*.xml")) + list(skin.rglob("*.html")):
        if path.parent.name.casefold() == "iqiyi_webapp" and path.name.casefold() in SIGNED_LWA_HTML:
            continue
        rel = path.relative_to(skin)
        try:
            raw, enc = read_text(path)
        except OSError:
            skipped += 1
            continue
        new, n = patch_text(raw, mapping)
        # Trang HTML tĩnh không nạp được ui-engine.js thì phải sửa thẳng text node.
        if path.suffix.casefold() == ".html":
            patched_nodes, n_nodes = patch_text_nodes(new, mapping)
            if n_nodes:
                new, n = patched_nodes, n + n_nodes
        if n == 0:
            continue
        backup_file(skin, skin_backup_dir(skin), rel)
        atomic_write(path, new)
        files += 1
        hits += n
    return files, hits, skipped


def main() -> int:
    if "--client-path" in sys.argv:
        client = find_iqiyi_client()
        if client:
            print(client)
            return 0
        print("Khong tim thay QyClient.exe.")
        return 1
    with installation_lock(ROOT):
        disabled = ROOT / "watch-iqiyi-vi.disabled"
        restoring = "--restore" in sys.argv
        if restoring:
            atomic_write(disabled, "restored\n")
        result = _main()
        if result == 0 and not restoring:
            disabled.unlink(missing_ok=True)
        return result


def _main() -> int:
    restore = "--restore" in sys.argv
    lwa_only = "--lwa" in sys.argv
    mapping = load_dict() if not restore else {}
    payload = ""
    if mapping:
        payload = build_lwa_js(mapping)
        atomic_write(LWA_JS, payload)
    elif LWA_JS.exists():
        payload = LWA_JS.read_text(encoding="utf-8")

    if restore:
        try:
            skin = find_skin()
            if skin:
                print(f"Skin: {skin}")
            n = restore_tree(skin_backup_dir(skin), skin) if skin else 0
            if skin and BACKUP.exists() and not skin_backup_dir(skin).exists():
                print("Bo qua backup skin cu khong ro phien ban de tranh ghi de sai resource.")
            if restore_wrapper_app():
                n += 2
            for webapp in find_lwa_dirs():
                n += restore_tree(lwa_backup_dir(BACKUP_LWA, webapp), webapp)
                for page in webapp.glob("*.html"):
                    raw, _ = read_text(page)
                    cleaned = patch_subtitle_tag(raw.replace(SCRIPT_TAG, ""), None)
                    if cleaned != raw:
                        atomic_write(page, cleaned)
                for name in ("lwa-vi.js", "sub-hook.js"):
                    extra = webapp / name
                    if extra.exists():
                        extra.unlink()
                        n += 1
            restore_lwa_sign()
            vbs = startup_vbs()
            if vbs.exists():
                vbs.unlink()
        except PermissionError as exc:
            print(f"Can quyen Administrator de khoi phuc giao dien native: {exc}")
            return 2
        print(f"Da khoi phuc {n} file goc.")
        print("Tat app iQIYI roi mo lai.")
        return 0

    disable_lwa_sign()
    if patch_wrapper_app():
        print("Da gan hook phu de som vao app iQ.com.")
    lwa_dirs = find_lwa_dirs()
    lwa_n = 0
    if not payload:
        print("Thieu lwa-vi.js")
    else:
        if not lwa_dirs:
            print("Khong tim thay goi web LWA.")
        for webapp in lwa_dirs:
            print(f"LWA: {webapp}")
            try:
                lwa_n += inject_lwa_dir(webapp, payload)
            except PermissionError:
                print(f"Bo qua LWA can quyen Administrator: {webapp}")
        print(f"Da nhung script dich trang chu vao {lwa_n} file LWA.")

    install_autostart()

    if lwa_only:
        return 0

    skin = find_skin()
    if not skin:
        print("Khong tim thay thu muc skin. Phan native bo qua.")
        print("Tat iQIYI roi mo lai de thay tieng Viet o trang chu.")
        return 0

    try:
        atomic_write(ROOT / ".iqiyi-install-location", str(skin.parent) + "\n")
    except OSError:
        pass
    print(f"Skin: {skin}")
    print(f"Tu dien: {len(mapping)} chuoi")
    try:
        files, hits, skipped = apply_skin(skin, mapping)
    except PermissionError:
        print("Can quyen Administrator de ghi skin Program Files.")
        print("Trang chu LWA (AppData) da duoc gan, khong can admin.")
        print("Tat iQIYI roi mo lai.")
        return 2
    print(f"Da dich {hits} chuoi trong {files} file skin.")
    if skipped:
        print(f"Bo qua {skipped} file khong doc duoc.")
    print(f"Ban sao luu: {BACKUP}")
    print("Tat QyClient / iQIYI roi mo lai.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
