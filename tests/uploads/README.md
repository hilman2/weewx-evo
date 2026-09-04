# Captured payloads

Real uploads, one per file, with the `PASSKEY` replaced. They are what the core is
measured against: `placement_test.py` runs all of them through a driver and then
through the read side, so a change that would have dropped a field shows up as a
failing test rather than as a gap in somebody's database a month later.

They stayed here when the protocols moved out to their own repositories. A body a
console actually sent is not an implementation of anything -- it is evidence, and
the question it answers is one the core asks: does a record hold what arrived?

| File | Hardware | Notable |
|---|---|---|
| `hp2561ae_pro.txt` | HP2561AE Pro console, firmware V2.1.4 | WH57 lightning, two WN34 soil probes, WH52 soil EC, `vpd` |

To add one: set `log_raw = True` on the listener, take the line out of the log, replace
the `PASSKEY`, and write a test that says what should come out of it.
