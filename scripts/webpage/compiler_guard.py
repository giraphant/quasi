"""Private compiler supervisor: owns temporary files and survives caller death.

Never retries. The only publish is an atomic replace after a successful compile,
and only while the requesting parent is still alive.
"""
import base64
import json
import os
from pathlib import Path
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time


def stop(child):
    for sig, seconds in ((signal.SIGTERM, .2), (signal.SIGKILL, .2)):
        try:
            os.killpg(child.pid, sig)
        except OSError:
            pass
        try:
            child.communicate(timeout=seconds)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass
    for pipe in (child.stdout, child.stderr):
        if pipe:
            try:
                pipe.close()
            except OSError:
                pass
    try:
        child.wait(timeout=.2)
    except subprocess.TimeoutExpired:
        pass


def run(job, owner):
    child = None
    directory = None
    def cancelled(*_args):
        raise SystemExit(1)
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, cancelled)
    try:
        if os.getppid() != owner:
            raise SystemExit(1)
        if job['mode'] == 'compile':
            binary = Path(job['binary'])
            previous = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGTERM, signal.SIGINT, signal.SIGHUP})
            try:
                directory = tempfile.mkdtemp(prefix='.compile-', dir=binary.parent)
            finally:
                signal.pthread_sigmask(signal.SIG_SETMASK, previous)
            source = Path(directory) / 'source.swift'
            stage = Path(directory) / 'binary'
            source.write_bytes(base64.b64decode(job['source'], validate=True))
            with source.open('rb') as stream:
                os.fsync(stream.fileno())
            args = [job['compiler'], *job['flags'], str(source), '-o', str(stage)]
        else:
            args = [job['compiler'], '--version']
        child = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 text=True, start_new_session=True, env=job.get("environment", {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LC_ALL": "C"}))
        deadline = time.monotonic() + (300 if job['mode'] == 'compile' else 10)
        while True:
            if os.getppid() != owner or time.monotonic() >= deadline:
                raise SystemExit(1)
            try:
                stdout, stderr = child.communicate(timeout=.1)
                break
            except subprocess.TimeoutExpired:
                pass
        if child.returncode != 0:
            raise ValueError('compiler failed')
        if job['mode'] == 'version':
            return {'version': stdout.strip()}
        info = stage.lstat()
        if not stat.S_ISREG(info.st_mode) or not info.st_size or not os.access(stage, os.X_OK):
            raise ValueError('compiler did not produce an executable')
        with stage.open('rb') as stream:
            os.fsync(stream.fileno())
        if os.getppid() != owner:
            raise SystemExit(1)
        os.replace(stage, binary)
        descriptor = os.open(binary.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return {'binary': str(binary)}
    finally:
        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            signal.signal(sig, signal.SIG_IGN)
        try:
            if child is not None:
                stop(child)
        finally:
            if directory:
                shutil.rmtree(directory)


if __name__ == '__main__':
    try:
        result = run(json.loads(sys.stdin.read()), int(sys.argv[1]))
        print(json.dumps(result))
    except Exception:
        print('compiler job failed', file=sys.stderr)
        sys.exit(1)
