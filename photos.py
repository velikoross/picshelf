"""Photo discovery, duplicate detection and collision-safe Linux moves."""
import ctypes
import errno
import hashlib
import os
import shutil
import stat
import tempfile
from collections import defaultdict
from pathlib import Path

EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp", ".gif"}


def scan(root, on_error):
    photos = []
    for directory, _, names in os.walk(root, onerror=on_error):
        for name in names:
            path = Path(directory, name)
            if path.suffix.lower() not in EXTENSIONS:
                continue
            try:
                info = path.lstat()
                if stat.S_ISREG(info.st_mode):
                    photos.append((path, info.st_size))
            except OSError as exc:
                on_error(exc)
    return sorted(photos)


def duplicates(photos, on_error):
    sizes = defaultdict(list)
    for path, size in photos:
        sizes[size].append(path)
    groups = defaultdict(list)
    for paths in sizes.values():
        if len(paths) < 2:
            continue
        for path in paths:
            try:
                digest = hashlib.sha256()
                with path.open("rb") as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(chunk)
                groups[digest.digest()].append(path)
            except OSError as exc:
                on_error(exc)
    return [paths for paths in groups.values() if len(paths) > 1]


def publish(source, directory, name):
    # Linux renameat2(RENAME_NOREPLACE) atomically reserves the final name.
    rename = ctypes.CDLL(None, use_errno=True).renameat2
    counter = 0
    while True:
        filename = name if not counter else f"{name.stem} ({counter}){name.suffix}"
        target = directory / filename
        if rename(-100, os.fsencode(source), -100, os.fsencode(target), 1) == 0:
            return target
        error = ctypes.get_errno()
        if error != errno.EEXIST:
            raise OSError(error, os.strerror(error), str(target))
        counter += 1


def move_photo(source, directory):
    info = source.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise OSError(f"Файл заменён или недоступен: {source}")
    if source.parent.samefile(directory):
        return None
    try:
        return publish(source, directory, Path(source.name))
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
    with tempfile.NamedTemporaryFile(dir=directory, prefix=".picshelf-", delete=False) as tmp:
        staging = Path(tmp.name)
    try:
        shutil.copy2(source, staging)
        current = source.lstat()
        if (current.st_dev, current.st_ino, current.st_ctime_ns) != (
            info.st_dev, info.st_ino, info.st_ctime_ns
        ):
            raise OSError(f"Файл изменился во время копирования: {source}")
        target = publish(staging, directory, Path(source.name))
        try:
            source.unlink()
        except OSError as exc:
            raise OSError(f"Копия сохранена в {target}, исходник остался: {exc}") from exc
        return target
    finally:
        staging.unlink(missing_ok=True)
