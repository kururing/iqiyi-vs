import importlib.util
import tempfile
from pathlib import Path
spec = importlib.util.spec_from_file_location('apply_vi', 'apply-vi.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    webapp = root / 'webapp'
    webapp.mkdir()
    m.BACKUP_LWA = root / 'backup'
    backup = m.lwa_backup_dir(m.BACKUP_LWA, webapp)
    backup.mkdir(parents=True)
    original = b'\xef\xbb\xbf<html><head></head><body>original</body></html>\r\n'
    (backup / 'compactPlayer.html').write_bytes(original)
    (webapp / 'compactPlayer.html').write_text('patched')
    (webapp / 'index.html').write_bytes(original)
    (webapp / 'other.html').write_text('<html><head></head></html>')
    m.inject_lwa_dir(webapp, '/* test */')
    assert (webapp / 'compactPlayer.html').read_bytes() == original
    assert (webapp / 'index.html').read_bytes() == original
    assert 'lwa-vi.js' in (webapp / 'other.html').read_text()
    m.inject_lwa_dir(webapp, '/* test */')
    assert (webapp / 'compactPlayer.html').read_bytes() == original
print('PASS: signed pages restored byte-for-byte, unsigned pages still injected')
