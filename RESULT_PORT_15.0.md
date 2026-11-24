# Result: M4 port to Odoo 15.0

Date: 2026-11-24. Branch `claude/b2-port-15.0`, cut from `origin/15.0` at `6b5b4c8` ("merge: 0.10.2 security hotfix
(15.0)"). Staged only: nothing committed, nothing pushed, version not bumped (stays `15.0.0.10.2`; the 0.11.0
release step bumps it). Part of the single 0.11.0 release.

**What is ported:** everything on `claude/b2-s4-fixes-17`: the outbound channel (M1 to M3), the RPC lockdown and
allowlist work (M-R2 to M-R5), HR over the channel (M-R6), the Discuss assistant (M-D, `docs/DISCUSS_CONTRACT.md`)
and the S4 fixes (token bucket 40/s burst 60 as system parameters; channel settings read fresh at each leader
tick). Behaviour: `RESULT_S4_FIXES_17.md` and `RESULT_HR_DISCUSS_17.md` on the 17 branches.

## How it was ported

From the 16 port (already on `mail.channel`, with the access log added and 16's settings layout), brought up to the
final version-neutral code of the 18, 19 and 20 ports, by a 3-way merge base `origin/16.0`, ours `origin/15.0`,
theirs that tree. No textual conflict: 15's own controller (`werkzeug` `Response`, `default=str`, the
`text/plain` POST note) stays as it is, with the shared `_json_default` import, `lang` / `company_ids` and
`/users/search` from the service.

## What differed on 15

| Topic | 16 | 15 (this branch) |
|---|---|---|
| **Lots** | `stock.lot` | **`stock.production.lot`** added to the allowlist (STYD reads lots under that name on 15: `odooSafetyNetAccess.ts`); `stock.lot` stays (absent on 15, answered `model_not_installed`). The allowlist test lists it on 15; a version-aware test checks it |
| **Timesheet pay wall** | journal item `move_line_id` | the analytic line's journal item is **`move_id`** on 15: the wall now asks for `[<journal item>, "!=", false]` with the version's field (`_orm_journal_item_field`), and the refusal names it. Without this, every `amount` read was refused on 15, filter or not |
| Discuss members | `channel_member_ids` (`mail.channel.member`) | `channel_last_seen_partner_ids` (`mail.channel.partner`): `members_field()` / `member_partners()` |
| `add_members` (tests) | `post_joined_message` | no such argument |
| ORM flush / invalidate (tests) | `flush_all()` / `invalidate_all()` | `env["base"].flush()` / `invalidate_cache()` (`flush_env()`) |
| Analytic plans (test data) | `account.analytic.plan` | none before 16 |
| Python | 3.10+ | 3.9: every file compiled with the 15 image's Python first |
| Discuss model, `channel_get`, access log, settings layout, `numbercall`, access checks | as on 16 | as on 16 (`RESULT_PORT_16.0.md`) |

Unchanged on 15: `mail.channel` has the `group` type, `channel_get` (a dict, as on 16),
`cr.flush()` and pre-commit hooks, `registry.enter_test_mode`, `Command`, `_message_post_after_hook(message,
msg_vals)`, `ir.cron._trigger`, the HR models and every field STYD reads (all HR tests ran with the apps).

## Tests (own Docker lab, never the STYD QA labs)

Own containers: `s4pt-pg` (`postgres:16-alpine`) and one throwaway `odoo:15.0` per run, in the Postgres container's
network namespace; the module copied to the session scratchpad. All removed after the work.

| Run | Apps installed | Result |
|---|---|---|
| Before: `origin/15.0` unchanged | styd_odoo_bridge, project, account, hr_holidays, hr_attendance, hr_timesheet | 48 / 48 |
| Before: `origin/15.0` unchanged | styd_odoo_bridge only | 48 / 48 |
| First port run | apps / bare | 179 / 181 (allowlist pin, timesheet pay wall on `move_line_id`) / 180 / 181 |
| **After** | styd_odoo_bridge, project, account, hr_holidays, hr_attendance, hr_timesheet | **181 / 181**, 1 skip (the 19+ status page) |
| **After** | styd_odoo_bridge only | **181 / 181**; HR, timesheet-pay, ledger and project tests skip cleanly |

The version pin (`15.0.0.10.2`) passes. No deprecation warning from the module.

## For the owner

- **Access log on 15:** added for the channel's audit, as on 16 (the HTTP routes of 15 stay unaudited).
- **Timesheet pay on 15:** STYD's ledger reader sends `move_line_id`; on 15 that domain is refused as an unknown
  field (the module validates every field). STYD has no Odoo 15 field fixture for analytic lines today, so
  nothing it does changes; if it reads them on 15 one day, it must send `move_id` there.
