# Result: M4 port to Odoo 18.0

Date: 2026-11-24. Branch `claude/b2-port-18.0`, cut from `origin/18.0` at `6b7fe9e` ("merge: 0.10.2 security hotfix
(18.0)"). Staged only: nothing committed, nothing pushed, version not bumped (stays `18.0.0.10.2`; the 0.11.0
release step bumps it). Part of the single 0.11.0 release.

**What is ported:** everything on `claude/b2-s4-fixes-17`: the outbound channel (M1 core, M2 executor, M3
pairing), the RPC lockdown and allowlist work (M-R2 to M-R5), HR over the channel (M-R6), the Discuss assistant
(M-D, `docs/DISCUSS_CONTRACT.md`), and the S4 fixes (token bucket 40/s burst 60 as system parameters, channel
settings read fresh at each leader tick). See `RESULT_S4_FIXES_17.md` and `RESULT_HR_DISCUSS_17.md` on the 17
branches for the behaviour; this file is about the port.

## How it was ported

1. **17 with the hotfix** (scratch only, no commit): `claude/b2-s4-fixes-17` merged with `origin/17.0` (the 0.10.2
   hotfix) over their common base `01bc040`. Where both did the same lockdown (the `_` renames of the service and
   ORM entry points, the admin check on the setup wizard), the channel side was kept: it already has the
   hotfix's renames and checks, plus `/users/search` moved into the service. Where they differ, **both guards
   hold**:
   - `res.config.settings.get_values` / `set_values`: Odoo's access check (channel) **and** the hotfix's
     `_styd_bridge_check_admin()`; `set_values` still checks the CA bundle.
   - `tests/test_rpc_access.py`: the hotfix's version-aware file (internal **and** portal users, each version's
     RPC path, onchange refused, the 19+ status page) plus the channel's models (pairing wizard and its 6 buttons,
     pairings, seen ids) and the Discuss models (`styd.discuss.question`, `inbox`, `welcome`, the
     `discuss.channel` extension), which define no public method and whose tables are closed.
   That tree passes on Odoo 17: 179 / 179 with and without the apps.
2. **Onto 18**: 3-way merge, base `origin/17.0`, ours `origin/18.0`, theirs the tree above. No textual conflict
   (17 and 18 differ only in version strings, `<list>` views and the access log view).
3. The Odoo 18 changes below.

## What differed on 18

| Topic | 17 | 18 (this branch) |
|---|---|---|
| `ir.cron` | `numbercall` | field removed in 18: dropped from both crons (channel keeper, Discuss job) |
| Access checks | `check_access_rights` | deprecated in 18 (gone in 20). New helpers `model_has_access` / `model_check_access` in `bridge_orm.py` (`has_access` / `check_access` when present, else the old call), used by the ORM, the settings, the capability snapshot (as 19 and 20 already do) and the HR test |
| `_()` in a module-level function | silent | 18 logs "no translation language detected": `check_owner` and `hub_from_settings` translate with `env._` when present |
| Bus notifications in tests | none pending | adding a user to a group queues bus notifications in the test cursor's pre-commit hooks; in test mode the read-only channel cursor wraps that connection, so the test helper `sync()` now also runs them (`cr.flush()`). Test-mode only |
| `test_channel_core.test_10` | `"17.0"` hard-coded | the running series |
| `test_channel_executor.test_12` | patches `check_access_rights` | patches `has_access` and `check_access` |
| `discuss.channel`, `_read_group`, `groups_id`, HR models, settings view | same as 17 | no change needed |

## Tests (own Docker lab, never the STYD QA labs)

Own containers: `s4pt-pg` (`postgres:16-alpine`) and one throwaway `odoo:18.0-20261015` per run, in the Postgres
container's network namespace; the module copied to the session scratchpad. All removed after the work.

| Run | Apps installed | Result |
|---|---|---|
| Before: `origin/18.0` unchanged | styd_odoo_bridge, project, account, hr_holidays, hr_attendance, hr_timesheet | 48 / 48 |
| Before: `origin/18.0` unchanged | styd_odoo_bridge only | 48 / 48 |
| First port run (before the 18 fixes) | both | 176 / 179: the hard-coded series, and the read-only cursor tests hit by the pending bus notifications |
| **After** | styd_odoo_bridge, project, account, hr_holidays, hr_attendance, hr_timesheet | **179 / 179**, 1 skip (the 19+ status page) |
| **After** | styd_odoo_bridge only | **179 / 179**; the HR and timesheet-pay tests skip cleanly (no HR, no account) |

No deprecation or translation warning from the module in either log. The version pin
(`test_21_manifest_version_bumped`, `18.0.0.10.2`) passes: the hotfix had already aligned it.

## Consistency pass (after 16, 19, 20 and 15)

The later ports found more version differences. Their fixes are written to work on every version, so they are on
this branch too, and the five port branches share one code for the channel, Discuss and the tests (only data files,
the Discuss model name, `_sql_constraints` vs `models.Constraint` and each release's own code differ). What that
adds here: `user_groups()` (groups with implied ones), `icp_get` / `icp_set`, `open_chat()` / `channel_record()`,
`members_field()` / `member_partners()`, the Discuss hook accepting both signatures, the bot kept in 19+ mention
filtering (unused before 19), `_auto_commit` also checking `current_test`, the analytic line's journal item by
version (`_orm_journal_item_field`), and in the tests: the test-mode and test-lock switches of 19 and 20, `GROUPS`,
`Params`, `flush_env`, pairing ids read before threads start, the record-rule test switching off Odoo's other
partner group rules, the unique-constraint check and the lots check (new tests), `ir.access` on 20, the version's
time off type.

| Final run | Apps installed | Result |
|---|---|---|
| **This branch, final** | styd_odoo_bridge, project, account, hr_holidays, hr_attendance, hr_timesheet | **181 / 181**, 1 skip (19+ status page) |
| **This branch, final** | styd_odoo_bridge only | **181 / 181** |

(181 = the 179 above plus the two new checks: the unique constraints exist in PostgreSQL, the lots model of the
version is allowed.)

## Files

New: `data/ir_cron_channel.xml`, `data/discuss_data.xml`, `models/bridge_channel*.py` (5),
`models/bridge_discuss.py`, `models/bridge_discuss_text.py`, `security/styd_bridge_channel_security.xml`,
`views/bridge_channel_views.xml`, `tests/channel_common.py`, `tests/fake_hub.py`, `tests/data/b2_protocol_vectors.json`,
9 test files, `docs/DISCUSS_CONTRACT.md`. Changed: manifest (`depends: base, mail`; data files), controller, ORM,
service, setup wizard, settings (model and view), access log, ACL, tests `__init__`, `test_orm_bridge`,
`test_rpc_access`.
