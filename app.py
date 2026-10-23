"""
app.py — Web front end for the EE accessory-diagram formatter.

Run it (see run.bat) and open http://127.0.0.1:5000 in a browser. Drop one or
more "accessory connection diagram" PDFs onto the page; for each PDF it
produces two clean 65x90 mm JPG labels:

    <docid>-D.jpg   dual language (Chinese + English)
    <docid>-E.jpg   English only

Results are previewed in the browser, offered as downloads, and (by default)
written to the project's ``output\\output`` folder.

The conversion logic itself lives in convert.py. Everything runs locally —
nothing goes online or gets uploaded — so it is safe for sensitive drawings.

Routes:
  /                  the upload page
  /convert           receives uploaded PDFs, converts them via convert.py, returns JSON
  /download/<token>  downloads one label's full-resolution JPG
"""

from __future__ import annotations

import base64
import io
import os
import sys
import traceback
from collections import OrderedDict
from uuid import uuid4

from flask import Flask, jsonify, render_template, request, send_file

# From the conversion core: size/resolution constants + the conversion functions.
from convert import (
    TARGET_DPI,
    TARGET_H,
    TARGET_W,
    ConversionError,
    convert_pdf,
    derive_base_name,
    preview_jpeg_bytes,
    save_version,
    version_jpeg_bytes,
)


def resource_path(rel: str) -> str:
    """Absolute path to a bundled resource, in dev *and* in a PyInstaller exe.

    PyInstaller unpacks data files (templates/) into a temp dir exposed as
    ``sys._MEIPASS``; in a normal checkout it's just this file's folder.
    """
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)


def app_dir() -> str:
    """Folder the program lives in: the .exe's folder when frozen, else this file's."""
    if getattr(sys, "frozen", False):       # frozen=True means we're running as the packaged exe
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


# Create the Flask app; template_folder points at the templates (works when packaged too).
app = Flask(__name__, template_folder=resource_path("templates"))
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024 * 1024  # max 64 MB per request

# Where finished JPGs are written on disk. As a portable .exe, default to an
# "output" folder next to the program; in a dev checkout keep writing to the
# project's existing output\output so generated labels land by the originals.
if getattr(sys, "frozen", False):
    DEFAULT_SAVE_DIR = os.path.join(app_dir(), "output")
else:
    PROJECT_ROOT = os.path.dirname(app_dir())
    DEFAULT_SAVE_DIR = os.path.join(PROJECT_ROOT, "output", "output")

# In-memory cache of full-resolution JPGs so the browser "Download" button can
# fetch the high-res file without shipping the whole thing inline on the page.
# Bounded so a long session can't grow without limit; evicted links 404 and the
# user just re-converts. Keyed by a random token -> (filename, jpeg bytes).
_DOWNLOADS: "OrderedDict[str, tuple[str, bytes]]" = OrderedDict()
_DOWNLOADS_MAX = 100


def _cache_download(filename: str, data: bytes) -> str:
    """Store one full-resolution JPG in the cache and return its token (a random string)."""
    token = uuid4().hex
    _DOWNLOADS[token] = (filename, data)
    # Over the limit: evict the oldest first (popitem(last=False) removes the earliest insert).
    while len(_DOWNLOADS) > _DOWNLOADS_MAX:
        _DOWNLOADS.popitem(last=False)
    return token


@app.route("/")
def index():
    """Home page: render the upload page (index.html) with the output size info."""
    return render_template(
        "index.html",
        save_dir=DEFAULT_SAVE_DIR,
        target_w=TARGET_W,
        target_h=TARGET_H,
        target_dpi=TARGET_DPI,
    )


@app.route("/download/<token>")
def download(token: str):
    """Download one label at full resolution. The token comes from _cache_download above."""
    item = _DOWNLOADS.get(token)
    if item is None:        # Not found (probably evicted): ask the user to re-convert.
        return "Download link expired — please re-convert the file.", 404
    filename, data = item
    return send_file(
        io.BytesIO(data),
        mimetype="image/jpeg",
        as_attachment=True,         # download as an attachment (rather than opening in the browser)
        download_name=filename,     # filename used for the download
    )


@app.route("/convert", methods=["POST"])
def convert():
    """Accept uploaded PDFs, return JSON with previews + on-disk paths."""
    # From the form: the uploaded files, whether to save to disk, and the save folder.
    files = request.files.getlist("pdfs")
    save_to_disk = request.form.get("save_to_disk", "true").lower() == "true"
    save_dir = request.form.get("save_dir", DEFAULT_SAVE_DIR).strip() or DEFAULT_SAVE_DIR

    if not files or all(not f.filename for f in files):
        return jsonify({"error": "No PDF files were uploaded."}), 400

    # If saving, make sure the target folder exists first.
    if save_to_disk:
        try:
            os.makedirs(save_dir, exist_ok=True)
        except OSError as exc:
            return jsonify({"error": f"Cannot create save folder: {exc}"}), 400

    results = []
    for f in files:                  # process each uploaded PDF in turn
        if not f.filename:
            continue
        entry = {"source": f.filename, "base": derive_base_name(f.filename), "versions": [], "error": None}
        try:
            data = f.read()
            if not data:
                raise ConversionError("File is empty.")
            versions = convert_pdf(data)     # ← convert.py does the actual conversion, giving -D / -E
            for v in versions:
                jpg = version_jpeg_bytes(v)          # full-resolution JPG (for saving/downloading)
                out_name = f"{entry['base']}-{v.suffix}.jpg"   # output filename, e.g. xxx-D.jpg
                saved_path = None
                if save_to_disk:                     # write to disk if requested
                    saved_path = os.path.join(save_dir, out_name)
                    with open(saved_path, "wb") as fh:
                        fh.write(jpg)
                token = _cache_download(out_name, jpg)   # cache the full-res JPG for the Download button
                preview = preview_jpeg_bytes(v)      # small preview (embedded directly in the page, loads fast)
                entry["versions"].append({
                    "suffix": v.suffix,
                    "label": v.label,
                    "filename": out_name,
                    "saved_path": saved_path,
                    "size": list(v.image.size),      # full-res pixel size, e.g. [3071, 4252]
                    # the preview is embedded in the page's <img> as base64.
                    "preview": "data:image/jpeg;base64," + base64.b64encode(preview).decode("ascii"),
                    "download_url": f"/download/{token}",   # full-resolution download URL
                })
        except ConversionError as exc:
            entry["error"] = str(exc)                # expected error: show it to the user as-is
        except Exception as exc:  # pragma: no cover — defensive
            traceback.print_exc()                    # unexpected error: print the traceback for debugging
            entry["error"] = f"Unexpected error: {exc}"
        results.append(entry)

    # Return the results for all files together (JSON).
    return jsonify({"results": results, "saved": save_to_disk, "save_dir": save_dir})


# ---------------------------------------------------------------------------
# Double-click launch support: pick a port, wait for the server, open the browser.
# ---------------------------------------------------------------------------
def _find_free_port(preferred: int = 5000) -> int:
    """Return ``preferred`` if it is free, otherwise an OS-assigned free port."""
    import socket

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        try:
            s.bind(("127.0.0.1", preferred))     # try the preferred port
            return preferred
        except OSError:
            s.bind(("127.0.0.1", 0))             # 0 = let the OS pick a free port
            return s.getsockname()[1]
    finally:
        s.close()


def _try_open_browser(url: str) -> bool:
    """Open *url* in the default browser, trying a few mechanisms. True on success.

    Tries webbrowser → os.startfile (Windows) → the shell's "start", in that order
    (the browser sometimes failed to open automatically, hence the fallbacks).
    """
    import webbrowser

    try:
        if webbrowser.open(url):
            return True
    except Exception:
        pass
    # Windows shell association for http(s) URLs.
    try:
        os.startfile(url)  # type: ignore[attr-defined]  # Windows only
        return True
    except Exception:
        pass
    # Last resort: hand it to the shell's "start".
    try:
        import subprocess

        subprocess.Popen(["cmd", "/c", "start", "", url])
        return True
    except Exception:
        return False


def _open_when_ready(url: str, port: int, timeout: float = 20.0) -> None:
    """Wait until the local server accepts connections, then open the browser.

    Opening too early shows "can't connect", so keep retrying for up to *timeout* seconds.
    """
    import socket
    import time

    deadline = time.time() + timeout
    ready = False
    while time.time() < deadline:
        try:
            # a successful connection means the server is ready.
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                ready = True
                break
        except OSError:
            time.sleep(0.25)        # not up yet, wait a bit and retry
    # Server is up but the browser didn't open -> tell the user to copy the URL from the console.
    if ready and not _try_open_browser(url):
        print()
        print("  >>> Could not open a browser automatically.")
        print(f"  >>> Open this address yourself:  {url}")
        print()


def main() -> None:
    """Entry point: pick a port → wait and open the browser in the background → print instructions → start the server."""
    import threading

    port = _find_free_port(5000)
    url = f"http://127.0.0.1:{port}"

    # Open the browser only once the server is actually listening.
    # A background thread waits for the server, then opens the browser; the main thread starts the server.
    threading.Thread(target=_open_when_ready, args=(url, port), daemon=True).start()

    # Print instructions in the console window, with the URL clearly visible.
    bar = "=" * 60
    print(bar)
    print("  Diagram Label Formatter  -  running 100% locally")
    print(bar)
    print(f"   OPEN THIS LINK:   {url}")
    print("   (it should open automatically; if not, copy the line")
    print("    above into your browser's address bar)")
    print(bar)
    print(f"  JPGs save to: {DEFAULT_SAVE_DIR}")
    print(f"  Output size:  {TARGET_W} x {TARGET_H} px  ({TARGET_DPI} dpi, 65 x 90 mm)")
    print("  Keep this window open while you work.")
    print("  Close it (or press Ctrl+C) to stop the converter.")
    print(bar)

    # threaded so multiple file conversions in one request stay responsive.
    # Binds to 127.0.0.1 only, so nothing outside this computer can reach it.
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
