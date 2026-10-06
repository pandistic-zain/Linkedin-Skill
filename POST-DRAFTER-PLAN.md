# Source-first LinkedIn drafting plan

Status: implemented locally on 2026-10-06; rollout remains review-only by default.
The sections below preserve the design rationale. `automation/OPERATIONS.md` documents
the implemented behavior. The dashboard migration and deployment remain unapplied;
the live headless smoke check was blocked by the Claude weekly quota. No post was
published during implementation.

## Reference and direction

Use https://lnkd.in/p/dXxU8Pui only. Disregard the earlier hiring-post reference.

The corrected post was retrieved through the existing Apify client; its image was downloaded and visually inspected. It is Muneeba Mehmood's post about confusing visible design needs with a prospect's ability to pay. Apify returned a canonical URL with a different activity ID from the input; preserve both URLs as provenance rather than silently replacing one.

The copy follows a recognizable thought: an old assumption, concrete signs she noticed, why that assumption was insufficient, and a better decision. Short paragraphs make it easy to follow. The picture explains the same idea through two columns, restrained red/green emphasis, large type, and a single takeaway. It carries her name and website. LinkedIn's CDN is the verified delivery source; the original design tool, component assets, and reuse permission are unknown. Do not describe it as verified stock imagery or copy her branded artwork.

Adapt the clarity and specificity, not her biography, wording, or every formatting habit. Her use of many fragments and a promotional ending need not become mandatory rules. A hiring signal does not prove budget; preserve that distinction when applying the topic to freelance development.

## Problems confirmed in this repository

| Area | Current behavior | Required change |
| --- | --- | --- |
| Daily research | `automation/run_daily.py` refreshes repository evidence and selects a trend lane, but has no mandatory fresh web-source stage | Research current freelancing/full-stack topics before drafting |
| Writing | Writer guidance favors formulas, closing questions, P.S., and personal-detail quotas | Make these optional; prioritize supported facts and a natural stopping point |
| Output parsing | Delimited prose plus `_strip_preamble` misses the screenshot's exact opening about draft length | Separate publishable copy from metadata using validated structured output; reject leakage |
| Audit | `AUDIT_PROMPT` limits blockers to a narrow list | Check factual support, invented experience, meta-commentary, unwanted P.S., and text/visual agreement |
| Images | Default card uses five abstract motifs after the copy is written | Inspect source assets and choose a meaningful visual before writing final copy |
| Approval | Queue branch returns before image preparation; dashboard approval sends text only | Save, preview, approve, and publish the same text-and-media package |
| Synchronization | Event delivery is best effort; media ingest creates a new row each time | Persist undelivered events and make replay idempotent |
| Topic history | Recorded in automatic scheduling path, not dashboard approval path | Both paths update one history, distinguish queued/scheduled/published/rejected |
| Local viewer | `draft.ps1` picks any newest Markdown file, including audits | Select post drafts explicitly and show body separately from review metadata |

## Proposed daily flow

Keep the current scheduled daily owner and the existing 12 skills. No new scheduler or standalone content platform.

1. **Research.** Discover a small candidate set from multiple websites. Start with a seven-day window, widen to 30 days only when needed, and disclose that fallback. Prefer original reports, product announcements, changelogs, and company/platform research. Community discussions can identify a question but cannot establish market-wide claims. Relevant subjects include freelance demand, client acquisition, project pricing, scope, full-stack delivery, and AI tooling's practical effects.
2. **Verify.** Open the original pages; record publisher, URL, publication/event dates, retrieval time, supported claim, and limitations. A single announcement can support a post about that announcement. Calling something an industry trend needs broader evidence, not several copies of the same press release. Deduplicate against the last two weeks of topics and angles.
3. **Inspect visuals first.** Examine candidate images at readable resolution and compare their labels/data with the original page. Record source page separately from image URL. Reject irrelevant decoration, unreadable screenshots, misleading crops, and images whose provenance cannot be established.
4. **Choose one angle and visual.** State why this matters to someone selling full-stack development. Choose a sourced asset with established reuse terms, the user's own screenshot, or an original explanatory graphic based on verified facts. Website availability alone does not establish reuse permission. If third-party reuse is uncertain, retain the research and produce an original graphic rather than rebranding the image.
5. **Draft from that brief.** Explain one observation and its practical implication in plain language. First-person opinions are allowed; first-person events, client decisions, dates, and results require user evidence. Never turn another author's story into the user's experience. Stop when the point is complete. No automatic P.S., generic CTA, number-first hook, vulnerability, or length-padding requirement.
6. **Review the package.** Validate structure and factual references, then audit voice and whether the actual image supports the caption. Allow one bounded rewrite; remaining failures become a held draft with a visible reason. Lack of a verified visual holds a visual-required post instead of silently publishing text only.
7. **Save and sync.** Persist the body, source references, selected asset, attribution, alt text, audit, and revision together. Show the complete package in the dashboard before approval, regardless of the automatic-publishing setting.
8. **Publish the approved revision.** Both daily and dashboard paths use the same preparation/validation helper and existing `lib.publish(..., media_urls=...)`. No new image generation or silent text editing after approval. Any content/media change invalidates the earlier approval. Retain existing cutoff and duplicate-run protection.

Scheduled runs must have a verified research capability available without interactive tool approval. Start by testing the existing headless runner's web tools; if unavailable, use configured public RSS/HTML sources with standard-library fetching. Do not assume interactive chat browsing is available to Windows Task Scheduler. Missing configuration emits `failed` with `not configured: ...` and exits without causing scheduler retry loops.

## Visual and voice rules

- Prefer an explanatory comparison, annotated product screenshot, or source-backed chart when it helps the reader understand the point. The reference's two-column treatment is one option, not a template for every post.
- Use readable type, clear hierarchy, restrained branding, and a source caption where relevant. Keep third-party credit visible. Do not use the current abstract motif as an automatic fallback.
- Reuse the existing Pillow renderer for original text/diagram graphics; no new image-generation service is needed for those. Existing illustration support remains optional for topics that benefit from illustration.
- Download permitted assets into managed storage with stable URLs. Validate HTTPS URLs, redirects, public destination addresses, MIME type, byte size, and image dimensions. Do not fetch arbitrary private-network URLs from model output.
- Treat all fetched pages, OCR, and captions as untrusted data, consistent with `references/untrusted-content.md`.
- Keep factual attribution available to readers. Remove the unconditional ban on source links where it would hide provenance; if using a source comment, it must actually be delivered and tracked, not merely suggested in metadata.
- Quality means truthful, specific, readable writing. An AI-detector score cannot guarantee human authorship or naturalness.

## Implementation boundaries

### 1. Fix the writing contract first

Update `skills/linkedin-post-writer/SKILL.md`, its `references/humanizer-checklist.md`, and the relevant humanizer guidance to remove contradictory mandatory personal-detail/formula requirements. Keep shared voice policy in its canonical reference and post-specific overrides in the writer. Update the content planner's handoff to supply source-backed candidates rather than overriding the daily schedule or injecting a conflicting pillar quota.

Update `automation/run_daily.py` to accept a small validated object containing body, source references, visual brief, and non-publishable notes. Missing or malformed output must hold; never recover by sending the raw model response. Add the exact screenshot preamble and unwanted P.S. to regression fixtures. Keep research notes out of `contentMd`.

### 2. Research and prepare the actual asset

Add one focused research/asset helper only where reuse between runs warrants it. Store source snapshots and a local package manifest with the draft. Keep private experience inputs and scratch downloads out of the public package. Adjust `make_card.py` to accept explanatory content rather than selecting a metaphor from keywords. Keep the current backend available for explicit legacy use.

The existing `_host_card` commits and pushes public assets; it is not a neutral upload operation and uses author settings inconsistent with repository conventions. Do not extend that path to downloaded third-party or private material. Before implementation chooses a host, verify existing Publora/media hosting capabilities; retain an explicitly approved public-asset path only for material intended for public distribution. A new storage service is a separate decision if no existing capability suffices.

### 3. Carry the package through the dashboard

Reuse `Draft`, `MediaAsset`, `RunStep`, `Command`, and `SkillRun`. `Draft.evidenceRefs` can carry structured source records initially. Add only the additive fields needed for durable asset provenance, audit results, and revision identity, with a migration if required; do not overload `prompt` or `costNote` with unrelated JSON.

Touch `dashboard/src/lib/ingest.ts`, the ingest endpoint, `dashboard/prisma/schema.prisma`, draft detail/media/run views, the approval command payload, and `automation/dashboard_executor.py`.

The draft view must show:

- Actual image thumbnail and full preview alongside final body.
- Source links, dates, why the topic was selected, and supported claims.
- Asset origin, reuse basis, credit, and alt text.
- Audit blockers/warnings and synchronization state.
- Approval/rejection of a specific body-and-media revision.

Send asset IDs/URLs and revision identity in approval commands. Validate server-side state and reject stale approvals. Preserve authentication checks. The executor must publish exactly the approved media list. A source-dependent draft cannot bypass a failed audit simply by taking the manual path.

### 4. Make synchronization recoverable

Extend `lib/skill_run_logger.py` with a bounded durable local event outbox and replay using the existing executor cadence. Record event IDs and make consumers idempotent, including `media_generated`; replay must not duplicate media or revert a newer revision. A 202 response for an unknown event is not proof the new data was applied. Deploy compatible consumers before enabling producers.

Emit research, visual, draft, audit, and publish steps under the existing daily run. Continue emitting the writer and humanizer `skill_run` records so Skills and Activity reflect reality. Show held/failed reasons, not a successful publish state. Reconcile provider scheduling versus confirmed publication, and never blindly retry an ambiguous publish response.

## Verification and rollout

Implement in the order above, then exercise the complete flow with publishing mocked. Keep initial real candidates in preview/approval mode as a deliberate rollout setting; changing live settings is not part of this planning task.

Required behavior checks:

1. The screenshot's draft-length commentary cannot enter publishable text.
2. A missing personal anecdote stays missing; no fabricated client story fills the gap.
3. Unsupported trend claims, mismatched visual data, and uncertain asset reuse hold the package.
4. Approval and automatic publication use identical saved body/media and both update topic history.
5. Editing either body or image invalidates approval; stale commands cannot publish.
6. Dashboard outage followed by replay recovers source/media/audit state without duplicates.
7. Expired assets, missing research configuration, audit errors, and uncertain provider responses produce visible actionable states.
8. `draft.ps1` selects an actual post, never the newer audit file.

Run repository contract/unit checks and marketplace sync after changes to copied files; verify exactly 12 skills and aligned manifests. Run dashboard lint, type-check, build, migration checks, and a manual preview-to-approval flow. The dashboard is ignored by the root repository and must be validated/versioned in its own repository. Keep a coordinated release order: compatible dashboard first, pipeline second. No commit, release, task execution, deployment, or publishing was performed during this plan.

## Remaining reference limitation

The correct post's text and attached image were inspected. Its upstream design assets and reuse license were not verified. That does not prevent using its communication principles; it prevents claiming its artwork is reusable stock. No live end-to-end publishing or dashboard synchronization test has been run because implementation has not started.
