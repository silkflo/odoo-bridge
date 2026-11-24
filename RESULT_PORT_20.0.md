# Result: M4 port to Odoo 20.0

Date: 2026-11-24. Branch `claude/b2-port-20.0`, cut from `origin/20.0` at `f07a617` ("merge: 0.10.2 security hotfix
(20.0)"). Staged only: nothing committed, nothing pushed, version not bumped (stays `20.0.0.10.2`; the 0.11.0
release step bumps it). Part of the single 0.11.0 release.

**What is ported:** everything on `claude/b2-s4-fixes-17`: the outbound channel (M1 to M3), the RPC lockdown and
allowlist work (M-R2 to M-R5), HR over the channel (M-R6, including `hr.work.entry.type`, which is 20's time off
type), the Discuss assistant (M-D, `docs/DISCUSS_CONTRACT.md`) and the S4 fixes (token bucket 40/s burst 60 as
system parameters; channel settings read fresh at each leader tick). Behaviour: `RESULT_S4_FIXES_17.md` and
`RESULT_HR_DISCUSS_17.md` on the 17 branches.

## How it was ported

From the finished 19 port (`claude/b2-port-19.0`, which already holds the 0.10.2 hotfix merge, the 18 and 19
changes and `models.Constraint`), by a 3-way merge base `origin/19.0`, ours `origin/20.0`, theirs the 19 port. One
conflict: the manifest's data list (20 renamed the ACL file). 20's own changes stay: `ir.access.csv`, the private
`_read_group` path (`ORM_USE_PRIVATE_READ_GROUP = True`), the `'today'` filter, `_icp_get` / `_icp_set` in the
service, and its `test_rpc_access` helpers for `get_str` / `set_str` (whose fallback called itself; corrected
to `get_param`, dead code on 20).

## What differed on 20

| Topic | 19 | 20 (this branch) |
|---|---|---|
| **System parameters** | `get_param` / `set_param` | gone (`get_str` / `set_str`): new `icp_get` / `icp_set` in the executor, used by the channel, the pairing, the executor and Discuss; tests keep the old names through a thin wrapper. The fresh read of the leader (plain SQL) was unaffected |
| ACL file | `ir.model.access.csv` | `ir.access.csv`: the pairing wizard's admin row added in 20's format (`crud`) |
| Rights and rules | `ir.model.access` + `ir.rule` | one `ir.access` model (tests: the no-ACL check for the secret tables, and the record-rule test written with `ir.access`; the admin gets an explicit read so only the member is filtered) |
| Test mode | `registry_enter_test_mode()` | `registry_test_mode()` context manager |
| Test cursors from other threads | | open with `flushing_cursor()`, which resets the test's own cursor while they are open: the tests read their pairing ids right after creating them, never while channel threads run (`_disable_flushing_cursor` was tried and dropped: it hides the main transaction's cache invalidations from the threads) |
| Discuss hook | `_message_post_after_hook(message, msg_vals)` | `(message)`: the override takes both and rebuilds the values from the message on 20 |
| Direct chat | `_get_or_create_chat(partners, pin=True)` | no `pin`: `open_chat()` checks the signature |
| Adding members (tests) | `add_members(partner_ids=…)` | `_add_members(partners=…)` |
| Bus notifications (test) | | a chat deleted with its welcome still queued for the bus broke the next flush: the test flushes first |
| HR time off types | `hr.leave.type`, `holiday_status_id` | `hr.work.entry.type` (needs a `code`), `work_entry_type_id` (test data; the allowlist already had both) |
| HR access of a plain employee (test) | `base.group_user` reads own time off | needs the time off employee group, which 20 gives new users through `base.default_user_group`; the test's plain employee gets it, as a real one does |
| Bot avatar in XML data | `type="base64"` | `type="bytes"` (deprecated otherwise) |
| `ir.cron`, `models.Constraint`, groups, test lock, mentions | | as on 19 |

## Tests (own Docker lab, never the STYD QA labs)

Own containers: `s4pt-pg` (`postgres:16-alpine`) and one throwaway `odoo:20.0-20261015` per run, in the Postgres
container's network namespace; the module copied to the session scratchpad. All removed after the work.

| Run | Apps installed | Result |
|---|---|---|
| Before: `origin/20.0` unchanged | styd_odoo_bridge, project, account, hr_holidays, hr_attendance, hr_timesheet | 52 / 52 |
| Before: `origin/20.0` unchanged | styd_odoo_bridge only | 52 / 52 |
| First port run | both | 80 / 184 (`registry_enter_test_mode` gone) |
| Then | both | 150, 157, 178, 183 / 184 as each difference above was handled |
| **After** | styd_odoo_bridge, project, account, hr_holidays, hr_attendance, hr_timesheet | **184 / 184**, 1 skip (20 has no legacy `read_group` to compare the adapter with, as in the baseline) |
| **After** | styd_odoo_bridge only | **184 / 184**; HR, timesheet-pay, ledger and project tests skip cleanly |

The version pin (`20.0.0.10.2`) passes. No deprecation warning from the module in either log.

## Consistency pass (after 15)

The 15 port found more version differences. Their fixes are written to work on every version, so they are on this
branch too, and the five port branches share one code for the channel, Discuss and the tests (only data files, the
Discuss model name, `_sql_constraints` vs `models.Constraint` and each release's own code differ). What that adds
here: `members_field()` / `member_partners()`, the analytic line's journal item by version
(`_orm_journal_item_field`), and in the tests `flush_env`, analytic plans only where they exist, the lots check
(new test).

| Final run | Apps installed | Result |
|---|---|---|
| **This branch, final** | styd_odoo_bridge, project, account, hr_holidays, hr_attendance, hr_timesheet | **185 / 185**, 1 skip (as above) |
| **This branch, final** | styd_odoo_bridge only | **185 / 185** |

(185 = the 184 above plus the lots check.)
