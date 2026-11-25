# B2 port to Odoo 17.0 (Bridge 0.11.0, lane B-17)

Date: 2026-11-25. Branch `claude/b2-port-17`, cut from `origin/17.0` at `1f63c4b` ("merge: 0.10.2 security hotfix
(17.0)"). Merge staged only: nothing committed, nothing pushed. Version not bumped: it stays `17.0.0.10.2` until
the 0.11.0 release step (owner decision). Part of the single 0.11.0 release, built the same way as the five other
ports (`claude/b2-port-15.0`, `16.0`, `18.0`, `19.0`, `20.0`).

## What was merged

The three 17 input branches are one linear chain on the common base `01bc040` (`git merge-base` checked):

| Branch | Head | Parent | Content |
|---|---|---|---|
| `claude/b2-channel-17` | `3e99f9f` | `01bc040` (+ `b9be554`) | outbound channel (M1 core, M2 executor, M3 pairing), RPC lockdown, M-R2 to M-R5 |
| `claude/b2-hr-discuss-17` | `8f7661e` | `3e99f9f` | HR allowlist M-R6, Discuss assistant and its owner decisions (`docs/DISCUSS_CONTRACT.md`) |
| `claude/b2-s4-fixes-17` | `415d568` | `8f7661e` | token bucket 40/s burst 60 from system parameters, settings read fresh each leader tick |

`origin/17.0` adds the 0.10.2 hotfix (`0f25075`, merged as `1f63c4b`) on the same base `01bc040`. So one merge of
`origin/claude/b2-s4-fixes-17` into `origin/17.0` (`git merge --no-commit --no-ff`) brings all three. The merge is
left staged (`MERGE_HEAD` = `415d568`), ready to be committed as the merge commit.

## Conflicts and how each was resolved

Seven files conflicted. They are the known overlap: the hotfix and the channel work did the same RPC lockdown
(the `_` renames of the service and ORM read entry points, the admin check on the setup wizard) with slightly
different code. Every conflict was resolved exactly as the finished 18.0 port resolved it
(`origin/claude/b2-port-18.0`, `a7d2a7c`, "0.10.2 hotfix guards kept, shared code"): its module files were taken
as they are, then only the Odoo 17 differences below were put back. **The hotfix's guards hold everywhere.**

| File | Conflict | Resolution (as 18) |
|---|---|---|
| `controllers/bridge_api.py` | hotfix kept the `/users/search` filter in the controller; channel moved it into the service | the service's `_build_user_search_payload(query)` (private, on the sudo service); controller delegates. Same body |
| `models/bridge_service.py` | the other half of the move above | channel side: `_build_user_search_payload` in the service; the hotfix's private renames (`_get_supported_features`, `_build_health_payload`, `_build_security_snapshot_payload`, `_build_user_directory_snapshot_payload`, `_build_capability_snapshot_payload`) all present |
| `models/bridge_orm.py` (2 hunks) | `_orm_search_read` / `_orm_read_group` signatures: hotfix `tz, tz_mode`; channel adds `lang, company_ids` (M-R4, M-R5) | private names (hotfix) with the channel's full signature. Plus the shared helpers `model_has_access` / `model_check_access` from the 18 port |
| `models/bridge_setup_wizard.py` (2 hunks) | import of `_`; `_check_admin` message plain (hotfix) vs translated (channel) | same guard (`env.su` or `_is_system()`, else `AccessError`), translated message; `_check_admin()` on `default_get` and on the save, generate, rotate, **revoke** and access-log buttons |
| `models/res_config_settings.py` (3 hunks) | `get_values` / `set_values`: hotfix `_styd_bridge_check_admin()`; channel Odoo's access check plus the CA bundle check | **both guards**: `model_check_access(..., "read"/"write")` **and** `_styd_bridge_check_admin()`; `set_values` still validates the CA bundle |
| `tests/__init__.py` | hotfix added `test_rpc_access`; channel added its 8 test modules | all of them |
| `tests/test_rpc_access.py` (add/add, 6 hunks) | both branches created the file | the hotfix's version-aware file (internal **and** portal users, each version's RPC path, onchange refused, the 19+ status page) plus the channel models (pairing wizard and its buttons, pairings, seen ids) and the Discuss models (`styd.discuss.question`, `inbox`, `welcome`, the `discuss.channel` extension), which define no public method and whose tables are closed |

The "status page" guard of the hotfix exists only on 19+; on 17 `test_21_status_page` skips ("no status page
before 19.0"), as on 18.

### Shared code taken from the 18 port

Beyond the conflicts, the 18 port's consistency pass (after 15, 16, 19 and 20) changed 18 files relative to the 17
inputs, all written to work on every version, so they are here too and 17 runs the same code as the other ports:
`user_groups()`, `icp_get` / `icp_set`, `open_chat()` / `channel_record()`, `members_field()` /
`member_partners()`, `model_has_access` / `model_check_access` (fall back to `check_access_rights` on 17), the
Discuss hook accepting both signatures, the bot kept in 19+ mention filtering, `_auto_commit` also checking
`current_test`, the analytic line's journal item by version (`_orm_journal_item_field`), `env._` when present
(else `_`), and in the tests: the test-mode and test-lock switches, `GROUPS`, `Params`, `flush_env`, `sync()`
flushing pending bus notifications, pairing ids read before threads start, the record-rule test switching off
Odoo's other partner group rules, the running series instead of a hard-coded `"17.0"`, the two new checks (unique
constraints exist in PostgreSQL, the version's lots model is allowed), `ir.access` on 20, the version's time off
type. Files: `models/bridge_channel.py`, `bridge_channel_executor.py`, `bridge_channel_pair.py`,
`bridge_discuss.py`, `bridge_orm.py`, `bridge_service.py`, `res_config_settings.py`, and the tests
`channel_common.py`, `test_channel_core.py`, `test_channel_executor.py`, `test_channel_pairing.py`,
`test_channel_settings.py`, `test_discuss.py`, `test_hr_read.py`, `test_read_policy.py`, `test_rpc_access.py`.

## 17 against 18: every remaining difference

`git diff origin/claude/b2-port-18.0` on this branch's staged tree. Code, tests, data, security and
`docs/DISCUSS_CONTRACT.md` are identical except:

| Path | 17 (this branch) | 18 | Why |
|---|---|---|---|
| `__manifest__.py` | `17.0.0.10.2` | `18.0.0.10.2` | version series; bump to 0.11.0 is the release step |
| `tests/test_orm_bridge.py` | `EXPECTED_MANIFEST_VERSION = "17.0.0.10.2"` | `"18.0.0.10.2"` | the version pin follows the manifest |
| `data/ir_cron_channel.xml`, `data/discuss_data.xml` | `<field name="numbercall">-1</field>` | absent | `ir.cron.numbercall` exists on 17 with default 1 (run once); removed in 18. Same as the 15 and 16 ports |
| `views/bridge_access_log_views.xml` | `<tree>`, `view_mode` `tree,form` | `<list>`, `list,form` | Odoo 18 renamed the list view type; 17 only knows `tree`. Already so on `origin/17.0` |
| `migrations/17.0.0.10.0/` | 17 folder | `18.0.0.10.0/` | migration folders follow the series; same script |
| `static/description/index.html`, `images/connection-setup.png`, `images/styd-connect.png` | Odoo 17.0 badge and screenshots | 18.0 | listing page per version, untouched by this port (as on `origin/17.0`) |
| `RESULT_HR_DISCUSS_17.md`, `RESULT_S4_FIXES_17.md` (repo root) | present | absent | the 17 input branches' own result notes, brought in by the merge; the 18 port points to them "on the 17 branches" |
| `RESULT_PORT_18.0.md` (repo root) | absent | present | 18's port note; this file is 17's |
| `validate_v18_bridge.py` (repo root) | absent | present | an 18.0 branch file from before B2 (`0b762c1`), not part of the module |

Nothing else differs: the shared helpers already handle the API differences between 17 and 18 at run time
(`has_access` / `check_access` vs `check_access_rights`, `env._` vs `_`, bus notifications in test cursors), so
no code had to be changed back for 17.

## Tests (own Docker lab, never the STYD QA labs)

Own containers only: `b2p17-pg` (`postgres:16-alpine`) and one throwaway `odoo:17.0-20260908` per run
(`b2p17-odoo-bare`, `b2p17-odoo-apps`, `--rm`), in the Postgres container's network namespace; the module copied
to the session scratchpad. Command: `odoo -d <db> -i <modules> --test-tags /styd_odoo_bridge --stop-after-init`.
All containers and the copy removed after the runs.

| Run | Apps installed | Result |
|---|---|---|
| **This branch** | styd_odoo_bridge, project, account, hr_holidays, hr_attendance, hr_timesheet | **181 / 181**, 0 failed, 0 errors; 1 skip (19+ status page) |
| **This branch** | styd_odoo_bridge only | **181 / 181**, 0 failed, 0 errors; the HR, timesheet-pay, ledger and project tests skip cleanly (apps not installed), plus the 19+ status page |

The version pin (`test_21_manifest_version_bumped`, `17.0.0.10.2`) passes: the hotfix had already aligned the
manifest and the pin, as on 18. 181 is the same count as 15, 16 and 18 (19 has 183, 20 has 185).

Log check: the only module warnings are the ones the tests provoke on purpose (refused messages with a bad
signature or a bad message, pairing refused or not confirmed, rotation not acknowledged), and Odoo's "no access
rules" notice for the five closed tables (`styd.odoo.bridge.pairing`, `styd.odoo.bridge.channel.seen`,
`styd.discuss.question`, `styd.discuss.welcome`, `styd.discuss.inbox`), closed by design. No deprecation or
translation warning from the module.

## State

- Branch `claude/b2-port-17` from `origin/17.0`, worktree
  `E:\Freelance\Flo\odoo-bridge\.claude\worktrees\b2-port-17-31a636`. HEAD is still `1f63c4b`; the merge of
  `415d568` is staged with this file, not committed. Commit it as the merge commit (`git commit`), which records
  both parents.
- The locked worktree `b2-port-17.0` and every other worktree were not touched.
