# Bridge 0.11.0: the 17 lane carried to 15.0, 16.0, 18.0, 19.0, 20.0

Source: `origin/claude/b2-more-17-32ea7c` at `84d352a` and its note `docs/B2_MORE_17.md`, section 6 ("What the ports
must carry"). One worktree and one branch per version, each started from `origin/claude/b2-more-<v>` (SEC-M and M-MORE
already committed there). Everything below is **staged, not committed, not pushed**. The version is not bumped (M5).
No release branch (15.0 to 20.0) and no `claude/b2-port-*` branch was touched.

| Version | Branch | Worktree | HEAD (= `origin/claude/b2-more-<v>`) |
|---|---|---|---|
| 15.0 | `claude/b2-final-15.0` | `E:\Freelance\Flo\odoo-bridge\.claude\worktrees\b2-final-15.0` | `ebe220d` |
| 16.0 | `claude/b2-final-16.0` | `E:\Freelance\Flo\odoo-bridge\.claude\worktrees\b2-final-16.0` | `c5b08db` |
| 18.0 | `claude/b2-final-18.0` | `E:\Freelance\Flo\odoo-bridge\.claude\worktrees\b2-final-18.0` | `9cc55a9` |
| 19.0 | `claude/b2-final-19.0` | `E:\Freelance\Flo\odoo-bridge\.claude\worktrees\b2-final-19.0` | `2a345e4` |
| 20.0 | `claude/b2-final-20.0` | `E:\Freelance\Flo\odoo-bridge\.claude\worktrees\b2-final-20.0` | `0c14198` |

## 1. What was applied, the same on every version

| # | Item (B2_MORE_17 §6) | How | Result |
|---|---|---|---|
| 1 | The version's store-text commit | `git cherry-pick -n origin/claude/b2-text-<v>` (15.0 `b4e311e`, 16.0 `f892d90`, 18.0 `270de80`, 19.0 `12dccdc`, 20.0 `f9481f4`) | clean on all five: manifest summary, store page, setup view |
| 2 | Code of `84d352a` | `bridge_channel.py` and `bridge_channel_pair.py` were byte-identical to 17's before the lane on every version (`2f15e82`, `f62545c`), so 17's new files were taken whole. `bridge_discuss.py` differs per version: 17's hunk (`wire_kind`) applied with `git apply -3` | clean on all five; the staged channel and pairing files equal `84d352a`'s |
| 3 | Tests | `test_contract_more.py`, `test_join_link.py` taken whole from `84d352a`; the two `__init__.py` lines applied with `git apply -3` | clean; the two files equal `84d352a`'s |
| 4 | `DISCUSS_CONTRACT.md` §4.1b | the file was identical to 17's before the lane (`ece81d7`), so 17's new file was taken whole | equals `84d352a`'s |
| 5 | Text edits as on 17 | the 7 store-page lines `84d352a` changed after the text patch, replaced by exact line match (each old line matched once on every version) | 7 of 7 on each version |

The text edits (item 5), with 17's wording:

- **Approval step's place** (step 3): "Then, in Odoo, open **Speak To Your Database > Connect without opening a port**
  and click **Approve**."
- **Copied database** (changelog): "A copy of the database (duplicated, or restored as a copy) never takes over the
  connection: it stays unpaired until you pair it again."
- **Unlinked members** (FAQ "Whose access rights apply?"): the outbound-connection part (connector owner's rights, HR and
  sensitive areas closed) and the Discuss part (no answer until they join; a personal join link in their direct chat).
- **One "Custom plan" mention**: 4 lines carried it on each text branch (5 mentions); 3 lines edited, the one kept is
  the FAQ answer about Odoo Online, as on 17.
- **Restaurant tables**: "Point of Sale (restaurant tables included)" in the changelog's "more Odoo data" line.

After the edits, each version's store page differs from 17's (`84d352a`) only in what belongs to the version: the
"This module: Odoo <v>" badge, the example-questions line, the footer version, and on 15 and 16 the changelog line
"Access log: new on Odoo <v>". The manifest summary equals 17's; the manifest version is unchanged.

## 2. Per version: adaptations

### 15.0 and 16.0

- **Discuss on `mail.channel`**: nothing to adapt. `wire_kind` reads only `channel_type` (same values; 15 has no
  `group`, which only means that value never occurs there). The new Discuss tests subclass `DiscussCase`, whose `dm()`
  already opens a `mail.channel` on these versions, and they name no Discuss model themselves. `conversation.key`
  keeps the `discuss.channel:<id>` form the port already sends (a contract key, not the model name).
- **Setup view** (§6 item 5): the "Open Access Logs" header button and the step "Review the **Access Logs** if needed."
  added as on 17. The button needs a method 15 and 16 did not have:
  - `models/bridge_setup_wizard.py`: `action_open_access_logs` added as on 17 (`_check_admin()`, then the
    `styd_odoo_bridge.action_styd_bridge_access_log` action, which the port already defines with its menu).
  - `tests/test_rpc_access.py`: the RPC inventory listed that method only `if MAJOR >= 17`. On 15 and 16 it is now in
    `SETUP_ACTIONS` without the condition (otherwise the inventory test fails on an unreviewed public method); the
    guard test then also calls it as an internal and a portal user and expects the refusal.
  - The token note's "never written to the logs" now says "never written to the **access** logs", 17's wording (15 and
    16 have that log now).
- The view keeps `attrs` where 17 has `invisible="…"` (the port's adaptation, untouched).

### 18.0

- Nothing to adapt in the code. The 18 text commit carries `docs/B2_TEXT_17.patch` (the text lane put 17's patch on
  the 18 branch); it came in with the cherry-pick and is staged. It is not part of the module. M5 removes it.

### 19.0 and 20.0

- Nothing to adapt. `bridge_discuss.py` differs from 17's elsewhere (the port's changes); the hunk applied cleanly.

## 3. Tests

Own containers only: `bfp-pg` (`postgres:16-alpine`, on Docker's default bridge, as no address pool was left for a new
network) and one throwaway Odoo per run (`--rm`, in `bfp-pg`'s network namespace), strictly one after the other, so
only one Odoo listens on 8069 at a time. Module trees exported to the session scratchpad: "before" with
`git archive origin/claude/b2-more-<v>`, "after" with `git checkout-index` from the staged index. Command, as in the
port lanes: `odoo -d <db> -i <modules> --test-tags /styd_odoo_bridge --stop-after-init`. "Apps" = styd_odoo_bridge,
project, account, hr_holidays, hr_attendance, hr_timesheet (the 17 lane's set, available on 15 to 20). Images as in
the port lanes. No STYD lab container (`rshb-styd-pg`, `*-styd-pg`), no production, no paid call.

| Version | Image | Tree | styd_odoo_bridge only | with apps |
|---|---|---|---|---|
| 15.0 | `odoo:15.0` | before (`ebe220d`) | **221 / 221**, 0 failed, 0 errors (14 skips) | **221 / 221** (2 skips) |
| | | **after** (staged) | **230 / 230**, 0 failed, 0 errors (14 skips) | **230 / 230** (2 skips) |
| 16.0 | `odoo:16.0-20250909` | before (`c5b08db`) | **221 / 221** (13 skips) | **221 / 221** (1 skip) |
| | | **after** (staged) | **230 / 230**, 0 failed, 0 errors (13 skips) | **230 / 230** (1 skip) |
| 18.0 | `odoo:18.0-20261015` | before (`9cc55a9`) | **221 / 221** (13 skips) | **221 / 221** (1 skip) |
| | | **after** (staged) | **230 / 230**, 0 failed, 0 errors (13 skips) | **230 / 230** (1 skip) |
| 19.0 | `odoo:19.0-20260528` | before (`2a345e4`) | **223 / 223** (12 skips) | **223 / 223** (0 skips) |
| | | **after** (staged) | **232 / 232**, 0 failed, 0 errors (12 skips) | **232 / 232** (0 skips) |
| 20.0 | `odoo:20.0-20261015` | before (`0c14198`) | **225 / 225** (13 skips) | **225 / 225** (1 skip) |
| | | **after** (staged) | **234 / 234**, 0 failed, 0 errors (13 skips) | **234 / 234** (1 skip) |

+9 on every version: `test_contract_more` 5, `test_join_link` 4. All 9 start in every "after" run. The counts differ
between versions as on the port branches (19 and 20 have tests of their own). On each version the skips are the same
tests before and after. Bare, they are the apps that are not installed. With apps: 15 `test_h04` (no
neutralization before Odoo 16) and `test_21_status_page` (19+ only); 16 and 18 `test_21_status_page`; 20
`TestReadGroupShape.test_02` (a skip the port branch already has); 19 none. The module's warnings in the log (only the
ones the tests provoke on purpose) are the same before and after, run by run. `restaurant.table`'s real read needs
`pos_restaurant`, which neither app set installs (as on 17). On 15 and 16 the RPC inventory test now also covers
`action_open_access_logs` (§2).

## 4. What M5 must still do, per version

All versions:

- Bump the version to `<v>.0.0.11.0` in the manifest and the store page footer (STYD's hub minimum is 0.11.0: until
  then every pair and hello gets `426 module_too_old`).
- The audit's clean-up: result notes, STYD paths in comments.
- Commit these staged trees (one commit per branch), then carry them to the release branches.

| Version | Also |
|---|---|
| 15.0 | Optional: carry the `test_rpc_access.py` change (`action_open_access_logs` in `SETUP_ACTIONS` without the condition) to 17 to 20, so the file is byte-identical again on all six (same meaning there: 17+ already lists it). |
| 16.0 | Same as 15.0. |
| 18.0 | Remove `docs/B2_TEXT_17.patch`. |
| 19.0 | Nothing else. |
| 20.0 | Nothing else. |

Not changed (as on 17, not in this lane's list): "behind Cloudflare" (owner lab), "(you can try it on sample data)" in
the setup view.
