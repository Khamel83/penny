#!/usr/bin/env python3
"""Start Penny only on the enrolled SSD; open logs after Python has started."""
import os
from pathlib import Path
import plistlib
import subprocess
import sys


def main():
    try:
        volume = Path(os.environ['COMPOST_STORAGE_VOLUME'])
        expected = os.environ['COMPOST_STORAGE_UUID']
        if not expected or not volume.is_absolute() or volume.is_symlink() or not volume.is_mount():
            raise ValueError('storage_volume_unavailable')
        info = plistlib.loads(subprocess.check_output(
            ['/usr/sbin/diskutil', 'info', '-plist', str(volume)], timeout=10))
        if info.get('MountPoint') != str(volume) or info.get('VolumeUUID') != expected:
            raise ValueError('storage_volume_identity_mismatch')
        runtime = Path(os.environ['PENNY_RUNTIME_ROOT']).resolve(strict=True)
        log = Path(os.environ['PENNY_RUNTIME_LOG']).resolve(strict=True)
        runtime.relative_to(volume)
        log.relative_to(volume)
        if len(sys.argv) < 2 or not Path(sys.argv[1]).is_absolute():
            raise ValueError('absolute_command_required')
        os.chdir(runtime)
        fd = os.open(log, os.O_WRONLY | os.O_APPEND)
        os.dup2(fd, 1)
        os.dup2(fd, 2)
        if fd > 2:
            os.close(fd)
    except (KeyError, ValueError, OSError, subprocess.SubprocessError, plistlib.InvalidFileException):
        print('Penny blocked: enrolled SSD or runtime unavailable', file=sys.stderr)
        return 75
    os.execv(sys.argv[1], sys.argv[1:])


if __name__ == '__main__':
    raise SystemExit(main())
