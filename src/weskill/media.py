"""Stage local media for the native client's existing send_message adapter."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat
import tempfile
import time
from urllib.parse import quote
import uuid


def _digest_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open('rb') as source:
        if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
            raise ValueError('Media source must be a local regular file')
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def file_identity(file_path: str | Path) -> dict:
    """Hash the current local bytes so a later copy can detect source changes."""
    path = Path(file_path).expanduser().resolve(strict=True)
    digest, size = _digest_file(path)
    return {'path': str(path), 'sha256': digest, 'size': size, 'name': path.name}


def _cache_root(pid: int, proc_root: Path = Path('/proc')) -> Path:
    """Discover only account roots whose databases the selected process has open."""
    accounts: set[Path] = set()
    try:
        descriptors = list((proc_root / str(pid) / 'fd').iterdir())
    except OSError as exc:
        raise RuntimeError('Cannot inspect the selected WeChat process file descriptors') from exc
    for descriptor in descriptors:
        try:
            target = Path(os.readlink(descriptor))
        except OSError:
            continue
        if not target.is_absolute() or 'db_storage' not in target.parts:
            continue
        index = target.parts.index('db_storage')
        account = Path(*target.parts[:index])
        if index > 1 and (account / 'db_storage').is_dir():
            accounts.add(account.resolve())
    if not accounts:
        raise RuntimeError('No active WeChat account database directory was found')
    if len(accounts) != 1:
        raise RuntimeError('Multiple active WeChat account database directories were found')
    account = accounts.pop()
    if account.stat().st_uid != os.getuid():
        raise RuntimeError('The active WeChat account directory belongs to another user')
    return account / 'cache'


def _month() -> str:
    # Native helpers use local time for cache layout; chat display timezone is unrelated.
    return time.strftime('%Y-%m', time.localtime())


def _private_directory(directory: Path) -> None:
    if directory.is_dir():
        if directory.stat().st_uid != os.getuid():
            raise RuntimeError('Media cache directory belongs to another user')
        return
    _private_directory(directory.parent)
    try:
        directory.mkdir(mode=0o700)
    except FileExistsError:
        if not directory.is_dir():
            raise RuntimeError('Media cache path is not a directory') from None
    if directory.stat().st_uid != os.getuid():
        raise RuntimeError('Media cache directory belongs to another user')


def _readable_name(name: str) -> str:
    # This client's XML extractor does not decode XML entities. Rename instead.
    safe = ''.join('_' if c in '<>&\"\'' or ord(c) < 32 else c for c in name)
    return safe if safe not in ('', '.', '..') else 'file'


def _collision_name(name: str, token: str, digest: str) -> str:
    original = Path(name)
    marker = hashlib.sha256(token.encode('utf-8')).hexdigest()[:12]
    return f'{original.stem}--weskill-{marker}-{digest[:12]}{original.suffix}'


def _stage(source: Path, destination: Path, expected: str | None, token: str,
           rename_on_collision: bool) -> Path:
    """Copy and hash before publishing; link atomically without overwriting files."""
    _private_directory(destination.parent)
    fd, temporary = tempfile.mkstemp(prefix='.weskill-', dir=destination.parent)
    temporary_path = Path(temporary)
    try:
        digest = hashlib.sha256()
        with os.fdopen(fd, 'wb') as output, source.open('rb') as original:
            if not stat.S_ISREG(os.fstat(original.fileno()).st_mode):
                raise ValueError('Media source must be a local regular file')
            while chunk := original.read(1024 * 1024):
                digest.update(chunk)
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        copied_digest = digest.hexdigest()
        if expected is not None and copied_digest != expected:
            raise ValueError('Media source changed after its identity was recorded')
        candidate = destination
        while True:
            try:
                os.link(temporary_path, candidate)
                return candidate
            except FileExistsError:
                if candidate.is_file() and not candidate.is_symlink():
                    existing_digest, _ = _digest_file(candidate)
                    if existing_digest == copied_digest:
                        return candidate
                if not rename_on_collision:
                    raise ValueError('Image cache key already refers to different bytes') from None
                if candidate == destination:
                    candidate = destination.with_name(
                        _collision_name(destination.name, token, copied_digest))
                else:
                    candidate = destination.with_name(
                        _collision_name(destination.name, uuid.uuid4().hex, copied_digest))
    finally:
        temporary_path.unlink(missing_ok=True)


def prepare_media(pid: int, kind: str, recipient: str, file_path: str | Path,
                  token: str, expected_sha256: str | None = None) -> dict:
    """Stage bytes and return arguments for the native generic JSON adapter."""
    if kind not in ('image', 'file'):
        raise ValueError('Media kind must be image or file')
    if not isinstance(token, str) or not token:
        raise ValueError('A media cache token is required')
    source = Path(file_path).expanduser().resolve(strict=True)
    root = _cache_root(pid) / _month()
    if kind == 'image':
        url = f'https://weskill.invalid/local/{quote(token, safe="")}.png'
        key = hashlib.md5(url.encode('utf-8')).hexdigest()
        cached = _stage(source, root / 'HttpResource' / key,
                        expected_sha256, token, False)
        parameters = {'chat_id': recipient, 'message_type': 3, 'content_xml': url}
        name = source.name
    else:
        name = _readable_name(source.name)
        cached = _stage(source, root / 'chatbot' / 'file' / name,
                        expected_sha256, token, True)
        name = cached.name
        content = ('<msg><appmsg><title>' + name + '</title><type>6</type>'
                   '<appattach><cdnattachurl>weskill-local-cache</cdnattachurl>'
                   '<aeskey>weskill-local-cache</aeskey></appattach></appmsg></msg>')
        parameters = {'chat_id': recipient, 'message_type': 49, 'content_xml': content}
    return {'parameters': parameters, 'cache_path': str(cached), 'file_name': name}
