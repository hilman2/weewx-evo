# Captured payloads

Real uploads, one per file, with the `PASSKEY` replaced. They are the input to the
parser tests, so a change that would have dropped a field shows up as a failing test
rather than as a gap in somebody's database a month later.

| File | Hardware | Notable |
|---|---|---|
| `hp2561ae_pro.txt` | HP2561AE Pro console, firmware V2.1.4 | WH57 lightning, two WN34 soil probes, WH52 soil EC, `vpd` |

To add one: set `log_raw = True` on the listener, take the line out of the log, replace
the `PASSKEY`, and write a test that says what should come out of it.
