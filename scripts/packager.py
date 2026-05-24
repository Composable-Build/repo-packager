#!/usr/bin/env python3
import json, tarfile, shutil, sys
from pathlib import Path

manifest_path = Path(sys.argv[1] if len(sys.argv) > 1 else "config/manifest.json")
work = Path("work/app")
outdir = Path("output")

outdir.mkdir(exist_ok=True, parents=True)
if work.exists(): shutil.rmtree(work)
for d in ["bin", "libs", "conf"]: (work / d).mkdir(parents=True)

data = json.loads(manifest_path.read_text())

errors = 0
for kind, dest in [("binaries", "bin"), ("libs", "libs"), ("configs", "conf")]:
    for item in data.get(kind, []):
        src = Path(item["path"])
        if src.exists():
            shutil.copy2(src, work / dest / src.name)
            print(f"  [{dest:4s}] {src.name}")
        else:
            print(f"  [ERROR] not found: {src}", file=sys.stderr)
            errors += 1

if errors:
    sys.exit(1)

tar_path = outdir / "app.tar.gz"
with tarfile.open(tar_path, "w:gz") as tf:
    tf.add(work, arcname="app")
print(f"\ncreated {tar_path}")
