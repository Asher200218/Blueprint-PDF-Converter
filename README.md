# Diagram Label Formatter (PDF Converter)

A small local web app that turns a *less-formatted* **accessory connection diagram** PDF (a CAD-exported wiring diagram sheet) into two clean, print-ready JPG labels:

| Output | Suffix | Contents |
|--------|--------|----------|
| `<docid>-D.jpg` | **D** | Dual language: Chinese **and** English sub-notes |
| `<docid>-E.jpg` | **E** | English only |

Each label is a **65 × 90 mm JPEG at 1200 dpi (3071 × 4252 px)**, rendered straight from the PDF's vector content for maximum clarity.

Everything runs on your own computer. The server only listens on `127.0.0.1`, uses no cloud services, and loads no external fonts or scripts, so your PDFs never leave the machine.

## How it works

A source sheet already contains **both** diagrams (one with Chinese sub-notes, one English-only). The tool:

1. finds the two matched, equal-sized diagram boxes on the page (works whether they are stacked, side by side, or on a rotated page);
2. decides which is which by detecting Chinese characters: that one becomes `-D`, the other `-E`;
3. crops each one out of the cluttered title-block sheet;
4. rotates it upright to portrait (landscape diagrams are turned 90° clockwise);
5. fits it onto a clean 65 × 90 mm white label and exports a crisp JPG.

## Run it

### Option A: standalone `.exe` (Windows, no Python needed)

The exe isn't stored in this repository. Build it once on a Windows PC by double-clicking **`build_exe.bat`**. It installs PyInstaller and the dependencies, then writes **`dist\DiagramLabelFormatter.exe`**.

Double-click the exe. A small console window opens, your browser opens automatically, and you can start dropping PDFs. Everything (PDF engine, image processing, web UI) is bundled into that one file, so it needs no Python install and no internet connection.

* **Moving it:** you can copy that single `.exe` anywhere: the Desktop, another PC, a USB stick.
* **Where JPGs go:** generated JPGs save to an **`output`** folder created next to the `.exe`. You can change the folder in the page's options bar.
* **Stopping it:** keep the console window open while you work; close it (or press Ctrl+C) to stop.

### Option B: run from Python source

On Windows, double-click **`run.bat`**. It installs the dependencies the first time, starts the server and opens your browser at <http://127.0.0.1:5000>.

Or manually (any OS):

```bash
pip install -r requirements.txt
python app.py
```

Then open <http://127.0.0.1:5000>. If port 5000 is busy, the app picks another free port and prints the address in the console.

## Use it

1. Drag one or more PDFs onto the page (or click to browse).
2. Each file shows its `-D` and `-E` previews side by side.
3. Download a label at full resolution, or let it auto-save.

You can change the save folder, or untick *Save JPGs to folder*, in the options bar. When run from source, the default folder is `output/output` in the folder **above** this project.

## Files

| File | Purpose |
|------|---------|
| `convert.py` | Core conversion logic (no web dependencies, so it can be imported and tested on its own) |
| `app.py` | Flask web server: the upload page, `/convert` and `/download` |
| `templates/index.html` | Drag-and-drop UI |
| `run.bat` | One-click launcher (runs from Python source) |
| `build_exe.bat` | Builds the standalone `dist\DiagramLabelFormatter.exe` with PyInstaller |
| `DiagramLabelFormatter.spec` | PyInstaller build spec |
| `_validate.py` | Dev helper: re-runs the conversion on the sample PDFs in `../Converter Data/input/input` and saves the results to `_validate_out/` |
| `requirements.txt` | Python dependencies (Flask, PyMuPDF, Pillow) |

## Notes and limitations

* **Vector PDFs only:** designed for **vector** connection diagrams (the usual CAD export). A PDF that is just a flat scanned image won't be detected; you get a clear error instead.
* **Output file names:** the output name comes from the input name with any trailing revision letter (e.g. `_A`) removed: `DWG1234567-105_A.pdf` → `DWG1234567-105-D.jpg` / `-E.jpg`. Rename inputs if you need a different base.
* **Rotation direction:** landscape diagrams are turned 90° clockwise, which matches the established output convention. If a future diagram type needs the other direction, adjust `_render_box` in `convert.py`.
* **Ambiguous diagrams:** if both boxes (or neither) contain Chinese, the first box in reading order becomes `-D` and the second `-E`.
* **First run of the `.exe`:** because the program is unsigned, Windows SmartScreen may show *"Windows protected your PC"*. Click **More info → Run anyway** (one time). Some antivirus tools also flag freshly built PyInstaller `.exe`s as a false positive.
