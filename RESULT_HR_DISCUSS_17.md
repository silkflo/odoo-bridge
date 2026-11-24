# Result: HR in the allowlist (M-R6) and the Discuss assistant (M-D), Odoo 17.0

Date: 2026-11-24. Branch `claude/b2-hr-discuss-17`, cut from `claude/b2-channel-17` at `3e99f9f`. Staged only:
nothing committed, nothing pushed. Part of the single 0.11.0 release.

## Tests (Odoo 17, own Docker lab, never the STYD QA labs)

Own containers: `b2hd17-pg` (`postgres:16-alpine`) and one throwaway `odoo:17.0-20260908` per run, the module
copied to the session scratchpad (no `__pycache__` in the worktree).

| Run | Apps installed | Result |
|---|---|---|
| Baseline, `3e99f9f` unchanged | styd_odoo_bridge, project, account, hr_holidays, hr_attendance, hr_timesheet | 129 / 130 (the known `test_21_manifest_version_bumped`) |
| This branch | same | **164 / 165**: the 129 still pass, all 35 new pass; the one failure is the same known version pin |
| This branch | styd_odoo_bridge only (base + mail) | 164 / 165, the HR tests skip cleanly (no HR app) |

`test_21_manifest_version_bumped` was already failing: it pins `17.0.0.10.0` while the manifest says
`17.0.0.10.1`. Left as is: the version bump belongs to the 0.11.0 release step (M5), see below.

One existing test changed on purpose: `test_channel_executor.test_10_bodies_match_the_routes` now compares
the channel's model list **minus the HR models** with the route's list (HR is listed over the channel only).

## 1. M-R6: HR

**What is in** (`models/bridge_orm.py`, `ORM_HR_FIELDS`): exactly STYD's API-key HR read
(`apps/api/src/security/odoo/odooHrAccess.ts`, origin/main), a per-model field **allowlist**:

| Model | Fields |
|---|---|
| `hr.employee.public` | id, name, active, department_id, job_id, job_title, parent_id, company_id, work_email, work_phone, user_id, tz |
| `hr.department` | id, name, complete_name, parent_id, manager_id, company_id, active |
| `hr.leave.report.calendar` | id, employee_id, department_id, company_id, state, duration, start_datetime, stop_datetime, request_date_from, request_date_to |
| `hr.leave` | id, employee_id, department_id, employee_company_id, user_id, request_date_from, request_date_to, date_from, date_to, number_of_days, number_of_hours, number_of_hours_display, state, holiday_status_id, work_entry_type_id |
| `hr.leave.type` | id, name, time_type, requires_allocation, unpaid, company_id, active |
| `hr.work.entry.type` (Odoo 20) | id, name, count_as, requires_allocation, unpaid, time_off_selectable, active |
| `hr.leave.allocation` | id, employee_id, employee_company_id, number_of_days, max_leaves, leaves_taken, date_from, date_to, state, holiday_status_id, work_entry_type_id, type_request_unit |
| `hr.attendance` | id, employee_id, check_in, check_out, worked_hours |

**Rules, as STYD's wall:**

- Every field a read touches (returned, filtered, ordered, grouped, summed) must be listed; a read must name
  its fields (a search_read with no fields, a read_group with no group_by and no aggregate: refused).
  `field_not_allowed` otherwise. The wall takes no role: `mobile_phone`, private and pay fields are refused
  for an HR officer too. `orm.fields` describes only the listed fields.
- Still never: `hr.employee`, `hr.contract`, `hr.job`, payslips, expenses, applicants, `hr.version`,
  `resource.calendar`, `res.partner.bank` (not on any list).
- **Channel only, as the member.** The HR models are readable only when the read runs as the asking member
  (the channel executor: own cursor, `SET TRANSACTION READ ONLY`, `api.Environment(cr, member_uid, …)`, no
  sudo). The sudo HTTP routes answer `model_not_allowed` and never list them in `/models`.
- **Company scope** (STYD's `ODOO_HR_COMPANY_SCOPE`, on top of Odoo's own rules): `employee_company_id` for
  time off and allocations, `company_id` for the directory, calendar, departments and types (empty allowed for
  departments and types), the employee's company (through `hr.employee.public`, as the member) for attendance.
- **Timesheet pay.** `account.analytic.line` (already open since M-R2 for the ledger) now refuses `amount`
  unless the read is limited to journal-item lines (`["move_line_id", "!=", false]` in a plain AND domain), on
  both the routes and the channel: a timesheet's amount is the employee's cost (STYD's HR wall and ledger
  rule together). A read that names no field simply leaves `amount` out.

**Tests** (`tests/test_hr_read.py`, 8):

- the module's lists equal STYD's, copied by hand (a drift fails);
- the sudo routes refuse every HR model; `hr.employee` is refused even as the member;
- an **HR officer** (HR officer, Time Off officer, Attendance officer) gets, over the channel, exactly what Odoo
  itself returns for that user (`with_user(...).search`), everyone's time off included;
- a **plain employee** gets only their own time off and attendance (search_read and read_group totals),
  the public directory's listed fields only, and `mobile_phone`, `private_email`, `birthday`,
  `km_home_work` are refused (returned or filtered), for the officer too;
- **every left-out field** of every installed HR model (fields_get minus the list, over 100 fields) is refused
  as a returned field, a filter, an order, a group-by and an aggregate; reads naming no field are refused;
- the listed fields read end to end; the company scope (time off by employee company, attendance by the
  employee's company); timesheet `amount` refused without the journal-item filter, open with it.

## 2. M-D: the Discuss assistant (module side, server only)

Files: `models/bridge_discuss.py` (models, hook, job), `models/bridge_discuss_text.py` (pure: texts in 7
languages, rendering, secret hiding, answer checks), `data/discuss_data.xml` (bot partner, job), settings
fields and view, `bridge_channel.py` (hello `features`, `discuss_answer` dispatch), `bridge_channel_protocol.py`
(the new message type), `bridge_channel_executor.py` (reads tagged with a question). Contract:
**`docs/DISCUSS_CONTRACT.md`**.

- **Bot**: partner "Speak To Your Database" (no user, no login, no seat). A direct message to it, or a
  mention of it in a channel, is a question. Only `discuss.channel` is watched, only comments by the internal
  user who posts; the bot's own posts, other bots, notifications, emails and record chatter are ignored.
- **Nobody waits on STYD**: the hook saves `styd.discuss.question` (pending) and calls the job's
  `_trigger()`. The job (`ir.cron` "Speak To Your Database: Discuss assistant", trigger + 1-minute fallback)
  sends a signed `discuss.ask` event **out** on the existing channel (`/bridge/v1/event`), with the Odoo uid,
  `conversation.key = discuss.channel:<id>` (one STYD thread per conversation), `kind`, `shared`, the user's
  `lang` and `tz`. On the ack it posts "Looking it up…" in the user's language.
- **The answer** comes down a poll as a signed `discuss_answer` (same envelope checks as a request). The poll
  thread only stores it (`styd.discuss.inbox`, insert-only, so it never fights the job for a row), triggers
  the job and reports `discuss.delivered`. The job posts it as the bot: "Understood as" line, text, HTML
  tables (built by the module, every value escaped), refusals and errors, in the answer's / user's language.
  No answer within 180 s: "did not answer in time"; a later answer is `late`.
- **Admin options** (Settings > Speak To Your Database > Discuss assistant), **off by default**: switch, who may
  ask (all internal users / a group / chosen users), the workspace when several are paired, per-user and
  per-database hourly limits. Saving with the switch on opens each allowed user's chat with the bot, with a
  welcome line (the OdooBot way: no change to Discuss screens; at most 500 per save).
- **Free replies, no call to STYD**: switched off, user not allowed ("ask your admin"), not connected, empty
  mention, rate limited (3 per user per minute, 30 per user per hour, 300 per database per hour).
- **Security**: question text sent as a JSON string, never interpreted; everything from STYD escaped; module's
  secrets and credential-shaped text hidden before posting; the answer can only become a message in the
  question's own conversation; reads stay on the read-only cursor and closed op list; reads tagged
  `discuss_question_id` must match an open question of that member, and **HR is refused when others can read
  the conversation**.

**Tests** (`tests/test_discuss.py`, 27, against the fake hub, extended to follow the contract): off by
default; a DM saves and triggers without any call to STYD; the job's signed `discuss.ask` (fields, language,
conversation key, follow-ups share it, other chats do not); mention in a channel (shared, answer posted there,
non-mentions ignored); empty mention; answer rendering (understood-as, escaped record text, table, row count,
order after "Looking it up…"); end to end through a real poll (hello `features`, `discuss.delivered`);
refusals and errors in French; answer checks (wrong member, other pairing, unknown, malformed, extra fields
pointing to another channel ignored, duplicate, late); timeout; no secret ever posted; who may ask (users,
group, portal, `__system__`, STYD-group restriction); rate limits; hub refusals (`member_unknown`,
`discuss_off`, `prompts_exhausted`, ignored); unreachable hub retried 3 times then said; not connected;
crafted text stays data and the bot cannot write; envelope rules (t/op/member, wrong secret refused before
storing); reads tagged with a question (member, open, HR refused when shared); settings open chats once;
pure text helpers (mention removal, truncation, escaping, answer limits, 7 languages complete).

## 3. Decisions to confirm (Florian)

1. **`mail` is now a dependency** (`depends: ["base", "mail"]`, was `["base"]`). Discuss needs it; almost every
   real Odoo has it. Alternative: a separate auto-install glue module, at the cost of a second module in the
   listing.
2. **Version.** The manifest stays `17.0.0.10.1`. The hub's default `min_module_version` is `0.11.0`, so the
   0.11.0 release step must bump it (and the `test_21` pin with it).
3. **Answers in channels.** A mention in a channel is answered in the channel, with the asker's own rights,
   readable by everyone there. The module refuses HR in that case; anything else private is left to STYD
   (contract §6). Option: answer channel mentions in a DM instead.
4. **Timesheet `amount`** is now refused on the sudo routes too unless the read is journal-item lines only.
   STYD's ledger reader always sends that filter, so nothing it does changes.
5. **Chats opened on save** for every allowed user, with a welcome line (like OdooBot onboarding). Users
   added later get theirs on the next save, or can mention the bot.
6. A mention of the bot on a record's chatter is ignored, but Odoo still tries to email the bot partner
   (no address: a failed notification on that message). Harmless; could be avoided by hiding the bot from
   chatter mention suggestions (a Discuss screen change, so not done).

## 4. Next

- STYD side of the contract (hub `discuss.ask` / `discuss_answer`, colour question path, `discuss.v1` in
  status): `docs/DISCUSS_CONTRACT.md` §10.
- Port to 15.0 (`mail.channel`), 16.0 (`mail.channel`), 18.0, 19.0, 20.0 (`hr.work.entry.type`, request dates on
  the calendar) with the rest of M4.
