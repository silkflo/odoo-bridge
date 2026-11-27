# Bridge 0.11.0: release candidates on Odoo 15 to 20 (M5)

Date: 2026-11-28. Six staged trees, nothing committed, nothing pushed. The release branches `15.0` to `20.0` and the
`claude/b2-port-*`, `b2-more-*`, `b2-final-*` branches were not touched.

This note lives in the session's own worktree (`claude/bridge-0-11-0-release-28786b`), not in the 20.0 release
worktree: a rule of this session blocks writing files into another worktree with the editor. It is not part of any
release tree, so committing a staged tree never ships it.

## 1. The six trees

| Version | Worktree (under `E:\Freelance\Flo\odoo-bridge`) | Branch | Source (HEAD) |
|---|---|---|---|
| 15.0 | `.claude\worktrees\b2-release-15.0` | `claude/b2-release-15.0` | `726b78e` (`claude/b2-final-15.0`) |
| 16.0 | `.claude\worktrees\b2-release-16.0` | `claude/b2-release-16.0` | `80c0ef4` (`claude/b2-final-16.0`) |
| 17.0 | `.claude\worktrees\b2-release-17.0` | `claude/b2-release-17.0` | `84d352a` (`claude/b2-more-17-32ea7c`) |
| 18.0 | `.claude\worktrees\b2-release-18.0` | `claude/b2-release-18.0` | `28a3e68` (`claude/b2-final-18.0`) |
| 19.0 | `.claude\worktrees\b2-release-19.0` | `claude/b2-release-19.0` | `6c9c7da` (`claude/b2-final-19.0`) |
| 20.0 | `.claude\worktrees\b2-release-20.0` | `claude/b2-release-20.0` | `1a3e59c` (`claude/b2-final-20.0`) |

Each source tip has the published `origin/<v>` as an ancestor (checked), so each release branch moves by fast-forward.

## 2. What changed, the same on all six

**Bump.** `__manifest__.py` `<v>.0.0.10.2` → `<v>.0.0.11.0`; the store page footer (`static/description/index.html`)
`Version: <v>.0.0.11.0`; `tests/test_orm_bridge.py` `EXPECTED_MANIFEST_VERSION` follows the manifest. The store page
names 0.11.0 everywhere it names the current version (changelog heading `0.11.0`, footer); `0.10.2` stays only as the
previous changelog entry.

**Clean-up (the milestone audit's list).** Every comment that named a STYD-internal file (the protocol document, the
read-policy and HR-access sources, the vector generator, the hub test) now says what it means without the path; the
lane tags (`B2 step M1` to `M3`, `M1`/`M2`/`M3` test headers, `M-R2` to `M-R6`, `S4 open point 6/8`, `S4 bench`,
`B0_AUDIT`, `(B2)`) are gone, and the dead pointer to `docs/B2_HARDENING.md` is removed. Files: `models/bridge_channel.py`,
`bridge_channel_executor.py`, `bridge_channel_pair.py`, `bridge_channel_protocol.py`, `bridge_orm.py`;
`tests/data/b2_protocol_vectors.json` (`_about`), `fake_hub.py`, `test_channel_core.py`, `test_channel_executor.py`,
`test_channel_pairing.py`, `test_channel_protocol.py`, `test_channel_settings.py`, `test_hardening.py`,
`test_hr_read.py`, `test_orm_bridge.py`, `test_read_policy.py`. Comments and docstrings only. The same 41 rewrites
applied once each on every version. `docs/DISCUSS_CONTRACT.md` is kept: the STYD-internal path reworded (line 7),
the lane branch name removed from line 4, and `resource.calendar.leaves` added to the shared-conversation row (refused
there as all HR, which the code already did). On 15 and 16 the access-log view comment ("Odoo 17 uses `<tree>`") is corrected (the audit's cosmetic note).

**`tests/test_rpc_access.py`** is byte-identical on all six: `action_open_access_logs` sits in `SETUP_ACTIONS`
without the version condition, as on 15 and 16 (17+ already had the button, so the meaning is unchanged there).

**HR wall: STYD's HR read since HR slice 5** (STYD `origin/main`, the HR access list). `models/bridge_orm.py`:

- `hr.employee.public` gains `leave_manager_id`, `attendance_manager_id`, `expense_manager_id`,
  `resource_calendar_id`, where the version has them. A field Odoo's own groups hide from the asker stays refused, as
  Odoo itself answers (e.g. `attendance_manager_id` for a plain employee on 17).
- New HR model `resource.calendar.leaves` (public holidays): fields `id`, `date_from`, `date_to`, `calendar_id`,
  `company_id`, `resource_id`; company scope `company_id` with rows of no company allowed (STYD's
  `{kind: company, field: company_id, allowEmpty: true}`). Read over the channel only, as the asking member's own Odoo
  user, like the other HR models: the sudo HTTP routes refuse it, and a shared Discuss conversation refuses it as all
  HR (the executor's guard uses the HR model set).
- As STYD's own guard does, a read of `resource.calendar.leaves` keeps to public holidays: its domain must hold
  `["resource_id", "=", false]` in a plain AND (no `|`, no `!`), or it is refused with `field_not_allowed`. A person's
  validated leave, which Odoo also stores there, is never read. `resource.calendar` stays closed. The plain-AND check is
  one helper now shared with the journal-items check (`_orm_plain_and_with`), same behaviour.
- `tests/data/styd_hr_read_policy.json` (parity fixture) and `STYD_HR_FIELDS` in `test_hr_read.py` carry the same
  additions. New test `TestHrRead.test_23_public_holidays_and_employee_managers`, on every version: what a plain
  employee and an HR officer read equals what Odoo lets them read; never the personal row; non-holidays domains
  refused however written; the company scope both ways; the sudo route refused; `resource.calendar` closed; the four
  directory fields read and filtered as the member (hidden ones refused). `test_21` reads the holidays with the
  public-holidays domain.
- Timesheet lines (`account.analytic.line`, `ORM_TIMESHEET_FIELDS`) gain `global_leave_id` (from
  `project_timesheet_holidays`: the public holiday Odoo wrote the line for). Same rule as the HR fields: the list is the
  same on all six, and on a database without the field a read naming it is refused with `field_not_allowed`, like any
  unknown field. The parity fixture follows. New test `TestTimesheetsAreHr.test_t05_global_leave_id_where_the_field_exists`:
  read, filtered and grouped over the channel where the field exists, refused where it does not.

## 3. Removed files, per version

| Version | Removed |
|---|---|
| 15.0 | `RESULT_PORT_15.0.md` |
| 16.0 | `RESULT_PORT_16.0.md` |
| 17.0 | `RESULT_HR_DISCUSS_17.md`, `RESULT_S4_FIXES_17.md`, `docs/B2_PORT_17.md`, `docs/B2_MORE_17.md` |
| 18.0 | `RESULT_PORT_18.0.md`, `docs/B2_TEXT_17.patch`, `validate_v18_bridge.py` (also on `origin/18.0` today: the push removes it there) |
| 19.0 | `RESULT_PORT_19.0.md` |
| 20.0 | `RESULT_PORT_20.0.md`, `docs/B2_FINAL_PORT.md` |

After this, each tree holds `styd_odoo_bridge/` and `docs/DISCUSS_CONTRACT.md` only.

## 4. Check

On each staged tree (`git grep --cached`): no STYD-internal path (`apps/`, `docs/internal`, `.ts` sources), no local
path, no lane tag or lane branch name, no real customer, no secret under `styd_odoo_bridge/`. What the scan still
finds is by design: the secret-shape regexes of the Discuss redactor, the made-up test secrets of
`b2_protocol_vectors.json`, `example.com` / `127.0.0.1` / `192.168.1.20` test hosts, the public
`speaktoyourdatabase.com` links and contact address.

## 5. Tests

Own containers only: `m5r-pg` (`postgres:16-alpine`) and one throwaway Odoo per run (`m5r-odoo`, `--rm`, in
`m5r-pg`'s network namespace), strictly one after the other; both removed at the end. No STYD lab container
(`rshb-styd-pg`, `*-styd-pg`), no production, no paid call. "Before" = `git archive <source tip>`, "after" =
`git checkout-index` of the staged index. Command as in the port lanes:
`odoo -d <db> -i <modules> --test-tags /styd_odoo_bridge --stop-after-init`. "Apps" = styd_odoo_bridge, project,
account, hr_holidays, hr_attendance, hr_timesheet (the port lanes' set). Count = Odoo's "N tests when loading".

| Version | Image | Tree | styd_odoo_bridge only | with apps |
|---|---|---|---|---|
| 15.0 | `odoo:15.0` | before (`726b78e`) | **230 / 230**, 0 failed, 0 errors (14 skips) | **230 / 230** (2 skips) |
| | | **after** (staged) | **232 / 232**, 0 failed, 0 errors (16 skips) | **232 / 232**, 0 failed, 0 errors (2 skips) |
| 16.0 | `odoo:16.0-20250909` | before (`80c0ef4`) | **230 / 230**, 0 failed, 0 errors (13 skips) | **230 / 230** (1 skip) |
| | | **after** (staged) | **232 / 232**, 0 failed, 0 errors (15 skips) | **232 / 232**, 0 failed, 0 errors (1 skip) |
| 17.0 | `odoo:17.0-20260908` | before (`84d352a`) | **230 / 230**, 0 failed, 0 errors (13 skips) | **230 / 230** (1 skip) |
| | | **after** (staged) | **232 / 232**, 0 failed, 0 errors (15 skips) | **232 / 232**, 0 failed, 0 errors (1 skip) |
| 18.0 | `odoo:18.0-20261015` | before (`28a3e68`) | **230 / 230**, 0 failed, 0 errors (13 skips) | **230 / 230** (1 skip) |
| | | **after** (staged) | **232 / 232**, 0 failed, 0 errors (15 skips) | **232 / 232**, 0 failed, 0 errors (1 skip) |
| 19.0 | `odoo:19.0-20260528` | before (`6c9c7da`) | **232 / 232**, 0 failed, 0 errors (12 skips) | **232 / 232** (0 skips) |
| | | **after** (staged) | **234 / 234**, 0 failed, 0 errors (14 skips) | **234 / 234**, 0 failed, 0 errors (0 skips) |
| 20.0 | `odoo:20.0-20261015` | before (`1a3e59c`) | **234 / 234**, 0 failed, 0 errors (13 skips) | **234 / 234** (1 skip) |
| | | **after** (staged) | **236 / 236**, 0 failed, 0 errors (15 skips) | **236 / 236**, 0 failed, 0 errors (1 skip) |

+2 on every version: `TestHrRead.test_23_public_holidays_and_employee_managers` and
`TestTimesheetsAreHr.test_t05_global_leave_id_where_the_field_exists`. With apps both run and pass on all six
(`project_timesheet_holidays` installs itself with hr_timesheet and hr_holidays, so `global_leave_id` exists there
and t05 takes its read-and-group branch). Bare, both are skipped with the rest of their classes (no HR or accounting
apps), hence +2 skips bare only. t05's "field absent" branch (refused like any unknown field) runs only on a database
with timesheets but without `project_timesheet_holidays`, which neither app set gives: covered by the validator's
existing unknown-field tests, not by a run here. The with-apps skips are the same tests before and after (15: `test_h04`
and `test_21_status_page`; 16, 17, 18: `test_21_status_page`; 20: `TestReadGroupShape.test_02`; 19: none). The bump,
the clean-up, the contract text and the `test_rpc_access.py` alignment change no count.

"After" was re-run once more (all 12 runs) after `global_leave_id` and the contract fixes; the table shows that run.
Each tested tree was then compared file by file with its staged index: identical on all six.

## 6. Left open

- Nothing from this lane. (The module's HR and timesheet lists now equal STYD's, as the parity fixture checks.)

## 7. At publish time (after the hub deploy)

Run in PowerShell from `E:\Freelance\Flo\odoo-bridge`, one version after the other. Each push is a plain
fast-forward of the release branch: Git refuses it if `origin/<v>` moved, and nothing here forces. Replace nothing:
the commands are complete.

1. Commit each staged tree (one commit per branch), then check it before pushing:

```powershell
foreach ($v in "15.0","16.0","17.0","18.0","19.0","20.0") { git -C ".claude\worktrees\b2-release-$v" commit -m "Bridge 0.11.0 for Odoo $v" }
```

```powershell
git fetch origin
```

```powershell
foreach ($v in "15.0","16.0","17.0","18.0","19.0","20.0") { git merge-base --is-ancestor "origin/$v" "claude/b2-release-$v"; if ($LASTEXITCODE) { "NOT a fast-forward: $v" } else { "$v ok: " + (git show "claude/b2-release-${v}:styd_odoo_bridge/__manifest__.py" | Select-String '"version"') } }
```

Every line must say `ok` with `<v>.0.0.11.0`. If one says `NOT a fast-forward`, stop for that version: someone
pushed to the release branch since `origin/<v>` was read here.

2. Move the release branches, after the hub deploy (the new hub refuses a module older than 0.11.0 with `426 module_too_old`):

```powershell
foreach ($v in "15.0","16.0","17.0","18.0","19.0","20.0") { git push origin "refs/heads/claude/b2-release-${v}:refs/heads/$v" }
```

Or one at a time, e.g. for 17.0:

```powershell
git push origin refs/heads/claude/b2-release-17.0:refs/heads/17.0
```

3. Check what is published:

```powershell
git fetch origin; foreach ($v in "15.0","16.0","17.0","18.0","19.0","20.0") { "$v " + (git rev-parse --short "origin/$v") + " " + (git rev-parse --short "claude/b2-release-$v") }
```

Both hashes must match on each line. The local checkouts of the release branches (`odoo-bridge-release-20.0` on `20.0`,
`odoo-bridge-listing-<v>` on `15.0` to `19.0`) do not move by themselves; update them with `git pull --ff-only` there
if they are used again.
