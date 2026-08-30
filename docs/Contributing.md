# Contributing

## The one rule

> An existing WeeWX database stays readable and writable — **by WeeWX itself**.

Before changing anything in `aggregate.py`, `db/archive.py` or `db/daily.py`:

```bash
python tools/difftest.py reference/weewx.sdb
```

The test recomputes the daily summaries of a real database and compares them
with what WeeWX wrote into it. Run it before **and** after.

## Writing style in the code

**English**, as in the weewx fork. Comments say **why**, not what.

A line explaining which bug happens without it is worth more than three that
retell the code.

Good:

```python
# 429 here, not 404: this one is a real client being told to slow down
```

Not good:

```python
# increment the counter
```

What goes down well here is the **reasoning next to the decision**. Not the
sequence of steps, but why it is this sequence and not the obvious other one.

The module docstrings are the place for the longer version. They are the source
this wiki is written from.

## Where things belong

| If you want to write about… | then it belongs in… |
|---|---|
| A weather protocol | the driver, never in `listener.py` or `archiver.py` |
| A new setting | the schema (`options.py`, or `options()` on the component), nowhere else |
| How an observation aggregates | `obstypes.py` |
| A conversion | `units.py` — as a **transcription**, not recomputed |
| What gets produced | a feed under `feeds/<name>/` |
| Where it gets sent | an export under `exports/` |
| What gets drawn | `plots.toml`, never a renderer |

## The pitfalls that have already sprung

This list is not theoretical. Every item was a bug.

### argparse defaults beat the configuration file

```python
parser.add_argument("--interval", default=None)   # always None
```

argparse cannot tell "not given" from "set to the default". A default here beats
the configuration file, and then the admin page appears to do nothing, **with no
error message anywhere**. Defaults live in the schema.
→ `tools/settings_test.py`

### A partial POST resets everything else

A form sending only one group must not set the rest to the default.
`MARKER = "__present__"` is how that is recognised. In a browser it never shows
up. → `tools/adminpage.py`

### SQLite connections are thread-bound

`LiveStore.conn()` opens one per thread. Passing a connection around builds a
bug that only appears under load.

### Checking has to be free

`has_attempts_left()` asks, `failed()` pays. Mixing the two locks a console out
after five **valid** uploads. → `tools/ratelimit_test.py`

### A "cleaner" constant is a wrong constant

`units.py` is a transcription. WeeWX's table is not self-inverse, and that is
**inherited deliberately**. The test checks that our drift is their drift.
→ `tools/unitcheck.py`

### `"5m"` comes back as a string

A roundtrip through form and file has to return a `duration` as seconds, not as
the string that went in.

### WeeWX's time suffixes are not ours

There, `M` is a minute and `m` is a **month**. Reading a WeeWX file goes by
WeeWX's rules (`_weewx_span`); nothing is ever written back with an ambiguous
suffix.

### pyephem computes refraction itself

`horizon = -0.833` counts it twice. Correct is `pressure = 0`,
`horizon = "-0:34"`, upper limb. → [Sun](Sun)

## Adding a setting

Into the schema, nowhere else:

```python
Option("infer_unknown", "Fields the catalog does not know",
       kind="choice", default="series",
       choices=(("off", "Drop them"), ("series", "…"), ("all", "…")),
       help="A reading put in the wrong column cannot be separated out afterwards.")
```

Out of it come, on their own: the form field, the validation, the comment in the
written file, the line in `--explain` and the entry in `schema.json`.

A new `kind` means: **teaching it to parse, to check and to render** — all
three, in one place each.

→ [Configuration](Configuration)

## Adding a driver

A directory under `ingest/plugins/<name>/` with a `load(registry)`. Nothing is
listed by hand.

If it is not a driver we maintain: `weewx-evo driver install`, and leave it
outside the package.

→ [Drivers](Drivers)

## Adding a feed

A directory under `feeds/<name>/` with a `produce(archive, into)` and an
`options()`. Assets — templates, stylesheets, a JS bundle — sit **next to it**,
not in a shared heap.

→ [Feeds](Feeds)

## What a test is worth here

The tests that found something all check the same pattern: **an assumption that
never shows up in a browser.**

Anyone adding one should look for that sort of case — not the one that would be
noticed anyway.

All tests run without a network and without state outside a temp directory.
→ [Testing](Testing)

## Dev tooling

**Always WSL Ubuntu**, never Windows Python:

```bash
wsl -d Ubuntu -- bash -lc 'source ~/venvs/weewx/bin/activate && \
  cd /mnt/d/Git/weewx-evo && python -m pytest tests/ecowitt -q'
```

The default WSL distro is `docker-desktop` and has no Python — hence always an
explicit `-d Ubuntu`. Venvs live under `~/venvs/<project>` inside WSL, not in the
repo on `/mnt/d` (NTFS long-path bug).

```bash
ruff check src tools tests    # line-length 100
```

## Maintaining this wiki

**`docs/` is the source; the wiki is the published copy.** A push to `main` that
touches `docs/` runs `.github/workflows/wiki.yml`, which copies the pages and
`docs/images/` into the wiki repository. It deletes there what is gone here, so
a page edited in the wiki's own web editor is overwritten by the next run.
Change the file in `docs/`, not the page on the web.

Every page declares at the end which files it covers:

```markdown
<!-- covers
src/weewx_evo/aggregate.py
src/weewx_evo/obstypes.py
-->
```

A user-guide page describes a job rather than a module, so it covers nothing
and would never be marked. It says what it depends on instead:

```markdown
<!-- watches
src/weewx_evo/exports/
src/weewx_evo/feeds/
-->
```

Same test, different claim. **Covering** a file means being its documentation:
one page owns it, and a file nothing covers is reported as having no page.
**Watching** one means going stale when it changes: any number of pages may
watch the same file, and a file nobody watches is nobody's problem. A directory
stands for everything under it.

From both, `tools/docsindex.py` builds the [Index](Index) and the
[API-Index](API-Index) — and marks the pages whose code has changed since the
last revision.

```bash
python tools/docsindex.py            # rewrite Index and API-Index
python tools/docsindex.py --check    # exit 1 if a page is behind
```

Anyone changing code sees with `--check` which page is due. Anyone revising a
page runs `docsindex.py` afterwards, so that the mark goes away.

**Created a new file?** `--check` reports it as uncovered. Either into the
`covers` block of an existing page, or into a new page.

## GitHub communication

For issue bodies, PR descriptions, review replies and commit messages, the
writing style from the `github-writing` skill applies: short sentences, no em
dashes, not defensive, no invented questions.

Say what is. Ask what you want to know. Stop.

<!-- covers
CLAUDE.md
.gitignore
.github/workflows/wiki.yml
-->
