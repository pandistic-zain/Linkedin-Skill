# Activity logging

Every skill that reaches a decision (approve/reject a draft, publish, edit,
abandon) should log it via `lib.start_run` / `lib.finish_run`, so the
dashboard's Skills and Activity screens have real data. Both are safe to call
unconditionally: with `DASHBOARD_EVENTS_URL` / `EVENTS_INGEST_SECRET` unset
(the common case for anyone not running the dashboard), they no-op silently
and never block or slow down the skill.

## Pattern

At the top of the skill's Steps, before gathering inputs:

```python
run_id = lib.start_run("<skill-name>", input_summary="<topic or target in one line>")
```

At the point a decision is made, before ending the conversation:

```python
lib.finish_run(run_id, "<skill-name>", "completed",
                decision="<what was chosen, e.g. a formula code or approach>",
                outcome="<approved | rejected | edited | published | abandoned>")
```

If the skill hits an unrecoverable error (a vendor call fails and there is no
fallback), log it instead of a decision:

```python
lib.finish_run(run_id, "<skill-name>", "failed", error_text="<what broke>")
```

## Outcome vocabulary

- `approved` — the user kept the draft as shown, no edits.
- `edited` — the user asked for changes before accepting it.
- `rejected` — the user declined the draft outright.
- `published` — a publish/schedule call was actually made (`lib.publish`,
  `lib.repost`, etc.), distinct from `approved` because a draft can be
  approved and then not published if the user cancels.
- `abandoned` — the conversation ended with no decision. Skills usually can't
  detect this themselves (no explicit signal); leave it to the dashboard's
  "no outcome recorded" state rather than guessing.

`decision` is free text: the formula code used (`F7`), the approach picked,
or a `NO_TRADE`-style stand-aside note when the skill declined to produce
anything (e.g. no post-worthy angle found). Keep it short — it is a label,
not the transcript.

For skills with no meaningful decision (pure lookups, analytics, monitoring),
just call `start_run` / `finish_run` with `status="completed"` and no
`decision`/`outcome` — the Skills screen still gets run counts and durations,
and reports "no outcome recorded" for approval rate rather than a fake 0%.
