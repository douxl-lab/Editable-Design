"""Render the audited final PPTX with explicit host-bundled tools only."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

from PIL import Image


def render(pptx, reconstruction, output, reject, audit):
    source = Path(pptx).absolute()
    native = audit(source, reconstruction)
    root = Path(output).absolute()
    if root.exists() or root.is_symlink() or any(p.is_symlink() for p in root.parents):
        raise reject("Rendering needs a new ordinary evidence folder")
    bin_dir = os.environ.get("RUNTIME_BIN_DIR")
    if not bin_dir or not Path(bin_dir).is_absolute():
        raise reject("Set explicit absolute RUNTIME_BIN_DIR to the host bundled renderer")
    def resolve(names):
        for name in names:
            p = Path(bin_dir) / name
            if p.is_file():
                return str(p)
        raise reject("Required bundled renderer not found: " + names[0])
    soffice = resolve(["soffice", "libreoffice/program/soffice", "soffice.exe", "libreoffice/program/soffice.exe"])
    pdftoppm = resolve(["pdftoppm", "pdftoppm.exe"])
    root.mkdir(parents=True)
    receipt = {"pptx_sha256": native["pptx_sha256"], "native_object_verified": True,
               "final_pptx_render_verified": False, "visual_review": "pending", "renderer": soffice}
    try:
        with tempfile.TemporaryDirectory(prefix="paper-fig-lo-", dir=root) as profile:
            command = [soffice, "-env:UserInstallation=" + Path(profile).as_uri(), "--headless",
                       "--convert-to", "pdf", "--outdir", str(root), str(source)]
            result = subprocess.run(command, capture_output=True, text=True, timeout=120)
            if result.returncode != 0:
                raise reject("Bundled LibreOffice failed: " + result.stderr[-2000:])
        pdf = root / (source.stem + ".pdf")
        if not pdf.is_file() or pdf.stat().st_size < 100:
            raise reject("Renderer returned no real PDF; no success claim recorded")
        import fitz
        with fitz.open(pdf) as document:
            if len(document) != 1:
                raise reject("Final PDF page count differs from the one-page figure")
        result = subprocess.run([pdftoppm, "-png", "-r", "144", "-singlefile", str(pdf), str(root / "slide-1")],
                                capture_output=True, text=True, timeout=120)
        image = root / "slide-1.png"
        if result.returncode or not image.is_file():
            raise reject("Bundled PDF rasterizer failed")
        with Image.open(image) as im:
            im.load()
            receipt["render_size_px"] = list(im.size)
        receipt.update(final_pptx_render_verified=True,
                       pdf_sha256=hashlib.sha256(pdf.read_bytes()).hexdigest(),
                       preview_sha256=hashlib.sha256(image.read_bytes()).hexdigest(),
                       preview_file=image.name, pdf_file=pdf.name)
    except Exception as exc:
        receipt["error"] = str(exc)
        raise
    finally:
        (root / "render-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt
