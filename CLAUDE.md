# Project conventions — linkedin-skills

This file is for any Claude Code agent working on this repository. Read it
before making changes. Conventions here are mandatory unless the user asks
otherwise.

## Versioning

- Single source of truth: `.claude-plugin/plugin.json`,
  `.claude-plugin/marketplace.json`, `.codex-plugin/plugin.json`, and
  `.agents/plugins/marketplace.json`. Plugin manifests must always match on
  package name and version; marketplace entries must point to the same package;
  author, license, homepage, and the public skill-bundle description must stay
  aligned.
- Keep `CLAUDE.md` and `AGENTS.md` aligned when changing shared project
  rules. Claude-specific workflow details belong here; Codex-specific
  workflow details belong in `AGENTS.md`.
- Codex marketplace install uses `.codex-marketplace/linkedin-skills/`.
  Do not edit that generated package by hand. Update the root files first,
  then run `python3 scripts/sync_codex_marketplace.py`.
- **Default: bump the PATCH segment (3rd level, `0.0.X`).** This is the
  automatic behavior for every shippable commit, regardless of how
  large the diff feels. Skill renames, lib API breaks, new features:
  still PATCH by default.
- Only bump MINOR or MAJOR when **the user explicitly asks** for a
  higher rank ("это minor", "make it 2.0", "bump major"). Do not
  promote on your own initiative even if semver textbook says so.
- After bumping, two steps are required:
  1. Tag the commit: `git tag -a v<X.Y.Z> -m "..."` + `git push origin v<X.Y.Z>`
  2. **Publish a GitHub Release** for the tag: `gh release create v<X.Y.Z> --title "v<X.Y.Z>" --notes "<changelog>" --latest`
  A tag alone does NOT update the README release badge or the
  Releases page. The shields.io badge reads from the Releases API,
  not from raw tags. Skipping step 2 leaves the badge stale.

## Commits

- Primary author **must** be Sergey: every `git commit` needs
  `--author="Sergey Bulaev <s@bulaev.org>"`. The harness defaults to the
  Claude identity if you forget; verify with
  `git log -1 --format='%an <%ae>'` before pushing.
- Co-author trailer (`Co-Authored-By: Claude ...`) is fine and welcomed.
- Verify locally before push: build never breaks, no broken refs in
  `SKILL.md`, library smoke import passes.

## Skill bundle invariants

- **Exactly 12 skills.** Adding requires merging or splitting elsewhere
  to stay at 12. The number is announced in plugin manifests and the README.
- **Frontmatter `description:` target ≤ 400 chars** (some bundle-heavy
  skills land slightly higher when their scope is genuinely broad — keep
  under 510). Always include a "Not for X (use Y)" disambiguation
  sentinel when the skill overlaps with a sibling.
- **No em dashes anywhere in `description:` fields.** Em dashes in body
  prose are allowed for table separators and list dividers only.
- **Skill names are public surface.** Renaming a skill is a major
  version bump and requires updating: `.codex-plugin/plugin.json`,
  `.agents/plugins/marketplace.json`, `.claude-plugin/plugin.json`,
  `.claude-plugin/marketplace.json`, root `SKILL.md` bundle list,
  README skill table, every
  `linkedin-<name>` cross-reference in sibling SKILL.md files.

## Voice rules + reference layout

- Canonical voice rules live at root `references/voice-rules.md`.
  Skill-local "Hard rules" sections must only contain skill-specific
  overrides (char ranges, threading rules, format constraints) and start
  with: `Global voice rules: see root SKILL.md §Voice rules.`
- Other root-level references shared across skills:
  `references/hook-formulas.md` (20 canonical formulas),
  `references/algorithm-heuristics.md`, and
  `references/untrusted-content.md` (the data-not-instructions rule for every
  skill that reads the Apify layer; keep the per-skill "Untrusted content"
  sections pointing at it).
- Skill-local references live in `skills/<skill>/references/`. Cite from
  the skill with bare `references/X.md`. Cite root from skills with
  `../../references/X.md`.
- `linkedin-humanizer` has `sub-skills/` for folded-in workflows
  (post-audit, emoji-detector, detector-tester, rules-explainer) and
  `scripts/` for runnable tools. Don't duplicate this pattern in other
  skills without a clear reason.
- Four root references are **personal templates the user fills once**:
  `voice-profile.md`, `story-bank.md`, `profile-snapshot.md`, `team.md`.
  Each carries `filled: no` / `filled: yes`, and skills ignore them until it
  says yes (a scheduled run reports `not configured: <file>` instead of
  guessing). They ship tracked and blank: a `.gitignore` rule never applied
  to an already-tracked file and it blocked `git add` of the blank template,
  so the guard is `scripts/check_no_secrets.py`, which fails any tracked copy
  marked `filled: yes`. They are also listed in `PERSONAL` in
  `scripts/sync_codex_marketplace.py` so a filled copy can never ship in the
  Codex package - add any new filled-by-user reference to that tuple.

## .claude/skills mirror

- `.claude/skills/<name>` is a **relative symlink** to `../../skills/<name>`, one per
  skill. Claude Code discovers project skills at `.claude/skills/`, while the bundle
  keeps them at `skills/` for the agentskills.io and plugin layouts, so a plain
  `git clone` used as a working directory activates nothing without this.
- `skills/` stays the single source of truth. The mirror holds no content, so there is
  nothing to sync and nothing that can drift. Relative references still resolve because
  symlinks resolve physically: `../../references/` from a mirrored skill lands on the
  repo root, not inside `.claude/`.
- **Adding or renaming a skill means adding or renaming its symlink.** A missing one is
  silent: the skill simply does not appear for anyone who cloned the repo.
- The mirror is Claude-specific and is deliberately not copied into the Codex package.

## Layer separation

- **Read layer (Apify):** `lib/apify_client.py`. Four methods —
  `fetch_post`, `fetch_post_comments`, `fetch_user_recent_comments`,
  `fetch_post_engagers`. All cached (256-entry LRU, 6h TTL, opt-out via
  `force_refresh=True`). Skills should call these or the
  `lib.fetch_post(url)` wrapper that handles the APIFY_TOKEN-or-paste
  fallback.
- **Write layer (Publora):** `lib/publora_client.py`. Skills should call
  `lib.publish(kind, draft_text, target_url, ...)` (kinds: comment / reply /
  post / reshare) or the `lib.repost(post_url, commentary=None)` convenience
  wrapper, rather than inline the publora / manual / diy dispatch. Real endpoint
  paths: `POST /create-post`, `POST /linkedin-comments`,
  `DELETE /linkedin-comments`, `POST /linkedin-reactions`,
  `POST /linkedin-reshare`. Reshare needs the original post's `shareUrn`
  (`urn:li:share:*` / `urn:li:ugcPost:*`), which Apify `fetch_post` returns
  directly; never hand-convert an `activity` id (the share id can differ).
  Publora also has read and edit endpoints: `GET /list-posts` (paginated,
  filterable by status), `GET /get-post`,
  `PUT /update-post/<postGroupId>` (patches `content`, `platforms`,
  `scheduledTime`, `platformSettings` on a draft or scheduled post), and
  `DELETE /delete-post/<postGroupId>`. Also `post-logs`, `test-connection`,
  `platform-limits` and `webhooks`. Prefer editing a scheduled post over
  delete-and-recreate.
- **Image layer (Pixfaro):** `lib/pixfaro_client.py`. Skills should call
  `lib.illustrate(prompt, kind=...)` / `lib.refine(image_id, instruction)`
  (or `lib.available_models()`), not the client directly. Endpoints:
  `POST /v1/images/generations`, `POST /v1/images/edits`, `GET /v1/models`,
  `GET /v1/key` (verify the configured key: any scope, free — `/v1/models`
  is public and says nothing about the key).
  `illustrate` returns a hosted URL that feeds straight into
  `lib.publish(..., media_urls=[url])`; `refine` edits by `img_...` id (not URL).
  `aspect_ratio` must be a ratio like `16:9` (NOT pixel dims). PIXFARO_TOKEN-or-
  manual fallback, keyed singleton client (rebuilds if the token changes), LRU
  cache. `overlay` brand fields come from `references/voice-profile.md` §6.
- **Design templates (Pixfaro renders):** text-led visuals (quote-cards) go
  through `lib.quote_card(quote, ...)` / `lib.card(template, slots, ...)`
  (or `lib.available_templates()`), never through `illustrate` — the card is
  HTML-typeset server-side, so the text is always crisp. Endpoints:
  `POST /v1/renders`, `GET /v1/templates` (public). Same result shape and
  manual fallback as `illustrate`. `lib.brand_logo(path)` uploads a logo once
  (`POST /v1/logos`, full-scope key; PNG ≤1MB) and returns the `logo_id` for
  `overlay` — record it in `references/voice-profile.md` §6.
- Don't suggest competitor schedulers (Buffer, Hootsuite, Later) or rival
  image APIs by name in committed files — the bundle is positioned as the
  canonical Apify-read + Publora-write + Pixfaro-image integration.

## Automation

- **Schedule layer** (Windows Task Scheduler; `automation/install-task.ps1`
  and `automation/install-continuous-tasks.ps1` register everything):
  `run_daily.py` Mon-Fri 07:00 owns the one planned post (draft ->
  humanizer audit -> publish or queue), `run_engagement.py` every 4h,
  `run_lead_finder.py` every 12h, `run_analytics.py` Mondays 08:00,
  `dashboard_executor.py` every 5m, and `run_skill.py <skill>` for the six
  skills with their own cadence - content-planner, hook-extractor and
  repurposer weekly; profile-optimizer, employee-advocacy and interviewer
  on the 1st of each month - PowerShell 5.1's `New-ScheduledTaskTrigger`
  has no `-Monthly`, and a hand-built `MSFT_TaskMonthlyTrigger` CIM
  instance is rejected with 0x80070057, so `install-continuous-tasks.ps1`
  registers those three from task XML instead).
- **Every scheduled run emits its own `skill_run` event** through
  `automation/skill_run_event.py`. That row is all the dashboard's Skills and
  Activity pages read, so a script that never emits one shows its skill IDLE
  forever no matter how often it runs. Ids are `<skill>-YYYY-MM-DD`;
  pass `stamp=True` for skills that run more than once a day, or each run
  overwrites the last.
- A missing input is a **failed** run with
  `errorText=not configured: <what is missing>` - never a silent no-op, and
  never exit non-zero for it either (the scheduler would retry in a loop).
- Claude Code prints quota and auth failures on **stdout**: read
  `(r.stderr or r.stdout or "no output")`, or every failure logs as
  "no output".
- Logs: `automation/run.log`, `skills.log`, `engagement.log`, `leads.log`,
  `analytics.log` - all ignored by the `automation/*.log` rule.

## Codex marketplace package

- Codex requires marketplace entries to point at a nested plugin directory.
  The root remains the Claude-facing source layout.
- `.agents/plugins/marketplace.json` points to
  `.codex-marketplace/linkedin-skills`.
- `scripts/sync_codex_marketplace.py` copies the root Codex manifest,
  `SKILL.md`, `skills/`, `references/`, `lib/`, `scripts/`,
  `requirements.txt`, `.env.example`, and `LICENSE` into the hidden package.
- After editing any copied file, run the sync script before testing or
  committing.

## testing/ is gitignored

- `testing/` is the local scratch directory: API keys, sample API
  responses, validation reports, integration scripts.
- Never write secrets above `testing/` (the rest of the repo is public).
- The `.gitignore` rule for `testing/` is load-bearing; do not change.

## Validation before push

Run from repo root:

```bash
python3 -c "from lib import publish, fetch_post, illustrate, refine, ApifyClient, PubloraClient, PixfaroClient; print('OK')"
python3 scripts/sync_codex_marketplace.py
wc -l SKILL.md skills/*/SKILL.md
ls skills/ | wc -l        # must equal 12
python3 scripts/check_frontmatter.py   # parses; a dir count does not prove a skill loads
python3 scripts/check_no_secrets.py    # .gitignore does not stop a rename of a tracked file
python3 scripts/check_config.py --offline   # credential wiring; --offline skips the live API calls
python3 scripts/check_actor_inputs.py  # Apify ignores unknown input keys; this catches a renamed one
python3 -m unittest discover -s tests    # contracts: docs vs code, response shapes, client behaviour
python3 scripts/selftest.py              # the whole picture: install, accounts, tests, what works now

Behaviour, not plumbing: `python3 evals/run_evals.py` runs the agent against
fixtures and grades what comes back (one model call per case, `--list` to see
them). Graders must have a right answer - the parentComment for a nested reply,
whether a scrub kept the user's figures. A grader that needs taste will drift,
and a wrong grader fails the skill for the grader's mistake.
grep -nE '^description:' skills/*/SKILL.md SKILL.md | grep -E '—|–'   # must be empty
```

If any of these fail, do not push.
