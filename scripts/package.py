#!/usr/bin/python3
"""Package an already-built native executable without installing anything."""
import argparse
import os
import re
from pathlib import Path
import shutil
import subprocess
import tempfile

def check_runtime(binary):
 """Validate the built executable against the installed system libraries."""
 binary=binary.resolve(strict=True)
 dynamic=subprocess.run(['readelf','--dynamic','--wide',str(binary)],capture_output=True,text=True,check=True).stdout
 if not re.search(r'\(NEEDED\).*\[libstdc\+\+\.so\.6\]',dynamic):
  raise SystemExit('Packaging refused: the app must link directly to shared libstdc++.so.6. Rebuild in a fresh directory with the system g++ compiler and complete development packages; do not use a partial extracted compiler toolchain.')
 env={k:v for k,v in os.environ.items() if k not in ('LD_LIBRARY_PATH','LD_PRELOAD','LD_AUDIT','LD_DEBUG')}
 env.update(LC_ALL='C',LD_BIND_NOW='1')
 runtime=subprocess.run(['ldd','-r',str(binary)],capture_output=True,text=True,env=env)
 output=runtime.stdout+runtime.stderr
 if runtime.returncode or 'not found' in output or 'undefined symbol:' in output:
  raise SystemExit('Packaging refused: runtime dependencies do not resolve against the installed system libraries. Rebuild against the current Cutefish toolkit.\n'+output.strip())
 print('Runtime dependencies verified.')


parser=argparse.ArgumentParser()
parser.add_argument('binary',type=Path)
parser.add_argument('--check-only',action='store_true',help='Check runtime linkage without creating a package')
parser.add_argument('--output',type=Path,default=Path('cutefish-app-center_0.3.6_amd64.deb'))
args=parser.parse_args()
check_runtime(args.binary)
if args.check_only:raise SystemExit(0)
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
Version: 0.3.6
Architecture: amd64
Maintainer: Cutefish App Center contributors
Provides: cutefish-store (= 0.3.6)
Replaces: cutefish-store
Conflicts: cutefish-store
Section: admin
Priority: optional
Installed-Size: {size}
Depends: libc6 (>= 2.38), libgcc-s1, libstdc++6 (>= 14), cutefish-toolkit (>= 1.0~git20261102154148), python3, python3-gi, xdg-utils, squashfs-tools, util-linux, packagekit, libpackagekit-glib2-18, appstream (>= 1.0), gir1.2-appstream-1.0, gir1.2-flatpak-1.0 (>= 1.14), apt-config-icons
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
