# The settings page

`admin.py`, `adminplots.py`.

A form, built out of whatever declares settings: the core, every driver, every
feed, every export.

**Nothing here knows what an Ecowitt is or what an archive interval means.** It
renders `Option` objects and writes back what comes out. That is the whole
design: a driver that gains a setting gains a field, and this file does not
change. → [Configuration](Configuration)

## Starting it

```bash
weewx-evo config set --config evo.toml admin.token <a-different-token>
weewx-evo admin --config evo.toml
```

Then `http://<host>:8080/<admin-token>/`.

Its own port, its own token, deliberately: an upload can at worst write a wrong
reading, this page can point the archive at a different file. **The same token
for both is refused.** → [Security](Security)

Reaching it from elsewhere without opening it up:

```bash
ssh -L 8080:localhost:8080 the-station
```

## The routes

| | |
|---|---|
| `GET /<token>/` | The first page |
| `GET /<token>/<schema>` | A section: `core`, `drivers.ecowitt`, `feeds.json`, `export:<name>` |
| `GET /<token>/plot:<name>` | One plot |
| `GET /<token>/new-plot` | Create a plot |
| `GET /<token>/import-plots` | Import from a WeeWX skin |
| `GET /<token>/new-export` | Create an export |
| `GET /<token>/schema.json` | The whole declaration as JSON |
| `POST /<token>/<schema>` | Save |
| `POST /<token>/<name>/test` | Try an export destination |
| `POST /<token>/<name>/remove` | Delete |

After every successful save it **redirects**, so that a reload does not save
again.

## `Admin`

What the pages do, minus the HTTP.

```python
admin = Admin(path, schemas, token, read_only=False,
              access=PRIVATE_ONLY, limits=limits)
```

| Method | What it means |
|---|---|
| `schemas()` | Everything configurable that exists |
| `refresh()` | Rebuild the list. After anything added or removed |
| `config()`, `values(schema)` | |
| `save(schema, form)` | Check and write. Returns what was wrong |
| `add_export(name, kind)` | |
| `remove_export(name)` | Delete from the configuration. **Nothing at the far end** |
| `test_export(name)` | Try a destination and say what happened |
| `columns()` | The readings the archive has a column for |

### Everything is checked before anything is written

`save()` collects **all** the errors and only writes afterwards. A form that
applies the half it understood and reports the rest leaves behind a
configuration nobody asked for.

### `columns()` asks the database

Not a schema. A station whose driver created columns of its own should be able
to plot them, and nothing here knows anything about that.

### `MARKER = "__present__"`

A hidden field sent along so that a **partial POST** can be recognised. Without
it, a form sending only one group resets everything else to the default — in a
browser that never shows up, and `tools/adminpage.py` checks exactly that.

`MAX_FORM = 1 << 18`. `NAME` enforces small names with no surprises:
`^[a-z][a-z0-9_-]{0,31}$`.

### `_form(content_type, body)` — with a file too

Ordinary settings arrive urlencoded. The [plot importer](Plots) additionally
needs a **file**, so multipart — and `cgi.FieldStorage` was removed in Python
3.13. The email parser does the same job and has not gone away.

A file comes back as its text under its own field name. Nothing here handles
anything other than text, and a `skin.conf` is text.

**A file field left empty still posts**, with no filename and no content. It
must not beat the field somebody actually filled in.

## How a field comes about

```python
def field(option: Option, value: Any, error: str = "") -> str
def group_html(group: Group, values, errors) -> str
def page(admin, active, errors=None, message="", form=None) -> bytes
```

`kind` decides:

| `kind` | Field |
|---|---|
| `text`, `path` | `<input type="text">` |
| `secret` | `<input type="password">`, **never rendered back** |
| `int`, `float` | `<input type="number">` with `min`/`max` |
| `bool` | Checkbox |
| `choice` | `<select>`, filled from `choices` + `choices_from()` |
| `duration` | A number plus a unit (`split_duration`) |
| `list` | Comma-separated |

`suggestions` becomes a `<datalist>`: the three usual answers are one click
away, an unusual one can be typed.

`advanced` sits behind a toggle — **hidden, not left out**. A setting left out is
one you find by reading source, which is worse than a long page.

`restart` is marked, so that it is clear what saving does not take effect on
straight away.

## Creating an export

`new_export_page()` asks for **two fields**: name and kind. Everything else is
filled in on the page that appears next.

Asking for a host and a password before it is clear what is being talked about
is a form somebody fills in without knowing what they are filling in.

`export_kinds()` is **asked, not enumerated**.

## The plot pages

`adminplots.py`. The only hand-written part.

A plot does not fit the form generator: a setting is **one** named value, a plot
is a set with a list of sets inside it, and there are a hundred of them.

What these pages have to do better than a text editor, or there is no point:
seeing which readings the database actually has, without looking it up — and
bringing a set over from a WeeWX skin without typing it out.

→ [Plots](Plots#the-admin-pages)

## `schema.json`

```
GET /<token>/schema.json
```

The whole declaration as JSON. A **second interface to the same declaration** —
for an installer, a test, or an admin page somebody likes better than this one.

## `--read-only`

Shows the settings and refuses to save. For a look at an installation you do not
want to touch.

## Checking it

```bash
python tools/adminpage.py
```

Renders the page, saves through it and breaks it on purpose. What is really
being checked is the chain **declaration → form → validation → file**, for every
kind of setting there is.

Nothing outside a temp directory is touched.

The cases that found something:

- A **partial POST** resetting everything else to the default.
- A **roundtrip** in which `"5m"` comes back as a string instead of 300.

→ [Testing](Testing)

<!-- covers
src/weewx_evo/admin.py
tools/adminpage.py
-->
