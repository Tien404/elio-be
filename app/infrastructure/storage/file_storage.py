from collections.abc import Iterator
from typing import BinaryIO

from app.core.errors import FeatureNotImplemented


class FileStorage:
    def store(self, stream: BinaryIO) -> str:
        raise FeatureNotImplemented("FileStorage.store")

    def read(self, key: str) -> Iterator[bytes]:
        raise FeatureNotImplemented("FileStorage.read")

    def save(self, **kwargs: object):
        raise FeatureNotImplemented("FileStorage.save")

    # Implement durable local bytes + DB file_assets together in the files story.
