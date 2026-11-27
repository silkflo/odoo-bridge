# Discuss assistant: the channel contract (protocol 1, feature `discuss.v1`)

Status: contract for the 0.11.0 release, 2026-11-24. Module side built and tested on Odoo 17.0
(`styd_odoo_bridge`). **The STYD side (hub and colours) implements
everything not marked [M].** [M] marks what the module does.

It extends the Bridge channel protocol version 1 (STYD's protocol
specification, "the protocol" below). Nothing in the protocol changes meaning: the additions are one hello field, two event
kinds, one hub-to-module message type, one optional read argument and a few error codes. The protocol number
stays 1. A hub that does not know them keeps working (it ignores the unknown hello field and answers the
unknown event kinds with `{"t":"ack","ignored":true}`, which the module turns into a polite "not available").

## 1. The flow

```
 Odoo user                 Odoo (module)                                   hub / STYD
 ─────────                 ─────────────                                   ──────────
 DM to the bot,     ──▶  hook on discuss.channel: checks (enabled,
 or @mention              who may ask, rate limits), saves a pending
 in a channel             question, triggers the Discuss job.
                          Nothing leaves Odoo in the user's request.
                                       │ (ir.cron trigger, seconds)
                          the job ─────┼── POST /bridge/v1/event  discuss.ask ──▶  ack {accepted:true}
                          posts "Looking it up…" (user's language)               │
                                                                                  │ STYD answers the question as
                          poll threads ◀── request envelopes (reads) ─────────────│ the member: ordinary signed
                          (read-only cursor, member's own rights) ── results ──▶ │ requests, args carry
                                                                                  │ discuss_question_id
                          poll thread ◀── signed discuss_answer ─────────────────┘
                          stores it (inbox), triggers the job,
                          POST /bridge/v1/event discuss.delivered ──────────────▶
                          the job posts the answer as the bot
```

- The module never receives an inbound call. Every byte goes out over the existing outbound channel:
  questions as signed events (protocol §4.2, §6.4), answers down the existing polls (protocol §6.2), signed
  like requests (protocol §4.1).
- Odoo's HTTP workers never wait on STYD: the question is saved and the job triggered (an
  `ir_cron_trigger` row, which cron runners are notified of); the job does the HTTP, and the job never waits
  for the answer either.
- One STYD thread per Discuss conversation (`conversation.key`), so follow-ups keep their context.
- **Where the bot answers** (owner decision, 2026-11-24). A question asked in the user's own chat with the
  bot is answered there. A mention anywhere else (a channel, a group, a chat with a colleague) is answered
  by default in the **asker's direct chat with the bot** (opened if needed), and once that reply is posted
  the bot adds one line where the question was asked, as a reply to it: "I've answered you in a direct
  message." The admin setting **"Answer mentions in the channel"** (off by default) answers in the channel
  instead (§6).

## 2. Hello: the feature flag

[M] The module adds one field to the protocol's `hello` (§6.1):

```json
{"t":"hello", …, "ops":[…unchanged…], "features":["discuss.v1"]}
```

- `features` is additive. A hello without it (an older module) means: no Discuss. STYD must not show the
  assistant as available for that pairing, and never sends a `discuss_answer` to it.
- `ops` is unchanged: Discuss adds **no** read op. Every read STYD makes to answer a Discuss question is an
  ordinary `orm.*` / `health` request of §7.
- STYD should expose the flag in `GET /internal/v1/status` (for example `features: ["discuss.v1"]`).

## 3. `discuss.ask` (module → hub, `POST /bridge/v1/event`, signed upstream)

```json
{
  "t": "event",
  "kind": "discuss.ask",
  "question_id": "dq_3q2-k1Vb0aYlZx8w7HfC0Q",
  "member_uid": 7,
  "conversation": {"key": "discuss.channel:42", "kind": "chat", "shared": false, "asked_in": "channel"},
  "lang": "fr_FR",
  "tz": "Europe/Paris",
  "text": "Quelles sont les ventes de mars ?",
  "truncated": false,
  "asked_at": 1795435200000,
  "attempt": 1
}
```

| Field | Type | Meaning |
|---|---|---|
| `question_id` | `dq_` + 22 base64url chars (16 random bytes) | Made by the module. **The idempotency key**: the module may send the same question again (a retry after a network error, a crash before its commit). STYD must treat a second `discuss.ask` with a known `question_id` as the same question: same ack, no second answer, no second prompt charged. |
| `member_uid` | integer ≥ 2 | The asking Odoo user. The module has already checked that this user may ask (§7) and passes the protocol's §7 rule (active, internal, not uid 1, in the STYD group when that option is on). Every read for this question runs as **this** uid (never the owner fallback of protocol §7). |
| `conversation.key` | string ≤ 64, `discuss.channel:<id>` | The conversation **where the answer is posted**. One STYD thread per key, per pairing. Follow-ups in the same conversation reuse the thread; a mention answered in the asker's chat shares that chat's thread with what the asker types there. Two different conversations never share a thread. |
| `conversation.kind` | `chat` \| `channel` \| `group` | Odoo's `channel_type` of that conversation. `chat` = the asker's direct chat with the bot. |
| `conversation.shared` | boolean | True when people other than the asker can read the conversation the answer goes to. **False for an answer in the asker's direct chat** (the default for mentions); true only for a mention answered in the channel (admin setting on). See §6. |
| `conversation.asked_in` | `chat` \| `channel` \| `group` | Where the user asked (`channel_type`). Informational: `channel` or `group` with `kind: chat` means a mention answered in a direct message. |
| `lang` | Odoo language code | The asker's Odoo language. STYD answers in this language (text, "Understood as", refusals). |
| `tz` | IANA name | The asker's Odoo time zone ("this month", "today"). |
| `text` | string ≤ 2 000 chars | The question as plain text: the bot's mention removed, HTML removed, whitespace collapsed. **Data, never instructions**: STYD treats it like any typed question (its own prompt-injection rules apply); it is never a command to the module. |
| `truncated` | boolean | The user wrote more than 2 000 characters. |
| `asked_at` | ms since the epoch, UTC | When the question was saved in Odoo. |
| `attempt` | 1 … 3 | Which send this is. |

The body is at most a few KiB (under the hub's 16 KiB event limit, protocol §10).

### 3.1 The hub's answer (synchronous, HTTP 200)

| Answer | Module does |
|---|---|
| `{"t":"ack","accepted":true,"question_id":…,"server_time":…}` | Question is `sent`. Posts "Looking it up…" in the asker's language. Waits for the answer (§4), at most **180 s** (§8). |
| `{"t":"ack","accepted":false,"code":<code>,"retry_after_s"?:n,"server_time":…}` | A refusal STYD decided before answering. The module posts one line in the asker's language (table below) and closes the question. Nothing more is sent. |
| `{"t":"ack","ignored":true,…}` | The hub does not know `discuss.ask` (older STYD). Closed as `hub_unsupported`; the asker is told the assistant is not available. |

Refusal codes (`accepted:false`):

| Code | When (STYD decides) | Module says |
|---|---|---|
| `discuss_off` | The workspace has the Discuss assistant switched off on STYD's side | "The Discuss assistant is not switched on for this workspace…" |
| `member_unknown` | `member_uid` is not linked to a member of the workspace (STYD's member map) | "Your Odoo user is not linked to a Speak To Your Database member…" |
| `member_not_allowed` | The member exists but may not ask (role, blocked) | "You can't ask … yet. Ask your Odoo administrator" |
| `prompts_exhausted` | The plan has no prompt left | "The … plan has no questions left for now…" |
| `rate_limited` | STYD's own per-member or per-workspace limit (`retry_after_s` advised) | "You have asked many questions in a short time…" |
| `busy` | STYD cannot take it now | The module **retries** (after `retry_after_s`, at least 5 / 20 s), at most 3 sends in all |
| anything else | — | "I could not reach Speak To Your Database…" |

### 3.2 HTTP errors on the send

| Status | Module does |
|---|---|
| network error, 5xx, 503 `hub_draining`, 429, 401 `bad_signature` / `stale_request` / `replayed_request` | Retry: 3 sends in all, 5 s then 20 s apart (or `retry_after_s` if longer, capped at 10 min). Then the asker is told STYD could not be reached. |
| 401 `not_paired` | Closed; "This Odoo is not connected…" |
| 400 `bad_message`, 413 `too_large` | Closed; generic error line. |

## 4. `discuss_answer` (hub → module, down a poll)

A new message type, in the protocol's signed envelope (§4.1), verified exactly like a request (shape, pairing,
signature, timestamp window, replay cache, §4.3):

```json
{"t":"discuss_answer","v":1,"id":"<uuid v4>","ts":1795435212000,"op":"discuss.answer","member_uid":7,
 "pairing_id":"bp_…","args_json":"{…}","sig":"…"}
```

- `t` and `op` must agree: `discuss_answer` ⇔ `discuss.answer`. `member_uid` is the **asker** (≥ 1), the same
  uid as in the question's `discuss.ask`. A `request` carrying `op` `discuss.answer`, or a `discuss_answer`
  with another op or `member_uid` 0, is dropped as `bad_message` (no result is posted for it).
- STYD sends it **once per question**, after it finished answering (no streaming, no partial answers).
- It carries no channel, no record, no model: the module posts it **only** in the conversation the question
  came from, and only as the bot. Any other field is ignored.

`args_json` (UTF-8 JSON object):

```json
{
  "question_id": "dq_3q2-k1Vb0aYlZx8w7HfC0Q",
  "status": "answered",
  "lang": "fr_FR",
  "understood_as": "ventes confirmées, mars 2026, toutes sociétés",
  "text": "Les ventes confirmées de mars 2026 sont de 12 400 €.\n\nC'est 8 % de plus qu'en février.",
  "tables": [
    {"title": "Ventes par client", "columns": ["Client", "Montant"],
     "rows": [["Acme SA", "7 200 €"], ["Beta", "5 200 €"]], "total_rows": 2}
  ],
  "thread_id": "th_…"
}
```

| Field | Type, limit | Meaning |
|---|---|---|
| `question_id` | as in §3 | Required. |
| `status` | `answered` \| `refused` \| `error` | Required. `answered` needs `text` or at least one table. |
| `lang` | Odoo language code, optional | The language STYD answered in (used for the module's own labels: "Understood as", "Showing x of y rows"). Absent: the asker's language. |
| `understood_as` | string ≤ 500, optional | The interpretation line, **without** its label (the module adds "Understood as:" in `lang`). |
| `text` | string ≤ 8 000 | Plain text. Blank lines separate paragraphs; a single newline is a line break. **No HTML, no Markdown**: everything is shown as text. |
| `tables` | ≤ 5 tables | Each `{title?: string ≤ 200, columns: [string] (1 … 20), rows: [[cell]] (≤ 200), total_rows?: int}`. A cell is a string (≤ 500), number, boolean or null. Send amounts already formatted (with currency) as strings; numbers are shown as given, right-aligned. `total_rows` > the rows sent makes the module add "Showing x of y rows". |
| `refusal` | `{code: [a-z_]{1,64}, message: string ≤ 1 000}` | With `status: refused`: STYD's refusal **in the asker's language** (for example HR not readable, a model not allowed, the member's own Odoo rights). Without `message`, the module says a generic "cannot answer". |
| `error` | `{code, message?}` | With `status: error`: STYD failed (timeout, channel lost …). Without `message`, the module says a generic error line. |
| `thread_id` | string ≤ 64, optional | STYD's thread, for STYD's own logs. Not shown. |

Longer values are cut at the limits, extra tables, columns and rows are dropped (the module never refuses an
answer for its size). A structurally wrong answer (no valid `question_id`, unknown `status`, `answered` with
nothing, wrong types) is `bad_answer`.

### 4.1 Rendering, in the module [M]

- Everything from STYD is **escaped**. The only markup in the posted message is the module's own: `<p>`,
  `<br/>`, one `<table class="table table-sm table-bordered">` per table, `<strong>` for a table title, `<em>`
  for "Understood as" and the row count. A record value such as `<a href=…>` or `@everyone` is shown as text
  and notifies nobody (no partner is passed to `message_post`).
- **No secret is ever posted.** Before posting, the module hides (as `[hidden]`): every channel secret it
  holds (current, pending, previous), anything shaped like a channel secret (43 base64url characters), bearer
  tokens, JWTs, common API key shapes (`sk-…`, `ghp_…`, `xox?-…`, `AKIA…`), PEM private keys, and the value
  after `password` / `secret` / `token` / `api key` labels. STYD must still never put a secret in an answer:
  this is defence in depth.
- Order in the conversation: "Looking it up…" first (after the ack), then the answer.

### 4.1b Askers not linked yet: the join link

An Odoo user who is not linked to a STYD member yet gets no answer. STYD sends a `refused` answer whose
`refusal.code` is one of:

| `refusal.code` | Sent when | What the module shows |
|---|---|---|
| `join_required` | a conversation only the asker reads | `refusal.message` as text: the personal join link is on a line of its own |
| `ask_in_direct_message` | a conversation others read | `refusal.message` as text (no link) |
| `join_limit` | too many links asked for in an hour | `refusal.message` as text |

- The link goes through the same filters as every answer: it is shown as plain text, scheme dropped and the
  host's dots bracketed (`app[.]example[.]com/join/odoo?t=…`). The token is never hidden: none of its parts
  has a secret's shape (§4.1).
- A `join_required` answer may carry a top-level `action` (`{type: "open_url", label, url}`, a button).
  This version ignores it: `action` is not read, stored, logged or shown. The text line keeps the link.
- Nothing is read in Odoo for such a question, and nothing else changes on the module's side.

### 4.2 `discuss.delivered` (module → hub, `POST /bridge/v1/event`)

[M] After each verified `discuss_answer`, the module reports what became of it:

```json
{"t":"event","kind":"discuss.delivered","id":"<the discuss_answer's id>","question_id":"dq_…","ok":true,"code":"ok"}
```

| `code` | Meaning |
|---|---|
| `ok` | Stored; the job posts it within seconds. |
| `bad_answer` | Malformed. If its `question_id` was valid the asker gets a generic error line, and the question is closed. |
| `unknown_question` | No such question for this pairing. |
| `wrong_member` | `member_uid` is not the asker. Not posted. |
| `late` | The question is closed already (answered, timed out, failed). Not posted. |
| `duplicate` | An answer for this question is already waiting. Not posted again. |
| `discuss_unavailable`, `module_error` | The module could not store it. |

The hub only logs it (`discuss_delivered` with ids and the code, never the content). A `discuss_answer` that
fails the envelope checks (§4.3 of the protocol) gets no `discuss.delivered`.

## 5. Reads made for a Discuss question

STYD answers a Discuss question with the ordinary read ops (§7 of the protocol), as the asker
(`member_uid` = the question's `member_uid`), through the same validators, read-only cursor and the
member's own Odoo rights. Each such request adds one argument:

```json
"args_json": "{\"model\":\"hr.leave\",…,\"discuss_question_id\":\"dq_3q2-k1Vb0aYlZx8w7HfC0Q\"}"
```

[M] The module checks it before running the read:

| Check | Refusal |
|---|---|
| the question exists, belongs to this pairing, is still open (waiting to be sent, or sent and not answered), and `member_uid` is its asker | `ok:false`, `error.code` = `discuss_question_unknown` (new, protocol §9.1: a bug or a replay; never retry) |
| the conversation is **shared** (§6) and the model is an HR model (`hr.employee.public`, `hr.department`, `hr.leave*`, `hr.work.entry.type`, `hr.attendance`, `resource.calendar.leaves`) | `ok:true`, status 400, `{"ok":false,"error":"model_not_allowed","detail":"HR is answered only in a direct message with the assistant."}` |

Reads without `discuss_question_id` are unchanged (older modules ignore the argument, as routes ignore
unknown keys). STYD **must** tag every read it makes for a Discuss question, and must not reuse cached read
results across members.

## 6. Shared conversations

The reads run with the asker's rights, so an answer must not land where others read it unless the admin
chose so.

- **Default** [M]: a mention outside the asker's own chat with the bot is answered in that chat
  (`kind: chat`, `shared: false`, `asked_in: channel|group|chat`). HR is answered normally there. When the
  reply is posted (answer, refusal, error, timeout, or "could not reach"), the bot posts once, in the
  conversation where it was asked, as a reply to the question: "I've answered you in a direct message" (in
  the asker's language). Nothing else from the answer appears there.
- **Admin setting "Answer mentions in the channel" on** [M]: the answer is posted where it was asked,
  readable by everyone there. The question is `shared: true` and the module refuses HR reads for it (§5).
  STYD should then refuse in words anything else the asker can read but the room should not, and suggest
  asking in a direct message.
- The free lines of §7 (switched off, not allowed, not connected, empty mention, rate limited) say nothing
  private: they are posted where the user asked, as a reply to the question.

## 7. Module-side rules before anything is sent [M]

All answered by the bot in the asker's language, **free** (no call to STYD, no prompt):

| Case | Line |
|---|---|
| The assistant is switched off (the default) | "The … assistant is switched off in this Odoo. Ask your Odoo administrator." |
| The user may not ask: not in the admin's audience (all internal users / a group / chosen users), portal or public, `__system__`, or outside the STYD group when "Only members of the STYD group" is on | "You can't ask Speak To Your Database in Odoo yet. Please ask your Odoo administrator for access." |
| No usable pairing (Bridge off, not paired, pairing waiting for an administrator's approval (§11), several workspaces and none chosen) | "This Odoo is not connected to Speak To Your Database right now…" |
| Only a mention, no question | A one-line example question |
| Rate limits: 3 per user per minute, 30 per user per hour, 300 per database per hour (the hourly ones set by the admin) | "You have asked many questions…" / "This Odoo has reached its limit…" |

Ignored entirely (no question, no line): the bot's own posts, notifications, emails, messages by other bots,
messages on records' chatter (only `discuss.channel` is watched), a message in a channel that does not
mention the bot.

**The bot cannot be made to write.** The only things the assistant writes are: its question row, its inbox
row, and the bot's own messages, in the conversation the question came from. The question text is sent as a
JSON string and never interpreted. The answer is rendered by the module from a fixed shape. Reads go through
the channel's read-only cursor (PostgreSQL refuses any write, pgcode 25006) and the closed op list (no write
op exists).

**The welcome line** [M]. Saving the settings with the assistant on opens the chat with the bot for each
allowed user who was never welcomed, with one welcome line. A user is welcomed **once ever** (recorded in
`styd.discuss.welcome`): later saves never post it again, even if the user left that chat, and nothing is
opened or posted while the assistant is off. A user whose first contact is a mention gets the welcome line
in the chat that opens for the answer.

## 8. Timeouts and limits

| What | Value |
|---|---|
| Question text | ≤ 2 000 characters (longer: cut, `truncated: true`) |
| Sends per question | 3 (5 s, then 20 s apart, or `retry_after_s`) |
| Wait for the answer after the ack | **180 s**, then "did not answer in time"; a later `discuss_answer` is `late` |
| STYD's own answer budget | should stay under 150 s, so the answer always beats the module's timeout |
| Answer limits | §4 table |
| Question rows kept | 30 days (text removed as soon as the question is sent or closed), answers removed once posted |

## 9. Error codes added to the protocol

| Code | Where | Meaning |
|---|---|---|
| `discuss_question_unknown` | result `ok:false` (module) | §5 |
| `discuss_off`, `member_unknown`, `prompts_exhausted` (and the existing `member_not_allowed`, `rate_limited`, `busy`) | `discuss.ask` ack `accepted:false` (hub) | §3.1 |
| `bad_answer`, `unknown_question`, `wrong_member`, `late`, `duplicate`, `discuss_unavailable` | `discuss.delivered` (module) | §4.2 |

## 10. What the STYD side builds (for the S-step)

1. Hub: accept `discuss.ask` events (signed, §3), check the pairing's hello has `discuss.v1`, dedupe by
   `question_id`, hand the question to a colour (a queue, so a colour restart does not lose it), answer the
   ack synchronously (§3.1).
2. Colour: map `member_uid` to the member, check the workspace switch and the plan, find or create the thread
   for `(pairing_id, conversation.key)`, run the question through the normal question path with the channel
   transport, `memberOdooUserId` = `member_uid`, every read tagged with `discuss_question_id` (§5), answer in
   `lang` / `tz`.
3. Hub: send the `discuss_answer` envelope (§4) down the pairing's polls; log `discuss.delivered`.
4. Logs: ids, codes and timings only; never the question, the answer or table values.
5. A loopback test route or script that plays STYD against a real module (the module's own fake hub in
   `styd_odoo_bridge/tests/fake_hub.py` follows this contract and can serve as the reference).

## 11. Pairing approval, and copies of the database [M]

**Approval.** Typing the code in STYD does not open the connection by itself. Once the hub has sent `paired`
and the module has acknowledged it (proof of possession), the module keeps the pairing **waiting for an
administrator's approval**:

- Every Odoo administrator (Settings) gets one line from the assistant: the STYD workspace's name and id, the
  e-mail domain of the person who typed the code, and where to decide (Speak To Your Database > Connect
  without opening a port).
- Until an administrator clicks **Approve** there, every request is answered
  `{"t":"result","ok":false,"error":{"code":"pairing_not_approved"}}`, and the assistant uses no such pairing:
  no question is sent, and a `discuss_answer` for it is not posted (`discuss.delivered` code
  `pairing_not_approved`).
- **Refuse** unpairs it, like **Unpair** (the signed unpair event, then every secret is cleared).
- STYD reads `pairing_not_approved` as "waiting for the Odoo administrator": never as a failed connection
  or a refused key. Reads work as soon as the pairing is approved; nothing else changes.

**Copies of the database.** A pairing belongs to the database that showed the code: the module records its
`database.uuid` and `database.create_date`. A copy made with Odoo's own tools (Duplicate, or a restore
marked as a copy) gets a new uuid and creation date, so its pairings never connect: the wizard says "This
database is a copy of the paired one", and the executor answers `not_paired`. On Odoo 16 and later,
neutralizing a database also unpairs every pairing and clears its secrets.

**Unpair before copying a database.** A copy made any other way (`pg_dump` and restore, a disk or virtual
machine snapshot, a database restored "as moved") keeps the uuid and the creation date, so neither the module
nor STYD can tell it from the original: both would connect as the same pairing. Before making such a copy,
unpair the database in Speak To Your Database > Connect without opening a port, make the copy, then show a
new code in the original and pair it again (and approve it). Pair the copy only if it should answer STYD on
its own, with its own code.
