# -*- coding: utf-8 -*-
"""Gan tieng Viet vao skin XML va trang chu LWA cua app iQIYI noi dia."""
from __future__ import annotations

import json
from html import escape, unescape
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

if os.name == "nt":
    import winreg

from iqiyi_common import (
    SIGNED_LWA_HTML, atomic_write, installation_lock, iqiyi_install_roots, iqiyi_skin_dir,
    lwa_backup_dir, patch_subtitle_tag, patch_ui_tag, python_executable, restore_lwa_ini_flags,
    subtitle_hook, update_lwa_ini_flags,
)

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent
BACKUP = ROOT / "backup-skin"
BACKUP_LWA = ROOT / "backup-lwa"
# Some native QyClient resources misspell `tooltip` as `tooptip`.
ATTRS = ("text", "tooltip", "tooptip", "tip", "hint", "placeholder", "disabledtext", "title", "aria-label", "alt")
ATTR_RE = re.compile(
    r'(?<![\w:-])(?P<attr>' + "|".join(ATTRS) + r')\s*=\s*(?P<q>["\'])(?P<val>.*?)(?P=q)',
    re.DOTALL,
)
# Text node giua hai the (trang HTML tinh nhu net/VodOtherErr_White.html khong nap
# duoc ui-engine.js nen phai sua thang noi dung file).
TEXT_NODE_RE = re.compile(r">([^<>]+)<")
CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")

APPDATA_LWA = Path(os.environ.get("APPDATA", "")) / "IQIYI Video" / "localwebapp"
PPSTREAM_INI = Path(os.environ.get("APPDATA", "")) / "IQIYI Video" / "LStyle" / "PPStream.ini"

LWA_JS = ROOT / "lwa-vi.js"
LWA_ENGINE = ROOT / "ui-engine.js"
SCRIPT_TAG = '<script src="./lwa-vi.js"></script>'
WRAPPER_APP = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/iQIYI/resources/app"


def find_skin() -> Path | None:
    seen: set[str] = set()
    for base in iqiyi_install_roots(ROOT):
        key = os.path.normcase(str(base))
        if key in seen:
            continue
        seen.add(key)
        skin = iqiyi_skin_dir(base)
        if skin:
            return skin
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


def load_prepared_ui() -> dict[str, str]:
    """Use only the prepared UI copy embedded in the current engine."""
    engine = LWA_ENGINE.read_text(encoding="utf-8")
    match = re.search(r"var FIXED_COPY = (\{.*?\});", engine, re.DOTALL)
    if not match:
        raise ValueError("Khong tim thay nhan Viet soan san trong ui-engine.js")
    return json.loads(match.group(1))


def build_lwa_js() -> str:
    return LWA_ENGINE.read_text(encoding="utf-8")


def sync_extension_sources() -> None:
    """Sync the DOM engine and subtitle hook without legacy dictionary assets."""
    extension = ROOT / "ext"
    atomic_write(extension / "content.js", LWA_ENGINE.read_text(encoding="utf-8"))
    atomic_write(extension / "sub-hook.js", (ROOT / "sub-hook.js").read_text(encoding="utf-8"))


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
        vi = mapping.get(unescape(val))
        if vi is None and "\r" in val:
            vi = mapping.get(val.replace("\r\n", "\n").replace("\r", "\n"))
        if vi is None:
            return m.group(0)
        hits += 1
        return f'{m.group("attr")}={m.group("q")}{escape(vi, quote=True)}{m.group("q")}'

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
        stripped = unescape(inner.strip())
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
        return f">{lead}{escape(vi, quote=False)}{trail}<"

    # Script/style source and editable defaults are not display labels.
    protected = re.compile(r"<(script|style|textarea|code|noscript)\b[^>]*>.*?</\1\s*>", re.I | re.S)
    parts = []
    end = 0
    for block in protected.finditer(raw):
        parts.append(TEXT_NODE_RE.sub(repl, raw[end:block.start()]))
        parts.append(block.group(0))
        end = block.end()
    parts.append(TEXT_NODE_RE.sub(repl, raw[end:]))
    return "".join(parts), hits


def patch_native_subtitle_menu(raw: str) -> str:
    """Give translated subtitle track labels enough room in the desktop player menu."""
    if 'name="menu_subtitle"' not in raw:
        return raw
    raw = re.sub(r'minwidth=&quot;\d+&quot;', 'minwidth=&quot;190&quot;', raw, count=1)
    raw = re.sub(r'itemheight=&quot;\d+&quot;', 'itemheight=&quot;32&quot;', raw, count=1)
    return re.sub(r'(<Font\b[^>]*\bsize=)"\d+"', r'\g<1>"13"', raw, count=1)


def _set_xml_tag_attributes(tag: str, updates: dict) -> str:
    for attr, value in updates.items():
        value = escape(str(value), quote=True)
        pattern = rf'(\b{attr}\s*=\s*)"[^"]*"'
        if re.search(pattern, tag):
            tag = re.sub(pattern, lambda m: f'{m[1]}"{value}"', tag, count=1)
        else:
            tag = re.sub(r'(/?>)$', lambda m: f' {attr}="{value}"{m[1]}', tag, count=1)
    return tag


def patch_native_settings_layout(raw: str, rel: Path) -> str:
    """Fit Vietnamese labels inside the native settings dialog's fixed page width."""
    if rel.parent.as_posix().casefold() != "configres/settingdlgres":
        return raw
    page = rel.stem.casefold().removesuffix("_wine")
    if page not in {"settingdlg", "playsetting", "playadvancedsetting", "basicsetting", "downloadsetting", "hotkeysetting"}:
        return raw

    def patch_tag(match: re.Match) -> str:
        tag = match.group(0)
        attrs = dict(re.findall(r'([\w-]+)\s*=\s*"([^"]*)"', tag))
        updates = {}
        name = attrs.get("name", "")
        if page == "settingdlg" and "config_icon.svg" in attrs.get("bkimage", ""):
            updates["pos"] = "20,24,180,44"
        if page == "playsetting":
            if match.group(1) == "Label" and attrs.get("text") in {
                    "Tăng tốc phần cứng:", "Cài đặt FPS cao:"}:
                updates["width"] = "150"
            if match.group(1) == "Label" and attrs.get("width") == "66":
                updates["width"] = "118"
            if attrs.get("name") in {"comb_adapter", "ps_comboaudio"}:
                updates["width"] = "240"
            if attrs.get("name") in {"auto_high_fps", "open_high_fps", "close_high_fps"}:
                updates["width"] = "110"
            widths = {"ps_radioselFull": 118, "ps_radioselSimple": 142, "playacceleratesvr": 190,
                      "open_lwa_gpu_ck": 190, "sup_resolution": 82, "memc_check": 120}
            if name in widths:
                updates["width"] = str(widths[name])
            if attrs.get("text") == "(Chỉ áp dụng cho chất lượng 1080P trở xuống)":
                updates.update(text="(Chỉ với 1080P trở xuống)", tooltip=attrs["text"])
            if attrs.get("text") == "(chỉ với 1080P)":
                updates["width"] = "150"
        if page == "playadvancedsetting":
            if match.group(1) == "Label" and attrs.get("width") in {"66", "70"}:
                updates["width"] = "150" if attrs["width"] == "70" else "110"
            if attrs.get("name") in {"comb_adapter", "ps_comboaudio"}:
                updates["width"] = "268"
            if attrs.get("name") in {"intelligencedecode", "ps_decode_soft", "ps_decode_hard"}:
                updates["width"] = "160"
        if page != "settingdlg" and attrs.get("text") == "(nên dùng)":
            updates["width"] = "90"
        if page == "basicsetting":
            widths = {"bs_autorun": 146, "bs_radiotaskbar": 112, "bs_radiotray": 112,
                      "bs_miniqiyi": 150, "bs_exitiqiyi": 70, "bs_jijian_open": 150, "bs_jijian_close": 70}
            if name in widths:
                updates["width"] = str(widths[name])
            if name == "bs_jijian_autorun":
                updates["padding"] = "12,0,0,0"
            if name == "bs_radiotray":
                updates["padding"] = "32,0,0,0"
            if name in {"bs_exitiqiyi", "bs_jijian_close"}:
                updates["padding"] = "16,0,0,0"
        if page == "downloadsetting":
            if name in {"ds_btnBrowserdownload", "ds_btnBrowsercache"}:
                updates["pos"] = "282,0,370,26"
            if name in {"ds_editdownloadpath", "ds_editcachepath"}:
                updates["textpadding"] = "4,3,90,3"
            if name == "ds_checkdownloaddelwitdlocal":
                updates.update(text="Xóa cả tệp trên máy", tooltip="Xóa tệp trên máy khi xóa khỏi danh sách tải")
            if attrs.get("text") == "Xóa cache":
                updates["width"] = "76"
            if attrs.get("width") == "1" and attrs.get("padding") == "237,9,0,0":
                updates["padding"] = "187,9,0,0"
            if name == "ds_btnClearCache":
                updates["width"] = "70"
        if page == "hotkeysetting":
            if name == "hs_openboss":
                updates["width"] = "150"
            if name == "btnShortCutDefault":
                updates.update(width="130", pos="260,0,0,0")
        return _set_xml_tag_attributes(tag, updates)

    return re.sub(r'<(Label|CheckBox|Combo|Button|Edit)\b[^>]*>', patch_tag, raw)


def patch_native_auxiliary_layout(raw: str, rel: Path) -> str:
    """Repair fixed text in common dialogs without touching control bindings or state."""
    page = rel.as_posix().casefold()
    rules = {
        "configres/timesetdlg.xml": {"radioPlayEnd": {"width": 225}, "radioDownloadEnd": {"width": 225},
                                    "btnreset": {"width": 100}},
        "configres/shutdowntipdlg.xml": {"showtip": {"width": 112}, "showtime": {"width": 32},
                                        "showtip1": {"width": 42}, "btnOK": {"width": 104}, "btnCancel": {"width": 104}},
        "geeplayer/skin/config/aboutdlg.xml": {"btnVersionInfo": {"textpadding": "12,0,12,0"},
                                               "btndeclareInfo": {"textpadding": "12,0,12,0"}},
        "geeplayer/skin/player/miniplayer/other/playconfig/subaudio.xml": {
            "btnAudioAdjust": {"textpadding": "38,13,12,13"}, "btnLoadTrack": {"textpadding": "38,13,12,13"}},
        "geeplayer/skin/player/miniplayer/other/playconfig/subsubtitle.xml": {
            "btnSubtitleAdjust": {"textpadding": "38,13,38,13"}, "btnLoad": {"textpadding": "38,13,12,13"}},
        "geeplayer/skin/player/miniplayer/other/sound_sync/sound_sync.xml": {"label_state": {"width": 220}},
        "geeplayer/skin/player/miniplayer/other/playfileattri/playfileattriwnd.xml": {
            "lab_file_size": {"width": 92}, "lab_file_bitrate": {"width": 92}},
        "geeplayer/skin/config/playlist.xml": {"clearlist": {"width": 220}},
        "geeplayer/skin/config/lyric_setting.xml": {"show_lyric": {"width": 160},
            "check_same_path_playfile": {"width": 210}, "check_self_define_path": {"width": 190}},
        "geeplayer/skin/frame/skinpeeler.xml": {"transLabel": {"width": 96}, "colorLabel": {"width": 60},
                                               "btn_DIYBk": {"padding": "8,2,0,0"}},
        "geeplayer/skin/list/locallist.xml": {"filename": {"padding": "4,2,0,0"},
                                             "search_btn": {"padding": "8,0,0,0"}, "OpenFile": {"width": 120}},
        "geeplayer/skin/menu/delmenu.xml": {"217093": {"text": "Xóa danh sách", "tooltip": "Xóa danh sách phát"}},
        "geeplayer/skin/player/miniplayer/other/titletrailer/titletrailer.xml": {"check_open": {"width": 190}},
    }
    if page not in rules:
        return raw

    def patch_tag(match):
        tag = match.group(0)
        attrs = dict(re.findall(r'([\w-]+)\s*=\s*"([^"]*)"', tag))
        updates = dict(rules[page].get(attrs.get("name"), {}))
        if page.endswith("timesetdlg.xml") and attrs.get("text") == "giờ":
            updates["width"] = 24
        if page.endswith("sound_sync.xml") and match.group(1) == "Label":
            if attrs.get("text") == "Đồng bộ âm thanh":
                updates["width"] = 160
            if attrs.get("text") == "Trạng thái:":
                updates["width"] = 90
        if page.endswith("playfileattriwnd.xml") and match.group(1) == "Label" and not attrs.get("name") and attrs.get("width") == "60":
            updates["width"] = 130
            if attrs.get("text") == "Tốc độ khung hình video:":
                updates["text"] = "Khung hình/giây:"
        if page.endswith("locallist.xml") and match.group(1) == "Label":
            if not attrs.get("name") and attrs.get("text") == "Danh sách phát" and attrs.get("width") == "64":
                updates.update(text="Danh sách", tooltip="Danh sách phát", width=72, indexfont="yahei_12")
            if attrs.get("text") == "Chưa có nội dung liên quan":
                updates["width"] = 220
        if page.endswith("titletrailer.xml") and match.group(1) == "Label" and attrs.get("text") in {"Đầu phim:", "Cuối phim:"}:
            updates["width"] = 68
        return _set_xml_tag_attributes(tag, updates)

    return re.sub(r'<(Label|CheckBox|Button|Option)\b[^>]*>', patch_tag, raw)


def read_text(path: Path) -> tuple[str, str]:
    data = path.read_bytes()
    if data.startswith(b"\xff\xfe"):
        return data.decode("utf-16-le"), "utf-16-le"
    if data.startswith(b"\xfe\xff"):
        return data.decode("utf-16-be"), "utf-16-be"
    head = data[:200].decode("ascii", errors="ignore").lower()
    declared = "gb18030" if ("gb18030" in head or "gbk" in head or "gb2312" in head) else "utf-8"
    for enc in (declared, "utf-8-sig", "utf-8", "gb18030"):
        try:
            return data.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="ignore"), "utf-8"


def disable_lwa_sign() -> None:
    if not PPSTREAM_INI.exists():
        return
    last_error: OSError | None = None
    for _ in range(8):
        try:
            raw = PPSTREAM_INI.read_text(encoding="utf-8", errors="ignore")
            new = update_lwa_ini_flags(raw)
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
        raw = PPSTREAM_INI.read_bytes().decode("utf-8")
        restored = restore_lwa_ini_flags(raw, bak.read_bytes().decode("utf-8"))
        if restored != raw:
            atomic_write(PPSTREAM_INI, restored.encode("utf-8"))


def remove_injected_html_tags(text: str) -> str:
    """Remove this app's external/marked scripts, including versioned tags, only."""
    text = re.sub(r'<script\b[^>]*\bsrc=["\']\./(?:lwa-vi|sub-hook)\.js(?:\?[^"\'<>]*)?["\'][^>]*>\s*</script>',
                  "", text, flags=re.I)
    text = re.sub(r'<script\b[^>]*\bdata-iqiyi-vi(?:-ui|-subtitle)?(?:\s|=|>)[\s\S]*?</script>',
                  "", text, flags=re.I)
    return re.sub(r'<script\b[^>]*>\s*/\*\s*iqiyi-vi(?:-[a-z]+)?\s*\*/[\s\S]*?</script>',
                  "", text, flags=re.I)


STARTUP_REGISTRY_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
STARTUP_REGISTRY_VALUE = "IQIYI-VI-Watch"


def startup_vbs() -> Path:
    """Path of the legacy startup script, removed during migration to Run key."""
    return Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs/Startup/iqiyi-vi-watch.vbs"


def python_exe() -> str:
    return str(python_executable(ROOT, background=True))


def install_autostart() -> None:
    py = python_exe()
    watch = ROOT / "watch-players.py"
    try:
        startup_vbs().unlink(missing_ok=True)
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, STARTUP_REGISTRY_KEY, 0,
                                winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, STARTUP_REGISTRY_VALUE, 0, winreg.REG_SZ,
                              subprocess.list2cmdline([py, str(watch), "iqiyi"]))
    except OSError as exc:
        print(f"Khong cai duoc tu dong khoi dong: {exc}")
    subprocess.Popen(
        [py, str(watch), "iqiyi"],
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
        if path.name.casefold() in SIGNED_LWA_HTML:
            # Preserve the exact bytes covered by QyClient's package signature.
            original = lwa_backup_dir(BACKUP_LWA, webapp) / path.name
            if original.is_file() and path.read_bytes() != original.read_bytes():
                shutil.copy2(original, path)
            continue
        raw, enc = read_text(path)
        backup_file(webapp, lwa_backup_dir(BACKUP_LWA, webapp), Path(path.name))
        raw = patch_subtitle_tag(raw, hook)
        raw = patch_ui_tag(raw, payload.encode("utf-8"))
        atomic_write(path, raw.encode(enc))
        n += 1

    return n


def patch_wrapper_app(app_dir: Path = WRAPPER_APP) -> bool:
    """Load the subtitle hook before iQ.com player scripts in the desktop wrapper."""
    main = app_dir / "main.js"
    if not main.is_file():
        return False
    hook_dest = app_dir / "iqiyi-vi-subtitle.js"
    atomic_write(hook_dest, build_lwa_js().encode("utf-8") + b"\n" + subtitle_hook(ROOT))
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
        layout_changed = False
        if rel.as_posix().casefold() == "geeplayer/skin/menu/subtitlelist.xml":
            menu = patch_native_subtitle_menu(new)
            layout_changed = menu != new
            new = menu
        settings = patch_native_settings_layout(new, rel)
        layout_changed = layout_changed or settings != new
        new = settings
        auxiliary = patch_native_auxiliary_layout(new, rel)
        layout_changed = layout_changed or auxiliary != new
        new = auxiliary
        if n == 0 and not layout_changed:
            continue
        backup_file(skin, skin_backup_dir(skin), rel)
        atomic_write(path, new.encode(enc))
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
    mapping = load_prepared_ui() if not restore else {}
    if not restore and not mapping:
        print("Khong co nhan Viet soan san trong ui-engine.js.")
        return 1
    payload = ""
    if mapping:
        payload = build_lwa_js()
        atomic_write(LWA_JS, payload)
        sync_extension_sources()
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
                    if page.name.casefold() in SIGNED_LWA_HTML:
                        continue
                    raw, enc = read_text(page)
                    cleaned = remove_injected_html_tags(raw)
                    if cleaned != raw:
                        atomic_write(page, cleaned.encode(enc))
                for name in ("lwa-vi.js", "sub-hook.js"):
                    extra = webapp / name
                    if extra.exists():
                        extra.unlink()
                        n += 1
            restore_lwa_sign()
            startup_vbs().unlink(missing_ok=True)
            if os.name == "nt":
                try:
                    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_REGISTRY_KEY, 0,
                                        winreg.KEY_SET_VALUE) as key:
                        winreg.DeleteValue(key, STARTUP_REGISTRY_VALUE)
                except FileNotFoundError:
                    pass
        except PermissionError as exc:
            print(f"Can quyen Administrator de khoi phuc giao dien native: {exc}")
            return 2
        print(f"Da khoi phuc {n} file goc.")
        print("Tat app iQIYI roi mo lai.")
        return 0

    permission_errors = []
    try:
        wrapper_patched = patch_wrapper_app()
    except PermissionError as exc:
        wrapper_patched = False
        permission_errors.append(str(exc))
    if wrapper_patched:
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
                permission_errors.append(str(webapp))
                print(f"LWA can quyen Administrator: {webapp}")
        print(f"Da nhung script dich trang chu vao {lwa_n} file LWA.")

    if lwa_only:
        if permission_errors:
            return 2
        if not lwa_dirs and not wrapper_patched:
            print("Khong tim thay goi web hoac app de Viet hoa.")
            return 1
        install_autostart()
        return 0

    skin = find_skin()
    if not skin:
        print("Khong tim thay thu muc skin. Phan native bo qua.")
        print("Tat iQIYI roi mo lai de thay tieng Viet o trang chu.")
        if permission_errors:
            return 2
        if not lwa_dirs and not wrapper_patched:
            print("Khong tim thay tai nguyen iQIYI de Viet hoa.")
            return 1
        install_autostart()
        return 0

    try:
        atomic_write(ROOT / ".iqiyi-install-location", str(skin.parent.parent) + "\n")
    except OSError:
        pass
    print(f"Skin: {skin}")
    print(f"Nhan Viet soan san: {len(mapping)} chuoi")
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
        return 1
    if permission_errors:
        return 2
    install_autostart()
    print(f"Ban sao luu: {BACKUP}")
    print("Tat QyClient / iQIYI roi mo lai.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
