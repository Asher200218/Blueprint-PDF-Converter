"""Run convert_pdf on every sample input and save results to _validate_out/.

A test/validation script: converts every sample PDF and saves the results to the
_validate_out folder so they can be compared with hand-made samples. Run it after
changing convert.py.  Usage (from this folder):  py _validate.py
"""
import glob, os, sys

# Let Python find convert.py in this same folder.
sys.path.insert(0, os.path.dirname(__file__))
from convert import convert_pdf, save_version, derive_base_name

# Project root (two levels up from this file):  ...\python coding
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Folder with the sample PDFs (the data lives under Converter Data). Change this to use another data set.
INPUT_DIR = os.path.join(ROOT, "Converter Data", "input", "input")
# Output folder (_validate_out next to this file), created if missing.
OUT = os.path.join(os.path.dirname(__file__), "_validate_out")
os.makedirs(OUT, exist_ok=True)

# Read each PDF -> convert -> save as JPG, printing one line per result.
for f in sorted(glob.glob(os.path.join(INPUT_DIR, "*.pdf"))):
    base = derive_base_name(f)              # output filename base, e.g. DWG1234567-105
    with open(f, "rb") as fh:
        data = fh.read()
    versions = convert_pdf(data)            # gives the -D / -E versions
    for v in versions:
        out = os.path.join(OUT, f"{base}-{v.suffix}.jpg")
        save_version(v, out)                # save as a high-clarity JPG
        print(f"{os.path.basename(f):28s} -> {os.path.basename(out):24s} [{v.label}] {v.image.size}")
print("DONE ->", OUT)
