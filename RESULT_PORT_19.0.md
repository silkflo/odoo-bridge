# Result: M4 port to Odoo 19.0

Date: 2026-11-24. Branch `claude/b2-port-19.0`, cut from `origin/19.0` at `be8e103` ("merge: 0.10.2 security hotfix
(19.0)"). Staged only: nothing committed, nothing pushed, version not bumped (stays `19.0.0.10.2`; the 0.11.0
release step bumps it). Part of the single 0.11.0 release.

**What is ported:** everything on `claude/b2-s4-fixes-17`: the outbound channel (M1 to M3), the RPC lockdown and
allowlist work (M-R2 to M-R5), HR over the channel (M-R6), the Discuss assistant (M-D, `docs/DISCUSS_CONTRACT.md`)
and the S4 fixes (token bucket 40/s burst 60 as system parameters; channel settings read fresh at each leader
tick). Behaviour: `RESULT_S4_FIXES_17.md` and `RESULT_HR_DISCUSS_17.md` on the 17 branches.

## How it was ported

The 17 work merged with the 0.10.2 hotfix (both guards kept where they differ, see `RESULT_PORT_18.0.md`), plus the
version-neutral fixes found on 18 and 16, applied onto `origin/19.0` by a 3-way merge over `origin/17.0`. Three
textual conflicts, all unions: the models' imports, the ORM's constants (19's `ORM_USE_PRIVATE_READ_GROUP` next
to the channel's member-rights constants), and the connector owner (the channel's per-pairing owner first, then
19's `_icp_get`). The capability snapshot keeps 19's own `_model_has_access`. 19's status page, its read-group
shape adapter and its test stay as they are.

## What differed on 19

| Topic | 17 / 18 | 19 (this branch) |
|---|---|---|
| **Unique constraints** | `_sql_constraints` | **ignored by 19** (a warning only): the pairing id, the seen request id (the replay guard's `ON CONFLICT (request_id)` needs it), the question id and the welcome per user would have had no constraint. Declared as `models.Constraint`; PostgreSQL gets the same names. New test on every version: the four constraints exist in the database |
| `res.users` groups | `groups_id` (implied included) | `group_ids` (explicit only) and `all_group_ids`: new `user_groups()` (all groups, implied included) for the member rule and the Discuss audience; tests use the version's field (`GROUPS`) |
| Test cursors | `registry.enter_test_mode` | `registry_enter_test_mode()` on the test case; the test's thread holds the test-cursor lock, so `ChannelCase` lets it go for the test (as HttpCase does around requests): the channel's threads open their cursors while the test waits for them. Test-only |
| Direct chat | `channel_get` | gone: `open_chat()` uses `_get_or_create_chat` when present |
| **Mentions of the bot** | kept | 19 drops mentioned partners who cannot read the channel (a channel restricted to a group, a chat they are not in). The bot is a partner without a user, so a mention, the way to ask in a channel, never reached the hook. `discuss.channel._get_allowed_message_partner_ids` now keeps the bot partner (only it) |
| Discuss job under tests | thread flag `testing` | not set by 19: the job also checks `odoo.modules.module.current_test` before committing |
| `hr.leave.type.requires_allocation` | selection `yes`/`no` | boolean (test data only) |
| `ir.cron` | `numbercall` | dropped (as on 18) |
| Access checks, `_()` in functions, bus pre-commit in tests | | as on 18 (helpers already in the tree) |

Unchanged on 19: `discuss.channel` and its hook, the read-only cursor, `ir.config_parameter` (plain SQL), the HR
models and every field STYD reads (all HR tests ran), the settings view (`<app>` / `<setting>` as on 17).

## Tests (own Docker lab, never the STYD QA labs)

Own containers: `s4pt-pg` (`postgres:16-alpine`) and one throwaway `odoo:19.0-20260528` per run, in the Postgres
container's network namespace; the module copied to the session scratchpad. All removed after the work.

| Run | Apps installed | Result |
|---|---|---|
| Before: `origin/19.0` unchanged | styd_odoo_bridge, project, account, hr_holidays, hr_attendance, hr_timesheet | 50 / 50 |
| Before: `origin/19.0` unchanged | styd_odoo_bridge only | 50 / 50 |
| First port run | both | 78 / 182: `Registry.in_test_mode` gone (every channel test) |
| Then | both | 143 / 182 (test-cursor lock, `channel_get`, leave type), then 165 / 182 (Discuss: commit under tests, mentions dropped) |
| **After** | styd_odoo_bridge, project, account, hr_holidays, hr_attendance, hr_timesheet | **182 / 182**, no skip |
| **After** | styd_odoo_bridge only | **182 / 182**; HR, timesheet-pay, ledger and project tests skip cleanly |

The version pin (`19.0.0.10.2`) passes. The one deprecation warning in the logs (`read_group` in `bridge_orm.py`)
is 19's existing read-group path, already in the 19.0 release (same warning in the baseline).

## Consistency pass (after 20 and 15)

The ports of 20 and 15 found more version differences. Their fixes are written to work on every version, so they
are on this branch too, and the five port branches share one code for the channel, Discuss and the tests (only data
files, the Discuss model name, `_sql_constraints` vs `models.Constraint` and each release's own code differ). What
that adds here: `icp_get` / `icp_set`, `open_chat()` checking for `pin`, `members_field()` / `member_partners()`,
the Discuss hook accepting both signatures, the analytic line's journal item by version
(`_orm_journal_item_field`), and in the tests: 20's test-mode switch, `Params`, `flush_env`, pairing ids read
before threads start, `ir.access` on 20, the version's time off type, the default user group for the plain
employee, the lots check (new test).

| Final run | Apps installed | Result |
|---|---|---|
| **This branch, final** | styd_odoo_bridge, project, account, hr_holidays, hr_attendance, hr_timesheet | **183 / 183**, no skip |
| **This branch, final** | styd_odoo_bridge only | **183 / 183** |

(183 = the 182 above plus the lots check.)
