#!/usr/bin/python3
"""Package an already-built native executable without installing anything."""
import argparse
from pathlib import Path
import shutil
import subprocess
import tempfile

parser=argparse.ArgumentParser()
parser.add_argument('binary',type=Path)
parser.add_argument('--output',type=Path,default=Path('cutefish-store_0.1.1_amd64.deb'))
args=parser.parse_args()
source=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='cutefish-store-package-') as temp:
 root=Path(temp)
 def copy(src,dest,executable=False):
  dst=root/dest;dst.parent.mkdir(parents=True,exist_ok=True)
  shutil.copyfile(src,dst);dst.chmod(0o755 if executable else 0o644)
 copy(args.binary,'usr/bin/cutefish-store',True)
 copy(source/'backend/store_backend.py','usr/libexec/cutefish-store/store_backend.py',True)
 copy(source/'data/org.cutefish.Store.desktop','usr/share/applications/org.cutefish.Store.desktop')
 copy(source/'data/org.cutefish.Store.svg','usr/share/icons/hicolor/scalable/apps/org.cutefish.Store.svg')
 copy(source/'data/org.cutefish.Store.metainfo.xml','usr/share/metainfo/org.cutefish.Store.metainfo.xml')
 copy(source/'data/branding.json','usr/share/cutefish-store/branding.json')
 copy(source/'LICENSE','usr/share/doc/cutefish-store/copyright')
 copy(source/'README.md','usr/share/doc/cutefish-store/README.md')
 size=sum(p.stat().st_size for p in root.rglob('*') if p.is_file())//1024
 (root/'DEBIAN').mkdir()
 (root/'DEBIAN/control').write_text(f'''Package: cutefish-store
Version: 0.1.1
Architecture: amd64
Maintainer: Cutefish Store contributors
Section: admin
Priority: optional
Installed-Size: {size}
Depends: libc6 (>= 2.38), libgcc-s1, libstdc++6 (>= 14), cutefish-toolkit (>= 1.0~git20261102154148), python3, python3-gi, xdg-utils, packagekit, libpackagekit-glib2-18
Recommends: flatpak, snapd
Suggests: appstream, libfuse2t64
Description: Native software manager for the current Cutefish desktop
 Initial prototype for Debian 13. Manages Debian packages through PackageKit,
 Flatpak and Snap apps through their own providers, and imported AppImages.
''')
 root.chmod(0o755)
 for directory in root.rglob("*"):
  if directory.is_dir():directory.chmod(0o755)
 args.output.parent.mkdir(parents=True,exist_ok=True)
 subprocess.run(['dpkg-deb','--root-owner-group','--build',str(root),str(args.output)],check=True)
