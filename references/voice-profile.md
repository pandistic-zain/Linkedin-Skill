# Voice & Brand Profile

Your voice, niche, and rules in one place. Fill this once (or let
`linkedin-humanizer` build it from a few of your real posts), and every writing
skill in this bundle reads it before drafting, so you stop re-explaining who you
are on every request. This file is yours: edit it freely, keep it as long or
short as you like. Nothing here is sent to us or to any service; it only steers
the drafts.

> **It is a file in this repository, though, so git can carry it.** If you
> cloned or forked this repo and you push, a filled profile goes wherever you
> push it, including a public fork. Either add `references/voice-profile.md` to
> your `.gitignore`, or keep the filled copy outside the repo and paste it in
> when you need it. The shipped template is empty; what you add is yours to
> protect.

Skills only load this profile when `filled: yes` below. An empty template is
ignored, so drafts fall back to the generic voice rules until you populate it.

## Status

- filled: yes
- source: seeded from project context; voice fingerprint (section 1) and signature
  examples (section 5) still need Zain's own posts
- updated: 2026-09-19

## 1. Voice fingerprint

> **NOT YET LEARNED.** Sections 2-4 below are real and should be obeyed. This
> section is not: no posts of Zain's have been analysed. Until it is filled, use
> the generic voice rules for rhythm and word choice, and offer
> `linkedin-humanizer --mode profile` once per session so it can be learned from
> 3-5 real posts. Do not guess a fingerprint from the pillars.

How your writing actually sounds. Be specific; examples beat adjectives.

- Sentence rhythm: (e.g. mostly short, one long every few lines; or steady medium)
- Signature openers: (lines/phrases you tend to start with)
- Punctuation habits: (e.g. you use `..` as a soft pause; you never use em dashes)
- Words and phrases you use a lot:
- Words and phrases you NEVER use: (banned vocab, cliches you hate)
- Emoji: (none / one occasionally / which ones)
- Formatting: (one idea per line? lists? no hashtags?)

## 2. Who you are and who you write for

- You are: Zain - builds SaaS products end to end, does ML/research work, and takes on freelance/client projects.
- Your audience (ICP): founders and technical leads who might hire or collaborate; other builders shipping solo; ML practitioners.
- Your content pillars:
  1. Building in public - shipping SaaS products solo (architecture calls, tradeoffs, what broke)
  2. ML / research - models, evaluation, what the papers leave out
  3. Freelance / client work - scoping, pricing, delivery, lessons from real projects
  4. Systems & automation - agents and pipelines that do real work

## 3. Hard rules (always / never)

- Always: first person. One concrete, checkable detail per post - a constraint, a
  tradeoff, a number I can actually stand behind. Name the thing I built. Say what
  went wrong as readily as what worked. If I'm uncertain, say so in the post.
- Never: engagement bait ("agree?", "thoughts?", "comment YES"). No fake vulnerability
  or manufactured origin story. No implied income or returns - especially not from
  the trading work. No invented numbers: if the Story Bank doesn't have the figure,
  the post goes out without one. No "in today's fast-paced world". No hustle-guru
  register. No hashtag stacks.

## 4. Links and CTA

- Primary link you point people to: (GitHub / portfolio - fill this in)
- Where it goes: first comment, not the post body.
- Your CTA style: soft invite. Most posts end with no CTA at all; when there is one,
  it is an open door ("happy to go into the risk engine if anyone's building
  something similar"), never a direct ask.

## 5. Signature examples

Paste 2-4 of your own real lines or short posts that sound most like you. The
writing skills mirror the rhythm and word choice of these, not a generic voice.

-
-
-

## 6. Brand assets (for illustrations)

Used by the illustration step (`lib.illustrate`) to keep every generated image
on-brand via a pixel-exact overlay. All optional; leave blank to skip the overlay.

- Handle to stamp on images: webbyzain.online
- Brand color (hex): #D71920 (crimson, from webbyzain.online)
- Logo: (path or Pixfaro `logo_id`, if you have one — a path can be uploaded
  once with `lib.brand_logo(path)`, which returns the `logo_id` to record here)
- Overlay position: bottom-right
- Visual style default: bold editorial on near-black (#08080A) with paper (#F7F7F3)
  text and crimson (#D71920) as a single accent - never a crimson fill. Flat,
  geometric, no stock-photo people, no glowing-neon-AI look. Secondary: #123C69.
  Type reference: Syne for display, Manrope for body, DM Mono for labels.
- Card style: brand
