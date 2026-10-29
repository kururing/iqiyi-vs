"""Run with Python from the checkout; the refresh check also requires Node.js."""
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import iqiyi_common as common


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check_assets():
    installer = load_script("apply-vi.py")
    watcher = load_script("watch-players.py")
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        (root / "ext").mkdir()
        for name in ("content.js", "sub-hook.js"):
            shutil.copy2(ROOT / "ext" / name, root / "ext" / name)
        engine = root / "ext" / "content.js"
        webapp = root / "webapp"
        webapp.mkdir()
        signed = b"<html><head></head><body>signed</body></html>"
        (webapp / "index.html").write_bytes(signed)
        for name in ("harmonyos.html", "player_harmonyos.html", "future_platform.html"):
            (webapp / name).write_bytes(signed)
        (webapp / "localwebapp.files.json").write_text(
            json.dumps({"files":[{"src":"./future_platform.html","sign":"vendor-signature"}]}),
            encoding="utf-8-sig")
        (webapp / "about.html").write_bytes(b"<html><head></head><body>about</body></html>")
        with (patch.object(common, "api_token", return_value="cleanup-test-token"),
              patch.multiple(installer, ROOT=root, UI_ENGINE=engine, BACKUP_LWA=root / "backups"),
              patch.multiple(watcher, ROOT=root, UI_ENGINE=engine,
                             SUB_HOOK_JS=root / "ext" / "sub-hook.js", BACKUP_LWA=root / "backups"),
              patch.object(watcher, "find_lwa_dirs", return_value=[webapp])):
            assert installer.load_prepared_ui(), "Installer must read the shared UI dictionary"
            installer.inject_lwa_dir(webapp, engine.read_text(encoding="utf-8"))
            for name in ("harmonyos.html", "player_harmonyos.html", "future_platform.html"):
                assert (webapp / name).read_bytes() == signed, name
            originals = common.lwa_backup_dir(root / "backups", webapp)
            originals.mkdir(parents=True, exist_ok=True)
            for name in ("harmonyos.html", "player_harmonyos.html", "future_platform.html"):
                (originals / name).write_bytes(signed)
                (webapp / name).write_bytes(signed + b'<script src="./lwa-vi.js"></script>')
            assert (webapp / "lwa-vi.js").read_bytes() == engine.read_bytes()
            assert (webapp / "sub-hook.js").read_bytes() == common.subtitle_hook(root)
            # Updating only the canonical source must update the installed copy.
            engine.write_bytes(engine.read_bytes() + b"\nwindow.__iqiyiViCleanupProbe = true;\n")
            watcher.patch_lwa()
            watcher.patch_lwa()
            assert (webapp / "lwa-vi.js").read_bytes() == engine.read_bytes()
            assert (webapp / "index.html").read_bytes() == signed
            for name in ("harmonyos.html", "player_harmonyos.html", "future_platform.html"):
                assert (webapp / name).read_bytes() == signed, "Repair signed page: " + name
            page = (webapp / "about.html").read_text(encoding="utf-8")
            assert page.count('src="./lwa-vi.js?') == page.count('src="./sub-hook.js?') == 1
            (webapp / "localwebapp.files.json").write_text("invalid manifest", encoding="utf-8")
            assert "about.html" in common.signed_lwa_html(webapp), "Unreadable manifests must preserve pages"
        assert common.restore_lwa_ini_flags(
            "user_setting=9\nlwa_disable_update=1\n", "user_setting=1\nlwa_disable_update=0\n"
        ) == "user_setting=9\nlwa_disable_update=0\n"


def check_refresh():
    source = (ROOT / "subtitle_app.py").read_text(encoding="utf-8")
    refresh = re.search(r"^async function refresh\(force\).*", source, re.M).group()
    check = r"""
const assert=require('node:assert/strict');
let refreshBusy=false,refreshPending=false,refreshError='',lastRenderSignature='';
let albumLists,discoveries,iqiyiSynced,iqiyiSources,episodeData;
let payload={episodes:[{tvid:'1',provider:'iqiyi',title:'Episode 1'}],session:{synced:false}};
const statusNode={textContent:''};
async function apiFetch(){return {ok:true,json:async()=>payload}}
function renderDiscoveries(){}
function updateIqcomStatus(){}
function renderMovieSearchResults(){}
const safeStatusText=value=>value;
let updates=0,renders=0,seenSession;
function updateProviderChrome(){updates++;seenSession=iqiyiSynced}
function render(){renders++;updateProviderChrome()}
(async()=>{
  await refresh(false);
  assert.equal(updates,1);assert.equal(renders,1);
  payload.session.synced=true;
  await refresh(false);
  assert.equal(updates,2);assert.equal(renders,1);assert.equal(seenSession,true);
  payload.episodes[0].title='Episode 2';
  await refresh(false);
  assert.equal(updates,3);assert.equal(renders,2);
  await refresh(true);
  assert.equal(updates,4);assert.equal(renders,3);
  assert.equal(refreshError,'');assert.equal(refreshBusy,false);
})().catch(error=>{console.error(error);process.exitCode=1});
"""
    subprocess.run(["node", "-"], input=refresh + "\n" + check,
                   text=True, encoding="utf-8", check=True)


if __name__ == "__main__":
    check_assets()
    check_refresh()
    print("Cleanup checks passed: shared player assets, signed pages, legacy restore and UI refresh.")
