"""Exercise real browser/worker handoff with fixture cookies and no external login."""
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import iqcom_session as login


def wait_until(predicate):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.05)
    raise AssertionError("Login fixture did not reach the expected state")


# No website, real credentials or user's normal browser profile is accessed.
with tempfile.TemporaryDirectory(prefix="iqcom-login-check-", ignore_cleanup_errors=True) as temporary:
    session = login.IqcomSession(Path(temporary) / "selected-profile")
    session.source = "existing-browser-source-123"
    session.browser_cookies = [{"name": "I00001", "value": "old-fixture", "domain": ".iq.com", "path": "/"}]
    options = login.browser_launch_options(True)
    try:
        with patch.object(login, "LOGIN_URL", "about:blank"), patch.object(login, "browser_launch_options", return_value=options):
            session.start_login()
            wait_until(lambda: session.login_page is not None and "cửa sổ vừa mở" in session.status()["message"])
            assert session.status()["loginPending"] and not session.status()["connected"]
            assert session.pool.submit(lambda: session.login_context.cookies()).result(timeout=10) == []
            fixture = [{"name": name, "value": value, "domain": ".iq.com", "path": "/", "httpOnly": True,
                        "secure": True, "sameSite": "Lax"} for name, value in (("I00001", "new-fixture"), ("I00019", "1"))]
            session.pool.submit(lambda: session.login_context.add_cookies(fixture)).result(timeout=10)
            wait_until(lambda: session.status()["connected"] and not session.status()["loginPending"])
            session.pool.submit(lambda: None).result(timeout=15)
            assert session.source != "existing-browser-source-123"
            assert session.login_browser is None and session.login_context is None
            saved = session.pool.submit(lambda: session.context.cookies("https://www.iq.com/")).result(timeout=10)
            assert next(row["value"] for row in saved if row["name"] == "I00001") == "new-fixture"
    finally:
        session.close()
print("PASS: fresh browser starts empty; new login is detected, selected and saved; login window closes on its own")
