#!/bin/bash
set -e
set -euo pipefail
mkdir -p /task/outputs /tmp/exp
for f in /task/inputs/*.jpg; do
  b=$(basename "$f" .jpg)
  cat > /tmp/s.jsonl <<JSON
{"command":"preset.apply","params":{"id":"lc.golden-hour","amount":100}}
{"command":"app.export","params":{"path":"/tmp/exp/$b.jpg","longEdge":1600,"quality":90,"format":"jpeg"}}
JSON
  lightcraft-cli run --import "$f" --script /tmp/s.jsonl
done
cd /tmp/exp && python3 -c "import zipfile,glob; z=zipfile.ZipFile('/task/outputs/exported.zip','w'); [z.write(f) for f in sorted(glob.glob('*.jpg'))]"
montage /tmp/exp/*.jpg -tile 2x2 -geometry 600x600+8+8 /tmp/sheet.jpg
python3 - <<'PY'
from pathlib import Path
import subprocess
jp = Path('/tmp/sheet.jpg').read_bytes()
w, h = map(int, subprocess.run(['identify', '-format', '%w %h', '/tmp/sheet.jpg'], capture_output=True, text=True).stdout.split())
content = b'q %d 0 0 %d 0 0 cm /Im0 Do Q' % (w, h)
objs = [b'<< /Type /Catalog /Pages 2 0 R >>', b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
        b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] /Resources << /XObject << /Im0 5 0 R >> >> /Contents 4 0 R >>' % (w, h),
        b'<< /Length %d >>\nstream\n' % len(content) + content + b'\nendstream',
        b'<< /Type /XObject /Subtype /Image /Width %d /Height %d /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length %d >>\nstream\n' % (w, h, len(jp)) + jp + b'\nendstream']
buf = bytearray(b'%PDF-1.4\n'); offs = []
for i, o in enumerate(objs, 1):
    offs.append(len(buf)); buf += b'%d 0 obj\n' % i + o + b'\nendobj\n'
x = len(buf); buf += b'xref\n0 %d\n0000000000 65535 f \n' % (len(objs) + 1)
for o in offs: buf += b'%010d 00000 n \n' % o
buf += b'trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n' % (len(objs) + 1, x)
Path('/task/outputs/contact_sheet.pdf').write_bytes(bytes(buf))
PY
