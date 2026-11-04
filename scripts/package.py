#!/usr/bin/python3
"""Package an already-built native executable without installing anything."""
import argparse
from pathlib import Path
import shutil
import subprocess
import tempfile

parser=argparse.ArgumentParser()
parser.add_argument('binary',type=Path)
parser.add_argument('--output',type=Path,default=Path('cutefish-app-center_0.2.1_amd64.deb'))
args=parser.parse_args()
source=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='cutefish-app-center-package-') as temp:
 root=Path(temp)
 def copy(src,dest,executable=False):
  dst=root/dest;dst.parent.mkdir(parents=True,exist_ok=True)
  shutil.copyfile(src,dst);dst.chmod(0o755 if executable else 0o644)
 copy(args.binary,'usr/bin/cutefish-app-center',True)
 copy(source/'backend/app_center_backend.py','usr/libexec/cutefish-app-center/app_center_backend.py',True)
 copy(source/'data/org.cutefish.AppCenter.desktop','usr/share/applications/org.cutefish.AppCenter.desktop')
 copy(source/'data/org.cutefish.AppCenter.svg','usr/share/icons/hicolor/scalable/apps/org.cutefish.AppCenter.svg')
 copy(source/'data/org.cutefish.AppCenter.metainfo.xml','usr/share/metainfo/org.cutefish.AppCenter.metainfo.xml')
 copy(source/'data/branding.json','usr/share/cutefish-app-center/branding.json')
 copy(source/'LICENSE','usr/share/doc/cutefish-app-center/copyright')
 copy(source/'README.md','usr/share/doc/cutefish-app-center/README.md')
 size=sum(p.stat().st_size for p in root.rglob('*') if p.is_file())//1024
 (root/'DEBIAN').mkdir()
 (root/'DEBIAN/control').write_text(f'''Package: cutefish-app-center
Version: 0.2.1
Architecture: amd64
Maintainer: Cutefish App Center contributors
Provides: cutefish-store (= 0.2.1)
Replaces: cutefish-store
Conflicts: cutefish-store
Section: admin
Priority: optional
Installed-Size: {size}
Depends: libc6 (>= 2.38), libgcc-s1, libstdc++6 (>= 14), cutefish-toolkit (>= 1.0~git20261102154148), python3, python3-gi, xdg-utils, squashfs-tools, util-linux, packagekit, libpackagekit-glib2-18, appstream (>= 1.0), gir1.2-appstream-1.0, apt-config-icons
Recommends: flatpak, snapd, libfuse2t64
Description: Native software manager for the current Cutefish desktop
 Initial prototype for Debian 13. Manages Debian packages through PackageKit,
 Flatpak and Snap apps through their own providers, and imported AppImages.
''')
 root.chmod(0o755)
 for directory in root.rglob("*"):
  if directory.is_dir():directory.chmod(0o755)
 args.output.parent.mkdir(parents=True,exist_ok=True)
 subprocess.run(['dpkg-deb','--root-owner-group','--build',str(root),str(args.output)],check=True)
