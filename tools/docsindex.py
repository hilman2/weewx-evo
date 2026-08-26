"""Build the wiki index, and say which pages the code has moved out from under.

The wiki in `docs/` is written by hand. This keeps two registers up to date and
answers the one question a hand-written wiki cannot answer for itself: *which
page is now behind the code?*

    python tools/docsindex.py            # rewrite Index.md and API-Index.md
    python tools/docsindex.py --check    # exit 1 if a page is behind
    python tools/docsindex.py --accept Series.md   # "I looked; it is fine"

## How a page says what it covers

Each page ends with a block that is invisible when rendered:

    <!-- covers
    src/weewx_evo/aggregate.py
    src/weewx_evo/obstypes.py
    -->

That is the only place the mapping lives. A page that gains a subject gains a
line there, and nothing else has to be told. The alternative -- a separate
manifest -- is a second list to keep in step with the first, which is the
failure this whole arrangement exists to avoid.

## What "dirty" means here

A covered file whose modification time is newer than the page's. That is a
weaker claim than "this page is wrong", and it is meant to be: the point is to
name the pages worth *looking* at after a change, not to judge them.

Modification time rather than a content hash, for one reason: it is the thing a
person can check themselves with `ls -l`, and a register nobody can verify by
hand is a register nobody trusts. It costs a false positive when a file is
reformatted and nothing means anything different -- `--accept` is for exactly
that, and it says so in the output rather than hiding it.

There is no git here, so there is no commit date to use instead.
"""

from __future__ import annotations

import argparse
import ast
import datetime as dt
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"

#: Where source lives. Everything under these, minus SKIP, wants a page.
SOURCES = ("src", "tools", "tests", "deploy")

#: Files that are documentation of themselves, or not worth a wiki page.
SKIP = {
    "tools/docsindex.py",       # this file
    "deploy/.env",
    "deploy/.token",
    "deploy/.admin-token",
    "deploy/weewx-evo.caddy",   # holds real tokens, gitignored
}

#: Suffixes that count as something a page could be about.
INTERESTING = {".py", ".yml", ".yaml", ".toml", ".md", ".caddy", ""}

#: Pages that are generated, and pages GitHub treats as furniture.
GENERATED = {"Index.md", "API-Index.md"}
FURNITURE = {"_Sidebar.md", "_Footer.md", "_Header.md"}

COVERS = re.compile(r"<!--\s*covers\s*(.*?)-->", re.S)


def stamp(path: Path) -> float:
    return path.stat().st_mtime


def when(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


def relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def title_of(page: Path) -> str:
    """The page's first heading, or its filename."""
    for line in page.read_text(encoding="utf-8").splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return page.stem


class Page:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.name = path.stem
        text = path.read_text(encoding="utf-8")
        self.title = title_of(path)
        self.mtime = stamp(path)
        self.covers: list[Path] = []
        self.missing: list[str] = []
        for block in COVERS.findall(text):
            for line in block.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                target = ROOT / line
                if target.exists():
                    self.covers.append(target)
                else:
                    self.missing.append(line)

    @property
    def declares(self) -> bool:
        """Whether the page carries a covers block at all."""
        return bool(self.covers or self.missing)

    def stale(self) -> list[tuple[Path, float]]:
        """Covered files changed since this page was last touched, newest first."""
        out = [(f, stamp(f)) for f in self.covers if stamp(f) > self.mtime]
        return sorted(out, key=lambda pair: pair[1], reverse=True)

    def newest_covered(self) -> float:
        return max((stamp(f) for f in self.covers), default=0.0)


def pages() -> list[Page]:
    found = []
    for path in sorted(DOCS.glob("*.md")):
        if path.name in GENERATED:
            continue
        found.append(Page(path))
    return found


def sources() -> list[Path]:
    """Every file under SOURCES that a page could reasonably be about."""
    out = []
    for top in SOURCES:
        base = ROOT / top
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            if "__pycache__" in path.parts or ".pytest_cache" in path.parts:
                continue
            if path.suffix.lower() not in INTERESTING:
                continue
            if relative(path) in SKIP:
                continue
            out.append(path)
    # The files at the top that are part of the project's story.
    for name in ("README.md", "CLAUDE.md", "pyproject.toml", ".gitignore",
                 "LICENSE"):
        top = ROOT / name
        if top.exists():
            out.append(top)
    return out


# -- the file index --------------------------------------------------------

def render_index(found: list[Page]) -> str:
    covered: dict[str, list[Page]] = {}
    for page in found:
        for f in page.covers:
            covered.setdefault(relative(f), []).append(page)

    everything = sources()
    orphans = [p for p in everything if relative(p) not in covered]
    behind = [p for p in found if p.stale()]

    now = when(dt.datetime.now().timestamp())
    lines = [
        "# Datei-Index",
        "",
        "Welche Datei zu welcher Wiki-Seite gehört, und wo die Seite dem Code",
        "hinterherhinkt.",
        "",
        f"**Erzeugt:** {now} · `python tools/docsindex.py`",
        "",
        "Diese Seite wird erzeugt. Von Hand geändert wird sie beim nächsten Lauf",
        "überschrieben — die Zuordnung steht in den `covers`-Blöcken am Ende jeder",
        "Wiki-Seite.",
        "",
        "## Legende",
        "",
        "| | |",
        "|---|---|",
        "| ✅ | Die Seite ist neuer als jede Datei, die sie abdeckt |",
        "| ⚠️ | Eine abgedeckte Datei wurde **nach** der Seite geändert — ansehen |",
        "| — | Die Seite deckt keine Datei ab (Glossar, Navigation) |",
        "",
        "„⚠️\" heißt *prüfen*, nicht *falsch*. Wer nachgesehen hat und nichts ändern",
        "musste, hakt es ab:",
        "",
        "```bash",
        "python tools/docsindex.py --accept <Seite>.md",
        "```",
        "",
    ]

    # -- the summary --------------------------------------------------
    lines += [
        "## Stand",
        "",
        "| | |",
        "|---|---|",
        f"| Wiki-Seiten | {len(found)} |",
        f"| Abgedeckte Dateien | {len(covered)} von {len(everything)} |",
        f"| Seiten zu prüfen | {len(behind)} |",
        f"| Dateien ohne Seite | {len(orphans)} |",
        "",
    ]

    if behind:
        lines += ["## Zu prüfen", "",
                  "| Seite | Geändert seit der Seite | Datei zuletzt | Seite zuletzt |",
                  "|---|---|---|---|"]
        for page in sorted(behind, key=lambda p: p.newest_covered(), reverse=True):
            stale = page.stale()
            names = ", ".join(f"`{relative(f)}`" for f, _ in stale[:3])
            if len(stale) > 3:
                names += f" (+{len(stale) - 3})"
            lines.append(f"| ⚠️ [{page.title}]({page.name}) | {names} "
                         f"| {when(stale[0][1])} | {when(page.mtime)} |")
        lines.append("")
    else:
        lines += ["## Zu prüfen", "",
                  "Nichts. Jede Seite ist neuer als der Code, den sie beschreibt.",
                  ""]

    # -- page by page -------------------------------------------------
    lines += ["## Seiten", "",
              "| | Seite | Dateien | Code zuletzt | Seite zuletzt |",
              "|---|---|---|---|---|"]
    for page in sorted(found, key=lambda p: p.title.lower()):
        if not page.declares:
            mark, code = "—", "—"
        elif page.stale():
            mark, code = "⚠️", when(page.newest_covered())
        else:
            mark, code = "✅", when(page.newest_covered())
        count = len(page.covers) or "—"
        lines.append(f"| {mark} | [{page.title}]({page.name}) | {count} "
                     f"| {code} | {when(page.mtime)} |")
    lines.append("")

    # -- file by file -------------------------------------------------
    lines += ["## Dateien", "",
              "| Datei | Zeilen | Wiki-Seite | Zuletzt geändert |",
              "|---|---|---|---|"]
    for path in everything:
        rel = relative(path)
        holders = covered.get(rel, [])
        if holders:
            where = " · ".join(f"[{p.title}]({p.name})" for p in holders)
            flag = "⚠️ " if any(path in p.covers and p.stale() and
                                stamp(path) > p.mtime for p in holders) else ""
        else:
            where, flag = "**keine**", ""
        try:
            count = sum(1 for _ in path.open("r", encoding="utf-8",
                                             errors="replace"))
        except OSError:
            count = 0
        lines.append(f"| `{rel}` | {count} | {flag}{where} | {when(stamp(path))} |")
    lines.append("")

    if orphans:
        lines += ["## Ohne Seite", "",
                  "Diese Dateien nennt kein `covers`-Block. Entweder gehören sie in",
                  "eine bestehende Seite, oder es fehlt eine.", "",
                  "| Datei | Zuletzt geändert |", "|---|---|"]
        for path in orphans:
            lines.append(f"| `{relative(path)}` | {when(stamp(path))} |")
        lines.append("")

    broken = [(p, name) for p in found for name in p.missing]
    if broken:
        lines += ["## Kaputte Verweise", "",
                  "Ein `covers`-Block nennt eine Datei, die es nicht gibt.", "",
                  "| Seite | Genannt |", "|---|---|"]
        for page, name in broken:
            lines.append(f"| [{page.title}]({page.name}) | `{name}` |")
        lines.append("")

    lines += ["---", "",
              "Erzeugt von `tools/docsindex.py`. Siehe [Mitarbeiten](Contributing).",
              ""]
    return "\n".join(lines)


# -- the API index ---------------------------------------------------------

def symbols(path: Path) -> list[tuple[str, str, int]]:
    """Top-level classes, functions and methods, as (kind, name, line)."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (SyntaxError, OSError):
        return []
    out: list[tuple[str, str, int]] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.name.startswith("_"):
                out.append(("def", node.name, node.lineno))
        elif isinstance(node, ast.ClassDef):
            out.append(("class", node.name, node.lineno))
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if sub.name.startswith("_") and sub.name != "__init__":
                        continue
                    out.append(("method", f"{node.name}.{sub.name}", sub.lineno))
    return out


def summary(path: Path, name: str) -> str:
    """The first line of a symbol's docstring, if it has one."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (SyntaxError, OSError):
        return ""
    want = name.split(".")
    for node in tree.body:
        if getattr(node, "name", None) != want[0]:
            continue
        target = node
        if len(want) == 2:
            target = next((s for s in node.body
                           if getattr(s, "name", None) == want[1]), None)
            if target is None:
                return ""
        doc = ast.get_docstring(target) or ""
        return " ".join(doc.split())[:110]
    return ""


def render_api(found: list[Page]) -> str:
    owner: dict[str, Page] = {}
    for page in found:
        for f in page.covers:
            owner.setdefault(relative(f), page)

    now = when(dt.datetime.now().timestamp())
    lines = [
        "# API-Index",
        "",
        "Jede öffentliche Klasse, Funktion und Methode, ihre Datei und die",
        "Wiki-Seite, die sie beschreibt.",
        "",
        f"**Erzeugt:** {now} · `python tools/docsindex.py`",
        "",
        "Private Namen (`_foo`) fehlen, `__init__` ist dabei. Wer einen Namen",
        "sucht, benutzt die Suche des Browsers.",
        "",
    ]

    files = [p for p in sources()
             if p.suffix == ".py" and p.is_relative_to(ROOT / "src")]
    for path in files:
        found_syms = symbols(path)
        if not found_syms:
            continue
        rel = relative(path)
        page = owner.get(rel)
        where = f"[{page.title}]({page.name})" if page else "**keine Seite**"
        lines += [f"## `{rel}`", "",
                  f"{where} · zuletzt geändert {when(stamp(path))}", "",
                  "| | Name | Zeile | |", "|---|---|---|---|"]
        for kind, name, lineno in found_syms:
            mark = {"class": "**C**", "def": "f", "method": "·"}[kind]
            doc = summary(path, name) if kind != "method" else ""
            shown = f"`{name}`" if kind != "method" else f"&nbsp;&nbsp;`{name}`"
            lines.append(f"| {mark} | {shown} | {lineno} | {doc} |")
        lines.append("")

    lines += ["---", "",
              "Erzeugt von `tools/docsindex.py`. Siehe [Datei-Index](Index).",
              ""]
    return "\n".join(lines)


# -- commands --------------------------------------------------------------

def write(path: Path, text: str) -> bool:
    """Write only if it differs, so an unchanged run leaves mtimes alone."""
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    path.write_text(text, encoding="utf-8")
    return True


def check(found: list[Page]) -> int:
    behind = [p for p in found if p.stale()]
    covered = {relative(f) for p in found for f in p.covers}
    orphans = [p for p in sources() if relative(p) not in covered]
    broken = [(p, n) for p in found for n in p.missing]

    for page in behind:
        stale = page.stale()
        print(f"behind: docs/{page.path.name}  ({when(page.mtime)})")
        for f, ts in stale:
            print(f"        {relative(f)}  {when(ts)}")
    for path in orphans:
        print(f"no page: {relative(path)}")
    for page, name in broken:
        print(f"broken:  docs/{page.path.name} names {name}, which is not there")

    if not (behind or orphans or broken):
        print(f"{len(found)} pages, {len(covered)} files covered, nothing behind.")
        return 0
    return 1


def accept(names: list[str]) -> int:
    """Mark pages as looked at: set their mtime to now."""
    now = dt.datetime.now().timestamp()
    for name in names:
        path = DOCS / name if not name.endswith(".md") else DOCS / name
        if not path.exists():
            path = DOCS / f"{name}.md"
        if not path.exists():
            print(f"no such page: {name}")
            return 1
        os.utime(path, (now, now))
        print(f"accepted: docs/{path.name}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="docsindex", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true",
                        help="say what is behind and exit 1, write nothing")
    parser.add_argument("--accept", nargs="+", metavar="PAGE",
                        help="mark pages as looked at")
    args = parser.parse_args(argv)

    if not DOCS.exists():
        print(f"no docs directory at {DOCS}")
        return 1

    if args.accept:
        return accept(args.accept)

    found = pages()
    if args.check:
        return check(found)

    changed = write(DOCS / "Index.md", render_index(found))
    changed |= write(DOCS / "API-Index.md", render_api(found))
    behind = [p for p in found if p.stale()]
    covered = {relative(f) for p in found for f in p.covers}
    print(f"{len(found)} pages, {len(covered)} files covered.")
    if behind:
        print(f"{len(behind)} page(s) behind the code:")
        for page in behind:
            print(f"  docs/{page.path.name}")
    print("wrote docs/Index.md and docs/API-Index.md" if changed
          else "nothing changed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
