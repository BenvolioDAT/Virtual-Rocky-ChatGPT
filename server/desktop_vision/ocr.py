"""Optional, on-demand local OCR. Never runs in the Watch worker."""
import shutil
import subprocess
import os
from . import settings


def extract(jpeg):
    if not settings.SCREEN_OCR_ENABLED:
        return {'available':False,'reason':'Local OCR is disabled.'}
    executable=shutil.which('tesseract')
    if not executable:
        return {'available':False,'reason':'Install the optional Tesseract executable to use OCR.'}
    try:
        # Pipe bytes directly; Python OCR wrappers commonly create temporary image files.
        process=subprocess.run([executable,'stdin','stdout'],input=jpeg,stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL,timeout=3,check=True,
                               creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        text=process.stdout.decode('utf-8',errors='replace')
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return {'available':True,'text':'\n'.join(lines)[:settings.SCREEN_OCR_MAX_CHARS]}
    except Exception:
        return {'available':False,'reason':'Optional local OCR is unavailable; vision still works.'}
