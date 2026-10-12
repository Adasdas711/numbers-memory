"""Keep offline cache version tied to released application files."""
from pathlib import Path
import hashlib
import re
import sys
root=Path(__file__).resolve().parents[1]
assets=['index.html','features.js','features.css','manifest.webmanifest','icons/icon-192.png','icons/icon-512.png']
h=hashlib.sha256()
for name in assets:
    h.update(name.encode()); h.update((root/name).read_bytes())
version='numbers-memory-'+h.hexdigest()[:16]
p=root/'sw.js'; original=p.read_text()
updated=re.sub(r"const CACHE = '[^']+';",f"const CACHE = '{version}';",original,count=1)
if '--check' in sys.argv:
    if updated!=original:
        sys.exit('Offline assets changed: run python3 tools/update-pwa-cache.py and commit sw.js.')
else:
    p.write_text(updated)
    print(version)
