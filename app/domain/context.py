from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Actor:
    user_id: int
    role: Literal["STUDENT", "INSTRUCTOR", "ADMIN"]
    restricted: bool = False
