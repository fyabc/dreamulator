"""Bounded paths, immutable inputs and atomic registry/checkpoint metadata."""
import contextlib
import hashlib
import json
import os
import re
import sys
from pathlib import Path


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def read(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def atomic(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    temporary.replace(path)


def valid_name(name: str):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', name):
        raise ValueError('实验名须为1–64个英文字母、数字、下划线或短横线。')
    if name.upper().split('.')[0] in {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}:
        raise ValueError('实验名不能是Windows保留设备名。')
    return name


def within(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError('配置路径超出工作目录。')
    return path


def registry(root: Path):
    data = read(root / 'experiments.json')
    if data.get('schema_version') != 1:
        raise ValueError('Unsupported experiments registry version.')
    names = [valid_name(c['name']) for c in data['cases']]
    if len(names) != len(set(names)):
        raise ValueError('Duplicate experiment names.')
    return data


@contextlib.contextmanager
def locked(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    with (root / '.manager.lock').open('a+b') as stream:
        if sys.platform.startswith('linux'):
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        elif sys.platform == 'win32':
            import msvcrt
            stream.seek(0)
            if stream.read(1) == b'':
                stream.write(b'0'); stream.flush()
            stream.seek(0); msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        try:
            yield
        finally:
            if sys.platform == 'win32':
                stream.seek(0); msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def init(root: Path, max_active: int):
    if max_active < 1:
        raise ValueError('并发容量必须为正整数。')
    if root.exists():
        raise ValueError('请选择尚不存在的工作目录，避免覆盖旧实验。')
    root.mkdir(parents=True)
    atomic(root / 'experiments.json', {'schema_version': 1, 'max_active': max_active, 'cases': []})
