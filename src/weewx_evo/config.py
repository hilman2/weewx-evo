"""Reading and writing the configuration file.

TOML, because it is the format Python can now read without a dependency and a
person can edit without learning anything. One file, and the admin page writes
the same file a person would.

Two things this is careful about, both learned from configuration files that
went wrong in the field:

  * **The file is rewritten, not patched.** Values come from the schema, so
    what is written is what the running system will read back. A file that
    accumulates settings nobody recognises is a file nobody dares to touch.
  * **A comment above every setting.** The file has to be editable by hand
    when the admin page cannot be reached, at three in the morning, over a
    serial console. That is the situation configuration files exist for.

Anything already in the file that the schema does not know is kept, in a
section at the end, rather than being dropped. It probably belongs to a driver
that is not installed at the moment, and deleting somebody's settings because
a package is missing is not a thing to do.
"""

from __future__ import annotations

import shutil
import tomllib
from pathlib import Path
from typing import Any

from .options import Option, Schema, format_duration


def read(path: str | Path) -> dict[str, Any]:
    """The configuration file, or an empty one if it is not there yet."""
    path = Path(path)
    if not path.exists():
        return {}
    with open(path, "rb") as fp:
        return tomllib.load(fp)


def get(config: dict, dotted: str, default: Any = None) -> Any:
    """A value by its dotted name: get(cfg, 'station.latitude')."""
    node: Any = config
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def put(config: dict, dotted: str, value: Any) -> None:
    """Set a value by its dotted name, making the sections on the way."""
    parts = dotted.split(".")
    node = config
    for part in parts[:-1]:
        nxt = node.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            node[part] = nxt
        node = nxt
    node[parts[-1]] = value


def values_for(config: dict, schema: Schema) -> dict[str, Any]:
    """What this schema's settings currently are, defaults filled in."""
    prefix = schema.groups[0].prefix if schema.groups else ""
    out = {}
    for group, option in schema:
        where = group.prefix or prefix
        dotted = f"{where}.{option.name}" if where else option.name
        value = get(config, dotted)
        out[option.name] = option.default if value is None else value
    return out


def apply(config: dict, schema: Schema, values: dict[str, Any]) -> None:
    """Write a schema's settings into the configuration."""
    for group, option in schema:
        if option.name not in values:
            continue
        where = group.prefix
        dotted = f"{where}.{option.name}" if where else option.name
        put(config, dotted, values[option.name])


# -- writing -------------------------------------------------------------

def write(path: str | Path, config: dict, schemas: list[Schema],
          backup: bool = True) -> Path:
    """Write the configuration out, commented, and keep the previous one.

    Written beside and moved into place, so an interrupted write cannot leave
    a file that is half a configuration. The previous version is kept as
    `.bak`: this file decides whether a station records anything, and the
    ability to put back what worked ten seconds ago is worth one copy.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = render(config, schemas)

    partial = path.with_suffix(path.suffix + ".part")
    partial.write_text(text, encoding="utf-8")
    # Parse what was written, not what we meant to write.
    with open(partial, "rb") as fp:
        tomllib.load(fp)

    if backup and path.exists():
        shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
    partial.replace(path)
    return path


def render(config: dict, schemas: list[Schema]) -> str:
    """The configuration as a commented TOML file."""
    lines: list[str] = [
        "# weewx-evo configuration.",
        "#",
        "# Written by the admin page, and meant to be edited by hand as well.",
        "# Every setting is commented with what it does. Durations may be",
        "# written as 30s, 5m, 2h or 7d; a bare number is seconds.",
        "",
    ]
    written: set[str] = set()

    for schema in schemas:
        heading = schema.label
        lines.append("#" + "-" * 72)
        lines.append(f"# {heading}")
        if schema.help:
            lines.append(f"# {schema.help}")
        lines.append("#" + "-" * 72)
        lines.append("")

        for group in schema.groups:
            section = group.prefix
            body: list[str] = []
            for option in group.options:
                dotted = f"{section}.{option.name}" if section else option.name
                value = get(config, dotted)
                if value is None:
                    continue
                written.add(dotted)
                body.extend(_option_lines(option, dotted, value))
            if not body:
                continue
            lines.append(f"# {group.label}")
            if group.help:
                lines.append(f"#   {group.help}")
            lines.append("")
            lines.extend(body)

    leftovers = _unknown(config, written)
    if leftovers:
        lines.append("#" + "-" * 72)
        lines.append("# Settings nothing installed recognises.")
        lines.append("#")
        lines.append("# Kept because they probably belong to a driver that is not")
        lines.append("# installed right now. Remove them by hand if they are stale.")
        lines.append("#" + "-" * 72)
        lines.append("")
        for dotted, value in sorted(leftovers.items()):
            lines.append(f"{_assignment(dotted, value)}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _option_lines(option: Option, dotted: str, value: Any) -> list[str]:
    out: list[str] = []
    if option.help:
        for line in _wrap(option.help, 74):
            out.append(f"# {line}")
    notes = []
    if option.unit:
        notes.append(f"in {option.unit}")
    if option.restart:
        notes.append("needs a restart")
    if option.default is not None:
        shown = (format_duration(option.default) if option.kind == "duration"
                 else option.default)
        notes.append(f"default: {shown}")
    if notes:
        out.append(f"#   ({'; '.join(notes)})")

    # A block, written as a table. Some settings take one: a skin's `[Extras]`
    # is whatever its author invented, and the schema calls it a list because
    # that is how the form offers it -- one `name = value` per line. In the
    # file it may equally be a table, and it has to survive being read and
    # written again.
    #
    # Putting it through `Option.parse` instead turns
    # `{"base_path": "/wdc/"}` into `["{'base_path': '/wdc/'}"]`: a Python
    # dict repr, inside a string, inside a list. Unrecoverable, and nothing
    # notices.
    if isinstance(value, dict):
        for key, held in sorted(value.items()):
            out.extend(_nested_lines(f"{dotted}.{key}", held))
        out.append("")
        return out

    # Through the option first. A value read back from the file is in whatever
    # shape it was written -- a duration comes back as "5m", not 300 -- and
    # rendering has to start from the canonical form or the second write is
    # not the same as the first.
    try:
        value = option.parse(value)
    except Exception:
        # Something the schema cannot make sense of. Written back as it was
        # found: it is the operator's, and losing it would be worse than
        # leaving it for them to fix.
        return [*out, f"{dotted} = {_toml(value)}", ""]

    if option.kind == "duration":
        rendered = _toml(format_duration(int(value)))
    else:
        rendered = _toml(value)
    # Dotted keys rather than sections, so the order in the file is the order
    # written here and a reader is never sent looking for a heading further up.
    out.append(f"{dotted} = {rendered}")
    out.append("")
    return out


def _nested_lines(dotted: str, value: Any) -> list[str]:
    """A value that may itself be a table, as dotted keys all the way down."""
    if isinstance(value, dict):
        out: list[str] = []
        for key, held in sorted(value.items()):
            out.extend(_nested_lines(f"{dotted}.{key}", held))
        return out
    return [f"{dotted} = {_toml(value)}"]


def _assignment(dotted: str, value: Any) -> str:
    return f"{dotted} = {_toml(value)}"


def _toml(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (list, tuple)):
        if not value:
            return "[]"
        inner = ", ".join(_toml(v) for v in value)
        return f"[{inner}]"
    text = str(value)
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _wrap(text: str, width: int) -> list[str]:
    import textwrap

    return textwrap.wrap(text, width) or [""]


def _unknown(config: dict, written: set[str], prefix: str = "") -> dict[str, Any]:
    """Everything in the file that no schema claimed.

    A setting the schema already wrote is not descended into. Some of them
    hold a whole block -- a skin's `[Extras]` is a table of whatever its
    author invented -- and walking into one produces a second copy of every
    key underneath it. Two copies of `feeds.wdc.extras` is not merely untidy:
    it is a file `tomllib` refuses, so the admin page cannot save at all
    until somebody edits it by hand.
    """
    out: dict[str, Any] = {}
    for key, value in config.items():
        dotted = f"{prefix}.{key}" if prefix else key
        if dotted in written:
            continue
        if isinstance(value, dict):
            out.update(_unknown(value, written, dotted))
        else:
            out[dotted] = value
    return out
