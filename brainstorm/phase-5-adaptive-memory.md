# Phase 5 — Adaptive Memory

## Goal
The system learns a given user's investment style from their actual behavior over
time (not just their stated preferences from Phase 3) and adapts future
recommendations accordingly.

## Scope
- Builds on Phase 3's stored preferences and Phase 4's ongoing summaries/alerts,
  where there's now a history of interactions to learn from.
- This is the most open-ended phase — start narrow and expand.

## Requirements
- **Track behavioral signals**, not just declared preferences, such as:
  - Which recommendations the user acted on vs dismissed
  - Which alerts they engaged with vs ignored
  - Manual portfolio changes made after seeing a report (did they buy what was
    recommended, or the opposite?)
  - Any explicit feedback mechanism you add (e.g. thumbs up/down on a
    recommendation, with an optional reason)
- **Memory representation:** decide on a concrete, inspectable format before
  reaching for anything exotic — e.g. a running structured profile
  (`{prefers_growth: 0.7, avg_holding_period: "long", reacted_negatively_to: [...]}`
  ) is easier to reason about and debug than an opaque embedding store. A vector
  store of past interactions can be added later for retrieval if the structured
  profile isn't capturing enough nuance.
- **Feed memory into the Recommendation Agent** as another structured input
  (same claims format as other agents), e.g. "This user has historically favored
  lower-volatility holdings; this ticker's volatility profile is notably higher
  than their typical picks" — surfaced as a claim with its own evidence, not a
  silent weighting adjustment the user can't see.
- **Transparency and control:**
  - Users should be able to see what the system has inferred about their style
  - Users should be able to correct or reset it — this matters for trust, and
    it's also just good practice for anything shaping financial recommendations
- **Evaluation:** track whether adaptation is actually improving anything —
  e.g. does the user act on recommendations more often after the profile has
  had time to develop signal, compared to before

## Explicitly out of scope / cautions
- Don't let inferred memory silently override the user's explicit stated
  preferences from Phase 3 — explicit input should generally take precedence,
  with inferred memory filling gaps or flagged as a tension to resolve, not
  quietly overriding it
- Avoid over-fitting to short-term behavior (e.g. one panic-sell shouldn't
  permanently redefine the user's "style")

## Starter Prompt

> Extend the Phase 4 investment research tool with adaptive memory: the system
> should learn a user's investment style from their actual behavior over time
> and factor it into future recommendations.
>
> Requirements:
> - Track behavioral signals: which past recommendations the user acted on vs
>   dismissed, which alerts they engaged with, portfolio changes made after
>   seeing a report, and any explicit feedback (e.g. thumbs up/down with an
>   optional reason) you add to the UI.
> - Represent the learned profile as an inspectable structured object (not an
>   opaque embedding store) — e.g. fields like preferred volatility range,
>   typical holding period, sectors reacted to positively/negatively — updated
>   incrementally as new behavior comes in.
> - Feed this profile into the Recommendation Agent as a structured claim input
>   in the same format as other agents (claim, evidence, confidence), so its
>   influence on the final report is visible, not a silent scoring adjustment.
> - Explicit preferences from Phase 3 should take precedence over inferred
>   memory when they conflict; surface the tension as a claim rather than
>   silently picking one.
> - Add a UI where users can view what the system has inferred about their
>   style and reset or correct it.
> - Avoid over-fitting to short-term or one-off behavior when updating the
>   profile.
