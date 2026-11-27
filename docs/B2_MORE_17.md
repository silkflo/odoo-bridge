# Bridge 0.11.0 on Odoo 17: SEC-M and M-MORE (module side)

Branch `claude/b2-more-17-32ea7c`, worktree `E:\Freelance\Flo\odoo-bridge\.claude\worktrees\b2-more-17-32ea7c`. It
continues the work found at step 0 (see below), from `bf18899`. This lane's changes are staged, not committed, not
pushed. The version is not bumped (that is M5). No release branch (15.0 to 20.0) was touched.

## Step 0: what was already there

| Ref | Head | Holds |
|---|---|---|
| `claude/b2-port-17` (= `origin/claude/b2-port-17`) | `60b9b15` | the 0.11.0 port to 17 (base) |
| `claude/b2-sec-17` (worktree `b2-sec-17`) | `a083db0` | SEC-M, committed: approval step, database binding, timesheets as HR, Settings guard test, Discuss audience and posting checks, plain-text links, owner and context arguments, free-line limit. Untracked note `docs/B2_HARDENING.md` |
| `claude/b2-more-17` (worktree `b2-more-17`) | `bf18899` | M-MORE, committed on top of `a083db0`: directory paging, `public_url` at pairing and in the hello, `module_version` in health and the snapshot, `restaurant.table` readable, approval texts in the module, a stronger Settings test |
| `claude/b2-sec-<v>`, `claude/b2-more-<v>` for 15.0, 16.0, 18.0, 19.0, 20.0 | | the same two commits on each port |

Both 17 commits were checked against the review, the audit and STYD's contract (below) and kept. This lane adds what
they lacked: the store texts, the contract fixes found by the check, and the join-link tests. The `b2-more-17` worktree
was not changed (a session rule keeps this lane inside its own worktree): this branch is `claude/b2-more-17` plus this
lane's staged changes. To land it on `claude/b2-more-17`, commit here and fast-forward that branch to the commit.

Sources read (with `git show`, nothing checked out): STYD `origin/claude/bridge-b2-security-review` `ff73c4b1`
(review), `origin/claude/bridge-b2-milestone-audit` `196efa86` (audit), `origin/claude/bridge-b2-text-notes`
`e0e71e91` (text notes), `origin/claude/bridge-discuss-join` `c006ef70` (STYD's 0.11.0 contract as built: stages A and
B and the join link; `B2_PROTOCOL.md` §16 to §18, `BRIDGE_B2_SEC_FIXES.md`, `B2_INTEGRATION.md`, `B2_DISCUSS_JOIN.md`
and the hub and client sources). The 17 store-text patch is `docs/B2_TEXT_17.patch` on `origin/claude/b2-text-18.0`.

## 1. SEC-M: the findings the review gives the module

The review gives the module H1, M1, M2, M3, M4 (defaults), M7, M9, L1, L5 to L10. The owner's decisions in
`BRIDGE_B2_SEC_FIXES.md` settle the rest: **L4, L5 and L6 deferred**, **M9: administrators are not refused** as members,
**M4: administrators and ordinary data unchanged** (STYD walls unlinked members). M5's fix is STYD's (explicit identity,
fail closed); the module keeps its check on `discuss_question_id`.

| Finding | Closed by | Tests |
|---|---|---|
| H1 copy of a paired database takes over the channel | `a083db0`: the pairing records `database.uuid` and `database.create_date`; a copy never streams (`database_copied` in the wizard, `not_paired` on the wire); `data/neutralize.sql` unpairs on neutralization. **This lane:** a hello refused `409 pairing_moved` stops polling for at least `retry_after_s` (300 s) and the wizard says the database was copied or moved (§16 [M]) | `test_hardening` h01 to h04; `test_contract_more` c02 |
| M1 timesheets not mirrored | `a083db0`: `account.analytic.line` not journal-items-only is HR: refused on the HTTP routes, 11 fields and company scope over the channel, refused when shared; STYD's HR list as a fixture | t01 to t04 |
| M2 Settings guard on 17 | already on `60b9b15` (hotfix merged); `a083db0`/`bf18899`: a test that grants a non-admin group ACL rights and calls this module's own override | s01 |
| M3 stolen pairing code | `a083db0`: `paired` held `waiting_approval`, `pairing_not_approved` until an admin approves, every admin told, Approve / Refuse in the wizard, "never share the code" | m01 to m06 |
| M4 defaults | `a083db0`: the wizard warns when the connector owner is in `base.group_system`. The rest is STYD's (owner decision) | o04 |
| M7 in-channel answers reach portal users and guests | `a083db0`: members read again at post time, any non-internal member sends the answer to the asker's DM; setting help says who sees it | d01, d02 |
| M9 hub trust (module half) | `a083db0`: web addresses in answers shown as plain text; owner-in-admin warning. Admins stay allowed (owner decision) | d03, o04 |
| L1 post as the bot through RPC | `a083db0`: `message_post` with the bot as author refused unless the module posts | d04 |
| L7 small leaks | `a083db0`: fixed messages for owner-op failures, exception type only in the log | o01 |
| L8 context keys decide sudo and the owner | `a083db0`: explicit arguments; routes strip both keys | o02, o03 |
| L9 free bot lines unlimited | `a083db0`: one per user per minute | d05 |
| L10 settings selection reads pairings with sudo | `a083db0`: empty unless Settings administrator | d06 |
| L5, L6 | deferred by the owner; nothing changed | – |

## 2. M-MORE

| Item | Where | Tests |
|---|---|---|
| User-directory paging (R0 H4) | `bf18899`: `GET /users/directory?cursor=&limit=` and op `users.directory {cursor?, limit?}`: pages in id order, `next_cursor` (digit string, `null` on the last page), `400 invalid_cursor` / `invalid_limit`; `users.search` searches every user and adds `truncated`; feature `odoo_user_directory_paging_v1` | `test_directory_and_version` p01 to p08 |
| Public URL at pairing | `bf18899`: `public_url` (`web.base.url`, cleaned: http(s), no credentials, query or fragment, no trailing slash, else `null`) in the first pair message and every hello | u01 to u04 |
| `module_version` | `bf18899`: `x.y.z` from the manifest at the top level of `/health` and `/security/snapshot` (HTTP and channel), the hello and the pair message; `bridge_version` stays `"0.3.0"`; the Odoo 15 `"0.0.0"` bug fixed (manifest reader fallback) | v01, v02 |
| `restaurant.table` opened, `payment.transaction` refused | `bf18899`: allowlist | `test_read_policy` r2_restaurant_tables, r2_allowlist_widened (refused list) |
| M2 regression test | `a083db0` + `bf18899` (see above) | s01 |
| Personal join link | **None** in code. STYD (§18) asks nothing of 0.11.0: the `join_required` / `ask_in_direct_message` / `join_limit` refusals are shown as `refusal.message`, and `action` (the button) is ignored by `validate_answer`. **This lane:** tests that pin it, and `DISCUSS_CONTRACT.md` §4.1b. The button is for a later module version (`B2_DISCUSS_JOIN.md` §10.1) | `test_join_link` 01 to 04 |
| Texts aligned with the code | **This lane**, see below | – |

### Texts (this lane)

The 17 store texts come from the text lane's patch (`B2_TEXT_17.patch`, applied cleanly here: manifest summary, store
page, setup view), then aligned with the code:

- **Approval**: step 3 now says where: "Then, in Odoo, open Speak To Your Database > Connect without opening a port and
  click Approve". The changelog line ("a new connection starts only after an administrator approves it") is now true
  (SEC-M). The module's own texts already name that place (`bf18899`).
- **Copied database**: "A copied or restored database never takes over" said more than the code does (a database
  restored "as moved", a `pg_dump` or a disk snapshot keeps the uuid and creation date). Now: "A copy of the database
  (duplicated, or restored as a copy) never takes over the connection: it stays unpaired until you pair it again."
  `DISCUSS_CONTRACT.md` §11 already says "unpair before copying" for the other cases.
- **Unlinked members** (FAQ "Whose access rights apply?"): the outbound connection part is what STYD enforces (SEC-S M4:
  ordinary data as the connector owner, HR and the sensitive families closed); Discuss now says what the join link
  does: no answer before joining, a personal link in the asker's direct chat.
- **One "Custom plan" mention**: 5 mentions on 4 lines; one kept, in the FAQ answer about Odoo Online.
- **Restaurant tables** added to the changelog's "more Odoo data" line.
- **15/16 access-log step**: not on 17 (17 has the "Open Access Logs" button and the step); carried to 15 and 16 below.
- Not changed (not in this lane's list): "behind Cloudflare" (still unproven: owner lab), "(you can try it on sample
  data)" in the setup view (the text notes call that wording unprovable), the footer version (M5).

## 3. Contract check against STYD `c006ef70`

Everything STYD's hub, its client and its fake module send to or expect from the module, against this tree. "Fixed
here" rows were mismatches before this lane.

| # | Message / field | STYD expects | Module | Verdict |
|---|---|---|---|---|
| 1 | `/bridge/v1/pair` first call: `t`, `protocol`, `module_version`, `odoo_series`, `db_uuid`, `owner_uid`, `code_hash`, `db_name`, `company_name`, `public_url` | names as listed; `db_name` / `company_name` string ≤ 128 or null (over 128: `400 bad_message`) | `bridge_channel_pair.py` `run_pair_session`, info in `action_show_code` | match; **fixed here**: both names cut to 128 (were sent whole) |
| 2 | `module_version` | `x.y.z`, compared with the hub's minimum `0.11.0`; `"0.0.0"` read as older than 0.11.0 | from the manifest (`17.0.0.10.2` gives `0.10.2`) | match in shape. **Value**: below the hub's minimum until the M5 bump (426 `module_too_old` at pair and hello) |
| 3 | `public_url` in the pair message and every hello | string or null; the hub refuses localhost and some IP classes itself | `clean_public_url(web.base.url)`, key always present | match |
| 4 | `pair_wait`, `paired` (`pairing_id`, `secret`, `workspace_label` ≤ 80, `workspace_id`, `claimant_email_domain` or null), `paired_ack` / `pair_done`, refusals 429 / 410 / 400 / 426 / 503 | §5, §16 | reads `workspace_name` then `workspace_label`; held `waiting_approval` | match |
| 5 | hello: `t`, `protocol`, `module_version`, `odoo_series`, `db_uuid`, `ops`, `features`, `instance`, `public_url` | §6.1, §17 | `PairingStream.hello` | match |
| 6 | hello `instance` stable for the life of the Odoo process (§16 [M]) | Discuss answers go only to the instance live at the ask | was new for each stream (a restart in the same process lost pending answers as `instance_changed`) | **fixed here**: one `PROCESS_INSTANCE` per process |
| 7 | `409 pairing_moved` + `retry_after_s` 300 (§16 [M]) | stop, tell the admin, never retry sooner | was not handled: hello again every ≤ 60 s, "Connecting (pairing_moved)" | **fixed here**: paused ≥ `retry_after_s` (at least 300 s), status `pairing_moved`, wizard text; the pairing stays (not an unpair) |
| 8 | `409 hello_required` (no session, or a poll from an IP not bound to it) | hello again at once | `_session_lost`, hello | match |
| 9 | `401 not_paired` on a poll | keep, retry every 10 min, alert after 24 h | as asked | match |
| 10 | `426`, `429 retry_after_s` | §11 | 1 h pause; `retry_after_s` | match |
| 11 | `503 hub_draining` + `retry_after_s` | §11: back off 1, 2, 4 … 60 s with jitter, as after any failed poll | that backoff (`retry_after_s` not read) | match (kept as §11 says; `test_channel_core` test_16 pins it) |
| 12 | envelopes `request` / `ping` / `rotate` / `unpaired` / `discuss_answer`: `t, v, id, ts, op, member_uid, pairing_id, args_json, sig, timeout_ms?` | §4.1 | `check_envelope` | match |
| 13 | `/result`: `{t:"results", results:[{t:"result", id, ok, status, body, exec_ms} or {ok:false, error:{code, message?}}]}` | §6.3 | executor | match |
| 14 | `pairing_not_approved` | `ok:false` `error.code` (a route body with that error is read the same) | executor, before any op | match |
| 15 | `not_paired` for a copied database | the hub ends the session and keeps the refusal | executor guard; a copy never streams | match |
| 16 | other module codes: `busy`, `op_not_allowed`, `member_not_allowed`, `member_missing`, `bridge_disabled`, `module_error`, `bad_signature`, `stale_request`, `replayed_request`, `wrong_pairing` | §9.1 | executor / stream | match |
| 17 | op `health` / `GET /health`: `ok`, `bridge_version`, `server_time_utc`, `supported_features`, top-level `module_version` | `bridgeTypes.ts`, `bridgeModuleVersion.ts` | `build_health_payload` | match |
| 18 | op `security.snapshot` / `GET /security/snapshot`: `bridge_version`, `snapshot_version`, `generated_at_utc`, `instance`, `connector_owner`, `company_scope`, `groups`, `model_access`, top-level `module_version` | same | `_build_security_snapshot_payload` | match |
| 19 | `GET /users/directory?cursor=&limit=`, op `users.directory {cursor?, limit?}` | cursor `^[0-9]{1,18}$`; STYD sends no `limit` | cursor digits; `limit` 1 or more, over 100 clamped to 100 | match (the clamp is unreachable: STYD never sends a limit; §17's "1 to 100" reads it as a range) |
| 20 | `next_cursor` | digit string or `null`, key present | `str(id)` or `None` | match |
| 21 | `400 invalid_cursor` / `invalid_limit` | HTTP: non-2xx with `error` / `detail`; channel: `ok:true` + status 400 | `{"ok":false,"error":code,"detail":…}` | match |
| 22 | directory entry: `odoo_user_id`, `is_active`, `allowed_company_ids`, `default_company_id` | `odooDirectoryMapping.ts` | `_build_directory_users` | match |
| 23 | `users.search {q}`, `truncated` | `truncated` bool | present | match (see STYD point 1 below) |
| 24 | `search-read` / `read-group` `company_ids`, `lang`; `400 company_invalid` / `lang_invalid` | §17 | routes and executor | match |
| 25 | events `pong`, `rotate_ack`, `rotate_request`, `unpair {reason:"admin"}` | §6.4 | stream / wizard | match |
| 26 | `discuss.ask`: `question_id`, `member_uid`, `conversation {key, kind chat/channel/group, shared, asked_in}`, `lang`, `tz`, `text` ≤ 2064, `truncated`, `asked_at`, `attempt` 1 to 10 | `discussProtocol.ts` | `_ask_payload` | match; **fixed here**: `kind` / `asked_in` were the raw `channel_type` (a live-chat or WhatsApp channel gave `400 bad_message`); now any other type is sent as `channel` (it is shared already) |
| 27 | ack to `discuss.ask`: `accepted`, `code` (`discuss_off`, `member_unknown`, `member_not_allowed`, `prompts_exhausted`, `rate_limited`, `busy`, `discuss_unsupported`), `retry_after_s` | §3.1 | `_handle_ack` | match (`discuss_unsupported` gets the generic "could not reach" line) |
| 28 | `discuss_answer`: `question_id`, `status`, `lang`, `understood_as`, `text`, `tables`, `refusal {code, message}`, `error`, `thread_id`, `action` | `discussProtocol.ts` | `validate_answer` (known keys only), `render_answer` | match: `thread_id` and `action` ignored |
| 29 | `join_required` / `ask_in_direct_message` / `join_limit`; the link whole through `redact` / `delink` | §18 | shown as text; token parts never 43 long | match (tests added) |
| 30 | `discuss.delivered`: `question_id` required, `code` | the hub answers 400 without a question id | was sent with `question_id: null` for an answer without a valid id | **fixed here**: not sent then (logged) |

**For STYD (not changed here):**

1. `bridgeTypes.ts` `isUserSearchPayload` requires a `results` array; the module (and `B2_PROTOCOL.md` §7) answer
   `users`. STYD's `searchUsers` would always fail. No STYD screen calls it today.
2. The hub's minimum is 0.11.0: the 17 candidate reads as 0.10.2 until M5 bumps the manifest to `17.0.0.11.0`.

## 4. Changes of this lane (staged)

| File | Change |
|---|---|
| `models/bridge_channel.py` | `PROCESS_INSTANCE` (one hello `instance` per process); `409 pairing_moved` handled (`PAIRING_MOVED_RETRY_S` 300); no `discuss.delivered` without a question id |
| `models/bridge_channel_pair.py` | `db_name`, `company_name` cut to 128; wizard text for `pairing_moved` |
| `models/bridge_discuss.py` | `wire_kind`: `discuss.ask` kinds limited to chat / channel / group |
| `__manifest__.py` (summary), `static/description/index.html`, `views/bridge_setup_views.xml` | the 17 text patch, then aligned (section 2) |
| `docs/DISCUSS_CONTRACT.md` | §4.1b: refusals for askers not linked yet, `action` ignored |
| `tests/test_contract_more.py` (new, 5 tests), `tests/test_join_link.py` (new, 4 tests), `tests/__init__.py` | the tests |
| `docs/B2_MORE_17.md` | this note |

## 5. Tests

Own containers only: `bm17-pg` (`postgres:16-alpine`) and one throwaway `odoo:17.0-20260908` per run (`--rm`, in the
Postgres container's network), the module copied to the session scratchpad. Command, as in the port lanes:
`odoo -d <db> -i <modules> --test-tags /styd_odoo_bridge --stop-after-init`. "Apps" = styd_odoo_bridge, project,
account, hr_holidays, hr_attendance, hr_timesheet. No STYD lab container, no production, no paid call.

| Tree | styd_odoo_bridge only | with apps |
|---|---|---|
| `60b9b15` (`claude/b2-port-17`, before SEC-M) | **181 / 181**, 0 failed, 0 errors (10 skips: apps not installed, 19+ status page) | **181 / 181** (1 skip: 19+ status page) |
| `bf18899` (`claude/b2-more-17`: SEC-M + M-MORE, before this lane) | **221 / 221** (13 skips) | **221 / 221** (1 skip) |
| **This tree** (`bf18899` + this lane's staged changes) | **230 / 230**, 0 failed, 0 errors (13 skips) | **230 / 230**, 0 failed, 0 errors (1 skip) |

+40 from SEC-M and M-MORE (`test_hardening` 25, `test_directory_and_version` 14, `test_read_policy` +1), +9 from this
lane (`test_contract_more` 5, `test_join_link` 4). The module's warnings in the log are the same before and after this
lane (only the ones the tests provoke on purpose). The two runs of a tree go one after the other: two Odoo containers
in the same network namespace both listen on 8069, and a first attempt run side by side failed an HTTP test
(`test_token_migration`, 403 from the other server); the sequential runs are the ones above.

`restaurant.table`'s real read (`test_r2_restaurant_tables`) needs `pos_restaurant`, which neither app set installs:
the runs check the allowlist and the `model_not_installed` path only.

## 6. What the ports to 15, 16, 18, 19, 20 must carry

Each `claude/b2-more-<v>` already has the two commits (SEC-M, M-MORE). On top, from this lane:

1. The four code changes of section 4 (`bridge_channel.py`, `bridge_channel_pair.py`, `bridge_discuss.py`): the
   channel and pairing files are byte-identical across versions, so they apply as is. In `bridge_discuss.py`, 15 and 16
   use `mail.channel` (`channel_type` the same values): `wire_kind` applies unchanged.
2. `tests/test_contract_more.py` and `tests/test_join_link.py`, with their `__init__.py` lines. On 15/16 the Discuss
   test class reads `mail.channel` through `DiscussCase` as the other Discuss tests do.
3. `docs/DISCUSS_CONTRACT.md` §4.1b.
4. The texts: each version's store text lives on `claude/b2-text-<v>` (one commit on its port tip). Bring that commit
   in, then make the same edits as section 2: the approval step's place, the copied-database line, the unlinked-member
   FAQ (outbound connection and Discuss join link), one "Custom plan" mention (each text branch has 5 on 4 lines),
   restaurant tables in the changelog.
5. **15 and 16 only**: their setup view (`views/bridge_setup_views.xml`) has no "Open Access Logs" button and no
   "Review the Access Logs" step, though the store page advertises the access log and the port added the menu. Add
   both as on 17 (`bridge_setup_views.xml` line 26 and the step in the list).
6. M5, per version: bump to `x.0.0.11.0` (manifest, footer), and the clean-up the audit lists (result notes, STYD paths
   in comments, the 17 patch on the 18 branch).
