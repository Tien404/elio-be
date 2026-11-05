from app.core.errors import PolicyNotImplemented
from app.domain.context import Actor


class AccessControl:
    def require(self, actor: Actor, action: str, resource_id: int) -> None:
        # No development "allow all" policy.
        raise PolicyNotImplemented("AccessControl.require")
