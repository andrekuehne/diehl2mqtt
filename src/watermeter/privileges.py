"""Drop app privileges after reading Supervisor-owned configuration.

HAOS USB nodes normally belong to root:root with group write access. GID 0
allows libusb to open them across reconnects without changing host ownership;
the receiver runs with a non-root UID and no Linux capabilities.
"""
import ctypes
import os
from pathlib import Path

from .settings import ConfigError

APP_UID = 10001
APP_GID = 0


def drop_privileges():
    """Irreversibly reduce this process and every future child; fail closed."""
    try:
        libc = ctypes.CDLL(None, use_errno=True)

        def prctl(option, value=0):
            if libc.prctl(option, value, 0, 0, 0) != 0:
                raise OSError(ctypes.get_errno(), 'prctl failed')

        # Never acquire privileges through setuid files or file capabilities.
        prctl(38, 1)  # PR_SET_NO_NEW_PRIVS
        prctl(8, 0)  # PR_SET_KEEPCAPS
        if os.getuid() == 0:
            # Dropping the bounding set does not remove the effective SETUID/
            # SETGID capabilities until the UID change below.
            last = int(Path('/proc/sys/kernel/cap_last_cap').read_text())
            for cap in range(last + 1):
                prctl(24, cap)  # PR_CAPBSET_DROP
            os.setgroups([])
            os.setgid(APP_GID)
            os.setuid(APP_UID)
        # Explicitly clear inheritable/permitted/effective sets as well.
        header = (ctypes.c_uint32 * 2)(0x20080522, 0)  # _LINUX_CAPABILITY_VERSION_3
        data = (ctypes.c_uint32 * 6)()
        if libc.capset(ctypes.byref(header), ctypes.byref(data)) != 0:
            raise OSError(ctypes.get_errno(), 'capset failed')
        state = dict(line.split(':', 1) for line in Path('/proc/self/status').read_text().splitlines() if ':' in line)
        if (os.getuid() != APP_UID or os.getgid() != APP_GID or os.getgroups()
                or any(int(state[k].strip(), 16) for k in ('CapInh', 'CapPrm', 'CapEff', 'CapAmb', 'CapBnd'))):
            raise ValueError('Privileges remain')
        if state['NoNewPrivs'].strip() != '1':
            raise ValueError('Privilege escalation remains enabled')
    except (OSError, ValueError, KeyError):
        raise ConfigError('Cannot safely drop app runtime privileges') from None


def healthcheck():
    from .health import healthy
    try:
        drop_privileges()
        return 0 if healthy(Path('/tmp/watermeter')) else 1
    except ConfigError:
        return 1


if __name__ == '__main__':
    raise SystemExit(healthcheck())
