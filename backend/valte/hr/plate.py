"""HappyRobot node configs are Plate rich text. A reference to another
node's output is a `variable` element whose group_id is the source node's
persistent id (or a built-in group such as "current")."""

from typing import Any


class Var:
    def __init__(self, group_id: str, variable_id: str) -> None:
        self.group_id, self.variable_id = group_id, variable_id

    def node(self) -> dict[str, Any]:
        return {"type": "variable", "children": [{"text": ""}], "group_id": self.group_id,
                "variable_id": self.variable_id}


def p(*parts: "str | Var") -> dict[str, Any]:
    """One paragraph mixing text and variables."""
    children: list[dict[str, Any]] = []
    for part in parts:
        if isinstance(part, Var):
            if not children or "text" not in children[-1]:
                children.append({"text": ""})
            children.append(part.node())
            children.append({"text": ""})
        else:
            children.append({"text": str(part)})
    return {"type": "paragraph", "children": children or [{"text": ""}]}


def doc(*paragraphs: "dict[str, Any] | str") -> list[dict[str, Any]]:
    return [x if isinstance(x, dict) else p(x) for x in paragraphs]


def text(s: str) -> list[dict[str, Any]]:
    """Plain multi-line text, one paragraph per line."""
    return [p(line) for line in s.strip("\n").split("\n")]


def static(id: str, name: str) -> dict[str, Any]:
    return {"type": "static", "static": {"id": id, "name": name}}
