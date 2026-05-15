# AI Act art. 14 — Human Oversight

The system is designed so that **a qualified lawyer remains the
decision-maker for every output that leaves the firm**. The platform
mediates research and drafting; it does not act on behalf of the lawyer
without the lawyer's review.

## Built-in oversight controls

1. **No autonomous filing**. The system never submits documents to
   courts, sends emails to clients, or transmits data to external
   parties without an explicit, per-action confirmation by the
   lawyer.
2. **Drafts are marked as drafts**. The .docx export
   (`pro_features.py::brief_docx` and friends) carries a header
   reading "DRAFT — do not file unread". Lawyers must remove it
   manually.
3. **Citation Shield refusal** (V8.11). Below a 50% confidence
   threshold the system refuses to answer. The lawyer can still ask
   the system to retrieve and present articles, but the model is
   blocked from composing strategic recommendations on weak ground.
4. **Adversarial loop** (V7.12). Strategic recommendations are
   stress-tested by a "red-team" stage that lists how the
   counter-party could attack the proposed strategy. The lawyer sees
   both sides.
5. **Calendar overrides**. AI-suggested deadlines (V7.10) are saved
   as suggestions; they only convert to firm-confirmed dates when a
   lawyer accepts them.
6. **Capacity dashboard** (V8.1). Workload signals are
   recommendations — assignment changes are made by the firm admin,
   not by the system.

## What the lawyer can override

- Mark any cited article as "not applicable" → it is excluded from
  future answers in the same case.
- Reject any AI suggestion (deadline, redline, contract clause) →
  the rejection is logged in `feedback`.
- Force the system to retry a question with a different model tier.
- Disable the system entirely on a per-case basis (set
  `case.ai_disabled = 1`) — useful for matters where the firm has
  contracted to provide human-only counsel.

## Stop button

There is no autonomous loop running in the background. Every LLM
call is initiated by a user action (chat send, dossier upload,
"generate brief" button). Closing the browser tab stops the system.

For long-running streams, the SSE endpoint terminates when the
client disconnects (`/api/ask/stream`). No outstanding calls
persist.

## Training data

The system does not train on user data. The foundation models
(Anthropic Claude) are used in inference mode only; we do not send
batches of user data back to the provider for fine-tuning. The
provider's data-handling commitments (Anthropic enterprise terms,
zero-data-retention with API key) are documented per-deployment and
audited annually.
