"""Store private files on local disk.

Files are stored under <private_files_dir>/files/<key[:2]>/<key> with a random key, never
the uploaded name, so a user cannot choose or guess paths. Only FileAsset rows in the
database (name, type, size, sha256, key) describe them; access checks happen in services.
"""

import hashlib
import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

CHUNK = 1024 * 1024


class FileTooLarge(Exception):
    pass


class EmptyFile(Exception):
    pass


@dataclass(frozen=True)
class StoredFile:
    key: str
    size_bytes: int
    sha256: str


class FileStorage:
    def __init__(self, private_files_dir: Path):
        self.root = Path(private_files_dir) / "files"

    def _path(self, key: str) -> Path:
        if len(key) != 32 or not all(c in "0123456789abcdef" for c in key):
            raise ValueError("invalid storage key")
        return self.root / key[:2] / key

    def save(self, stream: BinaryIO, *, max_bytes: int) -> StoredFile:
        """Copy the upload to disk, hashing as it goes; nothing is kept if it fails."""
        key = secrets.token_hex(16)
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".part")
        digest, size = hashlib.sha256(), 0
        try:
            with open(temp, "wb") as out:
                while chunk := stream.read(CHUNK):
                    size += len(chunk)
                    if size > max_bytes:
                        raise FileTooLarge()
                    digest.update(chunk)
                    out.write(chunk)
                out.flush()
                os.fsync(out.fileno())
            if size == 0:
                raise EmptyFile()
            os.replace(temp, path)
        except BaseException:
            temp.unlink(missing_ok=True)
            raise
        return StoredFile(key=key, size_bytes=size, sha256=digest.hexdigest())

    def path_for(self, key: str) -> Path:
        """Location of stored bytes, for streaming a download."""
        return self._path(key)

    def read(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)
