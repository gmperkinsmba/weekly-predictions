import plistlib
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

import server
from desktop_policy import navigation_policy
from build_desktop import APP_NAME, BUNDLE_ID, OWNER_MARKER, owned_bundle


class DesktopTests(unittest.TestCase):
    def test_bundle_ownership_requires_exact_id_and_marker(self):
        with tempfile.TemporaryDirectory() as temp:
            bundle = Path(temp) / f"{APP_NAME}.app"
            resources = bundle / "Contents" / "Resources"
            resources.mkdir(parents=True)
            with (bundle / "Contents" / "Info.plist").open("wb") as stream:
                plistlib.dump({"CFBundleIdentifier": BUNDLE_ID}, stream)
            (resources / OWNER_MARKER.name).write_bytes(OWNER_MARKER.read_bytes())
            self.assertTrue(owned_bundle(bundle))
            (resources / OWNER_MARKER.name).write_text("another app", encoding="utf-8")
            self.assertFalse(owned_bundle(bundle))

    def test_native_navigation_allows_only_owned_origin_and_blob_downloads(self):
        origin = "http://127.0.0.1:49125/"
        self.assertEqual(navigation_policy(origin, origin, False, False), "allow")
        self.assertEqual(navigation_policy(origin + "app.js", origin, False, False), "allow")
        self.assertEqual(navigation_policy("blob:" + origin + "export", origin, False, True), "download")
        for url in ("file:///etc/passwd", "javascript:alert(1)", "data:text/html,hello", "http://127.0.0.1:49126/", "http://127.0.0.1.evil.test:49125/"):
            self.assertEqual(navigation_policy(url, origin, False, False), "cancel")
        self.assertEqual(navigation_policy("https://example.com", origin, True, False), "external")
        self.assertEqual(navigation_policy("https://example.com", origin, False, False), "cancel")

    def test_ephemeral_backend_serves_desktop_page_and_stops_cleanly(self):
        with patch("socket.getfqdn", side_effect=AssertionError("Reverse DNS must not run")):
            backend = server.make_server(port=0)
        worker = threading.Thread(target=backend.serve_forever, daemon=True)
        worker.start()
        base = f"http://127.0.0.1:{backend.server_port}"
        try:
            with urlopen(base + "/?desktop=1", timeout=3) as response:
                page = response.read().decode()
                self.assertEqual(response.status, 200)
            self.assertIn('<body class="desktop">', page)
            self.assertIn('window.REQUEST_TOKEN="', page)
            req = Request(base + "/", headers={"Host": "127.0.0.1:1"})
            with self.assertRaises(HTTPError) as failure:
                urlopen(req, timeout=3)
            self.assertEqual(failure.exception.code, 403)
            failure.exception.close()
        finally:
            backend.shutdown()
            backend.server_close()
            worker.join(timeout=3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(backend.fileno(), -1)


if __name__ == "__main__":
    unittest.main()
