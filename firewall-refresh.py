#!/usr/bin/env python3
"""非特権で定期更新を監視し、容量制限付きログと診断状態を保存する。"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import selectors
import stat
import subprocess
import sys
import tempfile
import time
from time import sleep as pause

DIRECTORY = Path('/tmp/claude-firewall-refresh')
LOG_BYTES = 256 * 1024
STALE_SECONDS = 60


def prepare_directory(directory):
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if directory.is_symlink() or directory.stat().st_uid != os.getuid():
        raise OSError('診断ディレクトリの所有者または種類が不正です')
    directory.chmod(0o700)


@contextmanager
def writer_lock(directory):
    # 診断ディレクトリを清掃・再作成しても同じ inode のロックを保持する。
    path = directory.with_name(directory.name + '.lock')
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'a') as lock:
        info = os.fstat(lock.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise OSError('監視ロックの種類または所有者が不正です')
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


class BoundedLog:
    def __init__(self, directory):
        self.path = directory / 'refresh.log'
        self.previous = directory / 'refresh.log.1'

    def write(self, data):
        # 再起動時も既存の各世代を上限内へ収める。
        for path in (self.path, self.previous):
            if path.exists() and path.stat().st_size > LOG_BYTES:
                with path.open('rb') as stream:
                    stream.seek(-LOG_BYTES, os.SEEK_END)
                    tail = stream.read(LOG_BYTES)
                path.write_bytes(tail)

        while data:
            size = self.path.stat().st_size if self.path.exists() else 0
            if size >= LOG_BYTES:
                self.path.replace(self.previous)
                size = 0
            chunk, data = data[:LOG_BYTES - size], data[LOG_BYTES - size:]
            with self.path.open('ab') as stream:
                stream.write(chunk)


class Monitor:
    heartbeat_interval = 5

    def __init__(self, directory, command):
        self.directory = directory
        self.command = command
        self.log = BoundedLog(directory)
        self.state = dict(pid=os.getpid(), started_at=time.time(), phase='waiting',
                          result='not_run', last_attempt_at=None, last_completed_at=None,
                          last_success_at=None, consecutive_failures=0, last_failure=None,
                          diagnostic_errors={}, last_diagnostic_error=None)
        self.save()

    def diagnostic_error(self, operation, error):
        summary = str(error)[-1024:]
        self.state['diagnostic_errors'][operation] = summary
        self.state['last_diagnostic_error'] = dict(at=time.time(), operation=operation, summary=summary)

    def emit(self, data):
        try:
            prepare_directory(self.directory)
            self.log.write(data)
            self.state['diagnostic_errors'].pop('log', None)
        except OSError as error:
            # 診断の失敗で pipe の読み取りや次サイクルの更新を止めない。
            self.diagnostic_error('log', error)

    def save(self):
        self.state['heartbeat_at'] = time.time()
        name = None
        try:
            prepare_directory(self.directory)
            fd, name = tempfile.mkstemp(prefix='state-', dir=self.directory)
            self.state['diagnostic_errors'].pop('state', None)
            with os.fdopen(fd, 'w') as stream:
                json.dump(self.state, stream, ensure_ascii=False)
                stream.write('\n')
            os.replace(name, self.directory / 'state.json')
        except OSError as error:
            self.diagnostic_error('state', error)
        finally:
            if name is not None:
                try:
                    Path(name).unlink(missing_ok=True)
                except OSError as error:
                    self.diagnostic_error('state', error)

    def run_cycle(self):
        self.state.update(phase='running', last_attempt_at=time.time())
        self.save()
        stamp = datetime.fromtimestamp(self.state['last_attempt_at'], timezone.utc).isoformat()
        self.emit(f"--- attempt {stamp} ---\n".encode())
        tail = b''
        try:
            proc = subprocess.Popen(self.command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        except OSError as error:
            rc = 127
            tail = str(error).encode()[-4096:]
            self.emit(tail + b'\n')
        else:
            with proc:
                with selectors.DefaultSelector() as selector:
                    selector.register(proc.stdout, selectors.EVENT_READ)
                    next_heartbeat = time.monotonic() + self.heartbeat_interval
                    while selector.get_map() or proc.poll() is None:
                        delay = max(0, next_heartbeat - time.monotonic())
                        for key, _ in selector.select(delay):
                            data = os.read(key.fd, 4096)
                            if data:
                                self.emit(data)
                                tail = (tail + data)[-4096:]
                            else:
                                selector.unregister(key.fileobj)
                        if time.monotonic() >= next_heartbeat:
                            self.save()
                            next_heartbeat = time.monotonic() + self.heartbeat_interval
                    rc = proc.wait()
        result = 'success' if rc == 0 else 'partial' if rc == 75 else 'failure'
        completed = time.time()
        self.state.update(phase='waiting', result=result, last_completed_at=completed)
        if rc == 0:
            self.state['last_success_at'] = completed
            self.state['consecutive_failures'] = 0
        else:
            self.state['consecutive_failures'] += 1
            self.state['last_failure'] = dict(at=completed, result=result, exit_code=rc,
                                             summary=tail.decode(errors='replace')[-1024:].strip())
        self.emit(f'--- result {result} rc={rc} ---\n'.encode())
        self.save()


def read_status(directory, now=None):
    state = json.loads((directory / 'state.json').read_text())
    now = time.time() if now is None else now
    age = now - state['heartbeat_at']
    state.update(heartbeat_age_seconds=round(age, 1), stale=age > STALE_SECONDS or age < 0,
                 running_for_seconds=round(now - state['last_attempt_at'], 1)
                 if state['phase'] == 'running' else None)
    for name in ('started_at', 'heartbeat_at', 'last_attempt_at', 'last_completed_at', 'last_success_at'):
        if state[name] is not None:
            state[name] = datetime.fromtimestamp(state[name], timezone.utc).isoformat(timespec='seconds')
    for name in ('last_failure', 'last_diagnostic_error'):
        if state[name]:
            state[name]['at'] = datetime.fromtimestamp(state[name]['at'], timezone.utc).isoformat(timespec='seconds')
    return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--status', action='store_true', help='状態を JSON で表示する（更新処理は実行しない）')
    parser.add_argument('--ipv6', action='store_true')
    args = parser.parse_args()
    try:
        if args.status:
            print(json.dumps(read_status(DIRECTORY), ensure_ascii=False, indent=2))
        else:
            command = ['sudo', '-n', '/usr/local/bin/init-firewall.sh', '--refresh-domains']
            if args.ipv6:
                command.append('--ipv6')
            with writer_lock(DIRECTORY):
                monitor = Monitor(DIRECTORY, command)
                while True:
                    pause(15)
                    monitor.run_cycle()
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f'ERROR: 更新診断を利用できません: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
