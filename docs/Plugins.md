# Plugins

What lives outside the core, and how it gets in anyway.

Two forms, and which applies depends on what the plugin is.

## An entry point — exports, uploads, feeds, forecast sources

A pip-installable package with one line in its `pyproject.toml`:

```toml
[project.entry-points."weewx_evo.exports"]
sftp = "weewx_evo_sftp:SftpExport"
```

That is all it is. `pip install weewx-evo-sftp`, and afterwards `sftp` appears
in `weewx-evo export list`, in the choices on the settings page and as
`kind = "sftp"` in the configuration — without one line of change to weewx-evo.

The four groups:

| Group | What for | Interface |
|---|---|---|
| `weewx_evo.exports` | a directory somewhere else | `send(source, files)` |
| `weewx_evo.uploads` | the readings to a service | `post(records)` |
| `weewx_evo.feeds` | producing something | `produce(into)` |
| `weewx_evo.forecast` | what is coming | `fetch(place)` |

Every registry reads its group on first use (`load()`). **A plugin that will
not import is reported and skipped** — the same rule as with the drivers: one
that is broken must not cost the others.

A plugin that has `options()` gets its form on the settings page for free. It
has to do nothing for it, and the admin page has to know nothing about it.

## A directory — drivers

Drivers live **next to the data** rather than in the package, so that an upgrade
does not touch them:

```bash
weewx-evo driver install https://github.com/someone/weewx-evo-acurite
```

→ [Drivers](Drivers#2-installed--data-directorydrivers)

## Why the two forms differ

Not on principle, but from a practical difference: a driver has to survive an
upgrade of the package, and in a container the image being rebuilt. So it lives
in the data volume.

An entry-point plugin lives in `site-packages` and is gone after a
`docker compose build`. That is no problem for an installation on a Pi without
a container, and is one for an installation in a container — see below.

## What a plugin may do that the core may not

**Take a dependency.** The core runs on the standard library, and that is not a
slogan: it is what makes `pip install weewx-evo` work on a Raspberry Pi with no
compiler. A plugin has no such obligation — anyone who needs `paramiko`,
`pillow` or `numpy` takes it.

`weewx-evo-sftp` does not do so regardless, and the reason is in its README:
`cryptography` on a Pi with no matching wheel is a Rust toolchain and forty
minutes. But it would have been allowed, and that is the point.

## The catalogue

[**weewx-evo-plugins**](https://github.com/weewx-evo/weewx-evo-plugins). One
`plugins.toml`, one entry per plugin, each pointing at that plugin's own
repository.

**One repo per plugin, not one for all of them.** Each has its own issues, its
own releases and its own maintainer — and that is exactly what lets somebody who
is not us keep one alive.

The mistake this avoids is `weewx-DWD`'s: ten independent things in one package,
where a change to the radar code breaks the forecast and anyone who only wants
warnings installs the lot.

The same case already exists here: the Ecowitt driver came out of
`weewx-ecowitt`, a repo of its own for a **WeeWX** plugin. Because the two are
different programs, no fix travelled sensibly between them any more. The driver
is core now; that repo stays what it is.

## What is in it

| Plugin | Kind | `kind` | What for |
|---|---|---|---|
| [weewx-evo-sftp](https://github.com/weewx-evo/weewx-evo-sftp) | Export | `sftp` | A server with SSH but without rsync |

## Installing from the admin page?

The question comes up immediately once there is a curated catalogue, so here is
the answer rather than in an issue.

**For drivers: yes, and the mechanism is already there.** They live in the data
volume, survive an update, and `driver install` exists. A button on the settings
page would be an interface in front of something that exists.

**For entry-point plugins: not yet**, and for a concrete reason. They go into
`site-packages`, and in a container that is gone after the next
`docker compose build`. A plugin that disappears after an update is worse than
one installed by hand: it looks like a bug and nobody knows where it came from.

**What speaks against it independently of the form**, and what has to be
answered first:

- **The admin token would take on a new meaning.** Today it can change the
  configuration — at worst point the archive at a different file. With an
  install button it can run arbitrary code, as the user the service runs as.
  That is a different order of magnitude and has to be a deliberate decision,
  not a freebie.
- **"Curated" is a claim the catalogue is precisely not making.** It says that a
  plugin exists and what it claims to do. A button next to that reads as a
  recommendation. Either it really is curated — with the effort and the
  responsibility — or the button has to be labelled honestly.
- **A restart.** Entry points are read on import; a freshly installed plugin is
  only there afterwards. Doable (`needs_restart()` exists), but "one click"
  becomes "one click, and then the station is away for a minute".

**The route that resolves this** is not the button but a shared loading layer:
being able to load exports, uploads and feeds from a directory in the data
volume too, the way drivers already are. Then every plugin survives an update,
and an install button means the same thing for all of them.

With that in place, all that is left of the rest is the token question — and
that is answered with two settings: installation only from the catalogue, never
from a free-form URL, and a switch that turns it off entirely.

→ [Drivers](Drivers) · [Exports](Exports) · [Uploads](Uploads) · [Feeds](Feeds)
