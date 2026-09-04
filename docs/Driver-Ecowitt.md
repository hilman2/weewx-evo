# Push drivers

Hardware that uploads to you: an Ecowitt gateway, an Ambient console, a
Fine Offset Observer speaking Weather Underground, an AcuRite bridge, a
LaCrosse LW30x, a WeatherFlow hub.

**Each is its own add-on.** The core ships none.

```bash
weewx-evo addon install weewx-evo-ecowitt
```

| Add-on | The hardware |
|---|---|
| `weewx-evo-ecowitt` | GW1000 to GW3000, HP2551, HP2561, WS3800 and their rebadges |
| `weewx-evo-ambient` | WS-2902, WS-5000, WS-1965 and the rest of the Ambient range |
| `weewx-evo-wunderground` | Observer consoles, any Ecowitt set to Wunderground, Meteobridge |
| `weewx-evo-acurite` | smartHUB and Access bridges |
| `weewx-evo-lacrosse` | LW301 and LW302 gateways |
| `weewx-evo-weatherflow` | Tempest, and the AIR and SKY before it |

They share `weewx-evo-push-common`, which pip installs with any of them: the
`Protocol` base, the mapper, the body reading and the seam to the listener.
It registers nothing on its own.

## Protocol and dialect

Worth knowing here because the core stores both.

A **protocol** is an exchange: an endpoint, a response, a way of naming
itself. A **dialect** is a field catalogue -- the same exchange with other
field names, or the same names in other units. Fine Offset firmwares speak
Weather Underground in Fahrenheit **or** in Celsius, on the same endpoint
with the same credentials: one protocol, two dialects.

The driver stores the dialect beside the readings as an inert description
(`DialectSpec`), and the archiver reads that back without ever loading a
driver → [Drivers](Drivers), [Placements](Placements).

## Byte-identical to weewx-ultimate-push

`protocols/` and `catalogs/` are taken from
[weewx-ultimate-push](https://github.com/hilman2/weewx-ultimate-push)
unchanged. They import nothing -- not WeeWX, not weewx-evo -- so a fix to a
field placement belongs in both projects and should not have to be
translated on the way. Each add-on keeps the same ruff configuration for the
same reason: reformatting either side would mean every such fix arriving as
a diff nobody can read.

**The interface is ours.** What travels between the projects is the
*description* -- field catalogues and parsing -- never the interface.

## What a protocol does not configure

Nothing. Six protocols arrived at once and brought six settings pages with
the same three fields, and none of the three describes a protocol:

| | |
|---|---|
| `infer_unknown` | a policy of the installation. Asked once, in the core. |
| `max_behind` `max_ahead` | a property of a console: a timestamp is too old because a *clock* is wrong, and a clock is in a box. On the station. |

## The tests

Each add-on's suite lives with it. `tests/uploads/` stayed in the core --
real bodies consoles actually sent, with the PASSKEY replaced -- because a
captured upload is evidence rather than an implementation, and what it
proves here is that a record holds what arrived.

→ [Connecting a console](Connecting-a-console), [Drivers](Drivers)
