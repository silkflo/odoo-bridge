# Result: M4 port to Odoo 16.0

Date: 2026-11-24. Branch `claude/b2-port-16.0`, cut from `origin/16.0` at `8f60ca3` ("merge: 0.10.2 security hotfix
(16.0)"). Staged only: nothing committed, nothing pushed, version not bumped (stays `16.0.0.10.2`; the 0.11.0
release step bumps it). Part of the single 0.11.0 release.

**What is ported:** everything on `claude/b2-s4-fixes-17`: the outbound channel (M1 to M3), the RPC lockdown and
allowlist work (M-R2 to M-R5), HR over the channel (M-R6), the Discuss assistant (M-D, `docs/DISCUSS_CONTRACT.md`)
and the S4 fixes (token bucket 40/s burst 60 as system parameters; channel settings read fresh at each leader
tick). Behaviour: `RESULT_S4_FIXES_17.md` and `RESULT_HR_DISCUSS_17.md` on the 17 branches.

## How it was ported

Same base as 18 (`RESULT_PORT_18.0.md`): the 17 work merged with the 0.10.2 hotfix (both guards kept where they
differ), plus the version-neutral fixes found on 18 (access helpers `model_has_access` / `model_check_access`,
`env._` in module-level functions, `sync()` running pre-commit hooks, the running series in `test_10`,
`test_12` patching whichever access API the version has). That tree, applied onto `origin/16.0` by a 3-way merge
over `origin/17.0`, then the 16 changes below.

## What differed on 16

| Topic | 17 | 16 (this branch) |
|---|---|---|
| Discuss model | `discuss.channel` | **`mail.channel`** (same `channel_type` values, `channel_member_ids`, `_message_post_after_hook`); the Discuss models' many2ones, the hook's `_inherit`, the reply check and the tests. The `conversation.key` sent to STYD keeps the contract's format `discuss.channel:<id>` on every version, so the hub needs no per-version case |
| `channel_get` | returns the channel | returns the channel's info dict: new `channel_record()` browses its id (module and tests) |
| Access log | `styd.odoo.bridge.access.log` since 17.0.0.10.0 | **not on 16.0 before this port.** The channel's audit (one row per call, M2) needs it, so the model, its ACL (admin read only), list/form/search views and the *Access Logs* menu are added. On 16 it lists the channel's calls; the HTTP routes of 16 had no audit and still have none (unchanged) |
| Settings view | `<app>` / `<block>` / `<setting>`, `invisible="expr"` | `o_setting_box` layout with `attrs`: the channel settings (group restriction, CA bundle) and a *Discuss assistant* section (switch, who may ask, answer mentions in the channel, workspace, rate limits) |
| Channel pairing form | `invisible="expr"` | `attrs` |
| Manifest | `depends: base, mail` | `base, base_setup, mail` (16's settings view inherits `base_setup`) |
| Controller | had `_json_default` and the audit | 16's controller (no audit) with the shared `_json_default` from `bridge_orm`, `lang` / `company_ids` passed through, `/users/search` from the service |
| `ir.cron` | `numbercall` | kept (`-1`): the field exists until 17 |
| Record rules (`test_channel_executor.test_13`) | the test's group rule alone | Odoo 16's own group rules on partners (internal users: `type != 'private'`; more with the apps) are OR-ed with the test's rule; the test now switches off the other group rules on `res.partner` first. Odoo behaviour, not a module change: the read still runs with the member's rules, no sudo |

Unchanged on 16 (worked as is): `ir.config_parameter` (the fresh read is plain SQL), `check_access_rights` (the
helper falls back to it), the public `read_group` used by the ORM, `groups_id`, the HR models and the fields STYD
reads (all HR tests ran with the apps), `Command`, `flush_all`, `cr.flush()`.

## Tests (own Docker lab, never the STYD QA labs)

Own containers: `s4pt-pg` (`postgres:16-alpine`) and one throwaway `odoo:16.0-20250909` per run, in the Postgres
container's network namespace; the module copied to the session scratchpad. All removed after the work.

| Run | Apps installed | Result |
|---|---|---|
| Before: `origin/16.0` unchanged | styd_odoo_bridge, project, account, hr_holidays, hr_attendance, hr_timesheet | 48 / 48 |
| Before: `origin/16.0` unchanged | styd_odoo_bridge only | 48 / 48 |
| First port run | both | 156 / 179: `channel_get` returned a dict (21 Discuss tests), the record-rule test |
| Second run | apps / bare | 178 / 179 (record-rule test with the apps' partner rules) / 179 / 179 |
| **After** | styd_odoo_bridge, project, account, hr_holidays, hr_attendance, hr_timesheet | **179 / 179**, 1 skip (the 19+ status page) |
| **After** | styd_odoo_bridge only | **179 / 179**; HR, timesheet-pay, ledger and project tests skip cleanly |

The version pin (`16.0.0.10.2`) passes. No deprecation warning from the module.

## Consistency pass (after 19, 20 and 15)

The ports of 19, 20 and 15 found more version differences. Their fixes are written to work on every version, so
they are on this branch too, and the five port branches share one code for the channel, Discuss and the tests
(only data files, the Discuss model name, `_sql_constraints` vs `models.Constraint` and each release's own code
differ). What that adds here: `user_groups()` (groups with implied ones), `icp_get` / `icp_set`, `open_chat()`,
`members_field()` / `member_partners()`, the Discuss hook accepting both signatures, the bot kept in 19+ mention
filtering (unused before 19), `_auto_commit` also checking `current_test`, the analytic line's journal item by
version (`_orm_journal_item_field`), and in the tests: the test-mode and test-lock switches of 19 and 20, `GROUPS`,
`Params`, `flush_env`, pairing ids read before threads start, the unique-constraint check and the lots check (new
tests), `ir.access` on 20, the version's time off type.

| Final run | Apps installed | Result |
|---|---|---|
| **This branch, final** | styd_odoo_bridge, project, account, hr_holidays, hr_attendance, hr_timesheet | **181 / 181**, 1 skip (19+ status page) |
| **This branch, final** | styd_odoo_bridge only | **181 / 181** |

(181 = the 179 above plus the two new checks: the unique constraints exist in PostgreSQL, the lots model of the
version is allowed.)

## For the owner

- **Access log on 16:** added for the channel's audit. If you also want the HTTP routes audited on 16 (as on
  17+), that is the 17 controller's `_audit_log`, a separate small change.
