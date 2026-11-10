#!/usr/bin/python3
"""Fixed Polkit entry point: commit one reviewed Debian archive selection."""
import json
import os
import sys
import fcntl
import stat
from pathlib import Path
from debian_releases import System, ReleaseError

try:
    if os.geteuid()!=0:raise ReleaseError('Administrator authorization is required.')
    # No caller-selected paths, root override, executable or environment option.
    if len(sys.argv)!=1:raise ReleaseError('Unsupported helper arguments.')
    request=json.loads(sys.stdin.buffer.readline(65537))
    if set(request)!={'release','fingerprint'}:raise ReleaseError('Invalid release review.')
    if not isinstance(request['release'],str) or not isinstance(request['fingerprint'],str):raise ReleaseError('Invalid release review.')
    lock=os.open('/run/lock/cutefish-app-center-debian.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW|os.O_CLOEXEC,0o600)
    try:
        info=os.fstat(lock)
        if info.st_uid!=0 or not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_mode & 0o022:raise ReleaseError('Unsafe source transaction lock.')
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        result=System().apply(request)
    finally:os.close(lock)
    print(json.dumps(dict(ok=True,**result)))
except Exception as error:
    print(json.dumps(dict(ok=False,error=str(error))))
    sys.exit(1)
