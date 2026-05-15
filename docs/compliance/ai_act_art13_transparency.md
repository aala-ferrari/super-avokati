# AI Act art. 13 — Transparency to End Users

## Disclosure on first use

A new user sees a dialog explaining that:

1. The system is an **AI assistant** (not a lawyer), running on
   Anthropic Claude foundation models.
2. The system retrieves from a **fixed knowledge base** of Albanian
   legal codes; the KB version hash is shown in the footer.
3. Outputs are **decision-support, not advice** — the qualified
   lawyer using the system is responsible for verifying and signing
   any output before it reaches a client or a court.
4. **Citations** are post-verified against the KB; an in-line badge
   shows whether the cited article exists. If confidence is below
   50%, the system refuses with the disclaimer in
   `src/citation_shield.py::REFUSAL_PREAMBLE_AL`.

## Per-answer transparency (provenance pack)

Every assistant answer is paired with a provenance pack
(`/api/provenance/<id>.json` + `.docx`) carrying:

- response id + UTC timestamp
- jurisdiction tag (V8.13+)
- KB hash, model, tier, prompt hash, response hash
- list of citations + their verification status
- list of retrieved articles + their similarity scores
- refusal flag + reason (if applicable)

This is what an external auditor or unhappy client can ask the lawyer
for: a verifiable record of "what the AI said, on what data, with
what model".

## Per-firm transparency (audit log)

The firm administrator sees the full call history (model used,
latency, outcome, callsite). This satisfies the deployer-side
disclosure obligation in art. 26.

## Limits we proactively communicate

- The system does **not** know about case law beyond what is in the
  shipped KB. It will not hallucinate court decisions; if asked, it
  refuses or says it does not know.
- The system does **not** know about laws enacted after the KB
  version cutoff, which is shown to the user.
- The system does **not** access the internet at run time. Every
  answer is retrieved + reasoned over the local KB.
- The system does **not** store legal advice as authoritative — every
  output is marked "to be reviewed by qualified counsel".
