"""Capture stage owner. IPC EOF/parent death removes the pinned-directory stage.

The guardian allocates the file itself, transfers its open descriptor, and stays
alive until the entire caller transaction ends. No pathname cleanup is trusted.
"""
import array
import os
from pathlib import Path
import select
import signal
import socket
import sys
import uuid


def run(owner, directory, channel):
    name = None
    descriptor = None
    try:
        if os.getppid() != owner:
            return
        name = '.capture-' + uuid.uuid4().hex
        descriptor = os.open(name, os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_NOFOLLOW,
                             0o600, dir_fd=directory)
        channel.sendmsg([name.encode()], [(socket.SOL_SOCKET, socket.SCM_RIGHTS,
                                          array.array('i', [descriptor]))])
        while os.getppid() == owner:
            if select.select([channel], [], [], .05)[0]:
                if channel.recv(1) in (b'', b'D'):
                    break
    finally:
        if name is not None:
            try:
                os.unlink(name, dir_fd=directory)
            except FileNotFoundError:
                pass
        if descriptor is not None:
            os.close(descriptor)
        os.close(directory)
        channel.close()


if __name__ == '__main__':
    # Catchable parent termination is delivered through IPC closure; don't let a
    # process-group signal interrupt the guardian's unlink responsibility.
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, signal.SIG_IGN)
    run(int(sys.argv[1]), int(sys.argv[2]), socket.socket(fileno=int(sys.argv[3])))
