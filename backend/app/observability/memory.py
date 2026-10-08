"""An in-memory tracing backend: the trace of a request kept as data in the
process, for evaluation and tests. Nothing leaves the process. It receives what
any backend receives, so only safe metadata (app.observability.tracing)."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Node:
    """One observation, as recorded."""

    id: int
    parent: int | None
    name: str
    kind: str
    model: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    level: str | None = None
    status_message: str | None = None
    usage: dict[str, int] | None = None
    ended: bool = False


class MemoryBackend:
    """Records every observation, and every value handed to it, in order."""

    def __init__(self) -> None:
        self.nodes: list[Node] = []
        self.sent: list[Any] = []

    def _add(self, parent: Node | None, name: str, kind: str, metadata: dict, model=None) -> Node:
        node = Node(len(self.nodes), parent.id if parent else None, name, kind, model, dict(metadata))
        self.nodes.append(node)
        return node

    def start_trace(self, *, name, request_id, user_id, metadata):
        self.sent.append(("start_trace", name, request_id, user_id, metadata))
        node = self._add(None, name, "trace", metadata)
        node.metadata.update(user_id=user_id)
        return node

    def start(self, parent, *, name, kind, metadata, model):
        self.sent.append(("start", name, kind, metadata, model))
        return self._add(parent, name, kind, metadata, model)

    def update(self, handle, *, metadata, level, status_message, usage):
        self.sent.append(("update", handle.name, metadata, level, status_message, usage))
        handle.metadata.update(metadata)
        handle.level = level or handle.level
        handle.status_message = status_message or handle.status_message
        handle.usage = usage or handle.usage

    def end(self, handle):
        self.sent.append(("end", handle.name))
        handle.ended = True

    def end_trace(self, handle):
        self.sent.append(("end_trace", handle.name))
        handle.ended = True

    # reading the trace

    @property
    def root(self) -> Node:
        (root,) = [node for node in self.nodes if node.parent is None]
        return root

    def children(self, node: Node) -> list[Node]:
        return [child for child in self.nodes if child.parent == node.id]

    def named(self, name: str) -> list[Node]:
        return [node for node in self.nodes if node.name == name]

    def tree(self, node: Node | None = None) -> tuple:
        """(name, (children...)) from the root, in the order they started."""
        node = node or self.root
        return (node.name, tuple(self.tree(child) for child in self.children(node)))
