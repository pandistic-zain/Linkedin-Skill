# Story Bank

The raw material your posts are made of: what you have actually done, in numbers,
with names and dates. The Voice Profile holds *how you sound*. This holds *what
you have to say*.

Every writing skill in this bundle reads it before drafting, so it stops asking
you for "a specific number or moment" on every single request and starts drawing
from what you already told it once.

> **Keep this out of git.** It holds career detail, figures, failures and named
> people. It is a file in this repository, so a push carries it wherever you push,
> a public fork included. Add `references/story-bank.md` to your `.gitignore`
> before you fill it, or keep the filled copy outside the repo. Nothing here is
> sent to us or to any service; git is the only way it travels.

Fill it by running `linkedin-interviewer`, which interviews you and writes this
file. You can also edit it by hand at any time; the skill reads whatever is here.

## Status

- filled: yes
- updated: 2026-09-19
- sessions: 0 (seeded from project context, not an interview - Receipts, Scars and
  Recurring stories still need Zain's own numbers)

---

## 1. Timeline

Where you have worked and what changed at each stop. Dates matter: "March 2024"
beats "last year", because a post can anchor on it.

- (role, company, from-to, what you were actually responsible for)

## 2. Receipts

The numbers you can state without checking. This is the section the drafts reach
for most, because one odd-precision figure with a named referent is the single
strongest signal that a human wrote the post.

Good: "cut deploy time from 22 minutes to 9, team of four, Q2 2025".
Useless: "improved efficiency significantly".

- Quran Horizon live safety monitoring: browser-native Web Speech API shipped
  2026-07-01 (commit 318b0e3), replaced by self-hosted server-side streaming
  Whisper 2026-07-02 (commit aaa362d). One day between them.
- That swap took a day only because the self-hosted Whisper already existed:
  post-class transcription (backend/app/services/asr.py, faster-whisper) ran on it
  from the project's first commit (c0b34fc).
- Quran Horizon has never used a paid hosted STT API - no OpenAI, Deepgram,
  AssemblyAI, Azure or Google Speech appears anywhere in the repo history.

## 3. Shipped

Things that exist because you worked on them. Products, migrations, hires, papers,
events, rescues.

- **Fitnesstan** - SaaS diet and fitness planner built for the Pakistani market
  (local foods, local portions). Built solo, end to end. Includes the model work
  that generates the plans.
- **POS system** - a point-of-sale product rebuilt from the ground up to match a
  reference app's UI, feature set and DB schema, running on my own infrastructure.
- **Autonomous multi-agent crypto trading system** - Binance spot-first. LLM agents
  produce opinions; deterministic Python produces orders. Pydantic-validated agent
  output, a pure-Python risk engine with property tests, exchange-side stops via
  OTOCO, and a separate watchdog process. Phased build with hard gates - shadow
  mode, then paper, then micro-live.
- **MoneyPrinterTurbo build-out** - an autonomous AI short-video channel on top of
  the open-source MoneyPrinterTurbo repo.
- **MARE-Net** - plant disease diagnosis research; the basis of an MPhil research
  proposal.

(Add what each cost or returned - hours, users, revenue, a grade, a decision it
unlocked. A draft can use the project without a number, but it lands harder with one.)

## 4. Turning points

The moments where you changed your mind or the plan changed under you. These carry
posts better than successes do, and they are the hardest to invent.

- Live safety monitoring: the documented reason for leaving the browser's Web
  Speech API was not cost and not accuracy. It was reliability and control - the
  API only works in Chromium and the person being monitored can disable it
  client-side, which defeats a safety feature. Privacy (audio never leaving the
  server) was a real but secondary benefit.
- Building the trading system around a hard rule - "LLM agents produce opinions,
  deterministic Python produces orders" - instead of letting an agent place trades.
  What changed: the interesting part of an agent system is the boundary you refuse
  to let it cross, not the model.
- Designing the trading build so that *standing aside is a success*: eight
  deterministic gates, any one failure returns NO_TRADE, and a system that trades
  often in spot-only mode is a system whose gates are too loose.
- (Add your own - a client call you scoped wrong, a model you trusted too early, a
  framework you dropped.)

## 5. Scars

What went wrong and what it taught you. Kept separate from turning points because
the shape differs: a scar is a cost you paid, not a view you revised.

- (what broke, the real cost, what you do differently)

## 6. Positions

Opinions you would defend in a room that disagreed. A position with no cost to
holding it is not a position; note what holding it costs you.

- **An LLM's stated confidence is a language artefact, not a probability.** Plenty
  of agent demos gate on "I'm 85% confident". I gate on realised historical win rate
  read from a journal, adjusted to the lower bound of its confidence interval.
- **Build assuming the thing has no edge.** In the trading system that is written
  down as a rule: if expectancy is negative after fees at the paper stage, say so
  plainly rather than tuning parameters until the backtest looks good. That is the
  definition of overfitting, and it applies well beyond trading.
- **A backtest is optimistic and the model has partial memory of what happened.**
  Forward-testing is the only real evidence.
- (Add positions from your SaaS and client work - pricing, scoping, stack choices.)

## 7. Recurring stories

The three or four you already tell out loud, at dinner or in interviews. They are
proven: you know they land. Write them here before a draft dulls them.

- (the story in two lines, and the point it makes)

## 8. Names you can use

People, companies, tools and places you are free to name in public, and the ones
you are not. Drafts stay vague when they do not know which is which.

- Free to name: my own projects (Fitnesstan, the trading system, MARE-Net), open-
  source repos and public tools, languages and frameworks I use.
- Never name: client companies and client revenue without written permission;
  anything under NDA.
- Ask first: collaborators, supervisors and anyone whose work appears in a post.

## 9. Off limits

Subjects that stay out of posts regardless of how well they would perform: active
deals, litigation, health, other people's business, anything under NDA.

- Live trading P&L, account balances, or any figure that reads as a return claim.
  The trading system is a systems-engineering story, never a performance claim.
- Client names, client revenue, and anything from a client codebase.
- Application outcomes and anyone else's grades or reviews.

---

## How drafts use this

- A draft needs a concrete detail: it takes one from **Receipts** or **Shipped**
  rather than asking you mid-session.
- A hook formula needs a reversal or a confession: **Turning points** and **Scars**
  are where those live.
- A post needs an argument: **Positions** supplies the claim and the opposition.
- Anything a draft cannot source from here, it asks about or leaves out. It does
  not invent a number. If you see an unfamiliar figure in a draft, that is a bug
  worth reporting.
