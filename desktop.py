#!/usr/bin/env python3
"""Native macOS shell for Weekly Predictions."""
from __future__ import annotations

import threading

import server as product
import webview
from desktop_policy import install_policy


def run() -> None:
    backend = product.make_server(port=0)
    worker = threading.Thread(target=backend.serve_forever, name="decision-notebook-http", daemon=True)
    worker.start()
    url = f"http://127.0.0.1:{backend.server_port}/?desktop=1"
    try:
        install_policy(url)
        window = webview.create_window("Weekly Predictions", url, width=1080, height=760, min_size=(800, 580))
        if window is None:
            raise RuntimeError("Weekly Predictions window initialization was canceled")
        webview.start()
    finally:
        backend.shutdown()
        backend.server_close()
        worker.join(timeout=3)


if __name__ == "__main__":
    try:
        run()
    except Exception:
        import AppKit

        alert = AppKit.NSAlert.alloc().init()
        alert.setMessageText_("Weekly Predictions could not start")
        alert.setInformativeText_("The local app failed to open. Restart Weekly Predictions and try again.")
        alert.addButtonWithTitle_("OK")
        alert.runModal()
        raise SystemExit(1)
