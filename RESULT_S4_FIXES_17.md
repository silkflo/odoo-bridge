# Result: S4 open points 6 and 8, Odoo 17.0

Date: 2026-11-24. Branch `claude/b2-s4-fixes-17`, cut from `claude/b2-hr-discuss-17` at `8f7661e`. Staged only:
nothing committed, nothing pushed, version not bumped (the 0.11.0 release step does it). Part of the single
0.11.0 release. Source of the open points: STYD repo, `docs/internal/bridge/S4_TESTS_RESULT.md` on
`claude/bridge-b2-s4-tests` (points 6 and 8).

## Tests (Odoo 17, own Docker lab, never the STYD QA labs)

Own containers: `s4pt-pg` (`postgres:16-alpine`) and one throwaway `odoo:17.0-20260908` per run, sharing the
Postgres container's network namespace; the module copied to the session scratchpad. Removed after the work.

| Run | Apps | Result |
|---|---|---|
| Baseline, `8f7661e` unchanged | styd_odoo_bridge, project, account, hr_holidays, hr_attendance, hr_timesheet | 166 / 167 |
| Baseline, `8f7661e` unchanged | styd_odoo_bridge only | 166 / 167 |
| This branch | the apps above | **177 / 178** (run twice) |
| This branch | styd_odoo_bridge only | **177 / 178** |
| This branch with both fixes reverted (check that the tests catch it) | styd_odoo_bridge only | 167 / 178: 10 of the new tests fail, plus `test_32` |

The one failure everywhere is the known `test_21_manifest_version_bumped` (pins `17.0.0.10.0`, the manifest says
`17.0.0.10.1`), fixed at the 0.11.0 release step.

## Open point 8: the channel's token bucket

`models/bridge_channel_executor.py`

- The bucket is now **40 reads/s, burst 60** by default, as two system parameters:
  `styd_odoo_bridge.channel_rate_per_s` (default 40) and `styd_odoo_bridge.channel_burst` (default 60).
  A value that is not a number, or is below 1, falls back to the default; above 1000 is capped at 1000.
- The leader reads both at every tick (fresh, see point 6) and resizes the running bucket in place: the tokens
  left stay, capped at the new burst; no free refill.
- **4 workers and the queue of 16 are unchanged**, on this measurement (Odoo 17, real cursors, `odoo shell` on
  a throwaway database, the module's fake hub delivering each question as **one** batch, 5 runs each; the real
  hub sends up to 32 per poll and allows 32 in flight):

| Setting | Busy reads, cold question of 22 / 25 / 32 reads | Cold ms (median) |
|---|---|---|
| Before: 10/s, burst 20, queue 16 | 1 / 4 / 10 | 164 / 178 / 219 |
| 40/s, burst 60, queue 16 (this branch) | **0 / 0 / 0** | 168 / 199 / 264 |
| 40/s, burst 60, queue 28 | 0 / 0 / 0 | 158 / 193 / 296 |

  The 4 workers drain while the batch is dispatched, so even 32 reads at once never reach the 20-slot bound; a
  larger queue changes nothing. Back to back (a new 25-read question every ~0.2 s, about 125 reads/s, far above
  a real chat), the first two questions are answered with no `busy` and the next ones are rate limited, as the
  bucket intends. Before, every read of the second question was `busy`.

## Open point 6: settings reach the running leader within its tick

`models/bridge_channel.py`

- `PairingStore.load` (the leader's tick, every 10 s) now reads the channel parameters straight from
  `ir_config_parameter` (`read_params_fresh`, one `SELECT`): `styd_odoo_bridge.enabled`,
  `channel_hub_url`, `channel_ca_bundle`, and the two bucket parameters. `get_param` is cached per process and
  the leader's process clears that cache only when it runs a cron job, which is why S4 measured 36 to 72 s.
- `read_settings(env)` keeps the cached read for the other callers (Show code, the Discuss job): they run in a
  request or a cron job, where Odoo has already cleared the cache.
- A changed hub URL or CA bundle restarts the streams on the new client at that tick (the existing `hub_key`
  logic); switched off, the leader stops; a CA bundle that cannot be read stops the leader with "bad channel
  settings", as before.

## New tests (`tests/test_channel_settings.py`, 11; `test_channel_executor.test_32` updated to 40 / 60)

- defaults 40/s burst 60, workers 4, queue 16; `parse_limit` (empty, text, 0, negative, NaN, decimal, cap);
- the bucket resized in place (tokens kept, no free refill, smaller burst caps);
- four 25-read questions 0.5 s apart: 0 refused with the new bucket, over 40 with the old one;
- a tick applies the bucket parameters, and falls back to the defaults on a bad or missing value;
- end to end: one hub batch of 25 reads through a stream, no `busy`;
- `PairingStore.load` reads the table while this process's `get_param` cache is stale (hub URL, CA bundle,
  URL removed: the default hub);
- switched off in the table only: the leader stops at its next tick; an unreadable CA bundle: stops with
  "bad channel settings";
- **the running runner thread** moves to a second hub within its tick (hello there, a request answered there)
  after the URL is changed in the table only, while this process's cache still has the old URL;
- the running runner thread picks up new bucket limits within its tick.

In test mode every channel cursor wraps the test's one connection: the tick tests start streams without threads,
and the runner-thread tests touch the database only before the thread starts or through the locked test cursor.

## Next

M4: the port of this branch to 18.0, 16.0, 19.0, 20.0 and 15.0 (`RESULT_PORT_<version>.md` on each
`claude/b2-port-<version>` branch).
