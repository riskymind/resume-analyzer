"""Word lists used by the scoring rules. Plain data, easy to review and extend."""

from __future__ import annotations

# Stored as one whitespace-separated block for readability.
ACTION_VERBS = frozenset(
    """
    accelerated accomplished achieved acquired adapted addressed administered advanced advised advocated
    aligned analysed analyzed anticipated applied appointed architected arranged assembled assessed attained
    audited authored automated balanced benchmarked boosted briefed budgeted built calculated captured
    catalogued centralised centralized championed chaired clarified coached coded collaborated collected
    combined commissioned communicated compiled completed composed computed conceived conceptualised
    conceptualized conducted configured consolidated constructed consulted contracted contributed controlled
    converted convinced coordinated corrected counselled counseled created cultivated curated customised
    customized cut debugged decreased defined delegated delivered demonstrated deployed designed detected
    determined developed devised diagnosed directed discovered dispatched documented doubled drafted drove
    edited educated eliminated enabled encouraged engineered enhanced established estimated evaluated examined
    exceeded executed expanded expedited experimented explored extended facilitated fixed forecasted formalised
    formalized formulated fostered founded generated grew guided halved handled headed hired identified
    implemented improved increased influenced initiated innovated inspected installed instituted instructed
    integrated interpreted interviewed introduced invented investigated launched led leveraged lowered maintained
    managed mapped marketed maximised maximized measured mediated mentored merged migrated minimised minimized
    modelled modeled modernised modernized monitored motivated navigated negotiated onboarded operated optimised
    optimized orchestrated organised organized originated outperformed overhauled oversaw partnered performed
    piloted pioneered planned prepared presented prevented prioritised prioritized processed procured produced
    profiled programmed promoted proposed prototyped provided published raised ran rebuilt reconciled recruited
    redesigned reduced refactored refined regulated rehabilitated reinforced remodelled renegotiated reorganised
    reorganized replaced reported represented researched resolved restructured retained revamped reviewed
    revised revitalised revitalized saved scaled scheduled scoped screened secured selected shaped shipped
    simplified solved sourced spearheaded specified sped stabilised stabilized standardised standardized
    steered streamlined strengthened structured succeeded supervised supported surpassed synthesised
    synthesized systematised tackled targeted taught tested tracked trained transformed translated tripled
    troubleshot tuned unified upgraded utilised utilized validated verified won wrote
    """.split()
)

WEAK_PHRASES = (
    "responsible for",
    "duties included",
    "duties include",
    "worked on",
    "helped with",
    "helped to",
    "tasked with",
    "involved in",
    "assisted with",
    "assisted in",
    "participated in",
    "in charge of",
)

BUZZWORDS = (
    "hard-working",
    "hardworking",
    "team player",
    "detail-oriented",
    "detail oriented",
    "results-driven",
    "results driven",
    "go-getter",
    "self-starter",
    "self starter",
    "synergy",
    "think outside the box",
    "dynamic",
    "motivated individual",
    "highly motivated",
    "passionate",
    "best of breed",
    "proven track record",
    "excellent communication skills",
)

FIRST_PERSON = ("i", "me", "my", "mine", "myself")
