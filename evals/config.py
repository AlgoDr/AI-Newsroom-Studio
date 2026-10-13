"""Shared configuration for evals.

Constants used by content_evals.py and unit_evals.py. Values are
sourced from the production agents (agent5.py, agent6.py) so the
eval thresholds match what the pipeline actually enforces.
"""

from __future__ import annotations

# ── Judge model (used by content_evals LLM-judged scoring) ───────
JUDGE_MODEL = "qwen/qwen3.8-27b"
JUDGE_MAX_TOKENS = 256

# ── Content eval thresholds ──────────────────────────────────────
FAITHFULNESS_THRESHOLD = 0.70
RELEVANCE_THRESHOLD = 0.70

# ── Word budget guardrail (content_eval_cost_guardrail) ──────────
# MAX_WORDS_PER_RUN is the absolute ceiling for the cost eval.
# It's deliberately higher than TARGET_MAX to allow for minor
# overshoot without failing the cost guardrail — the per-script
# word count check (TARGET_MIN/MAX) is the tighter constraint.
MAX_WORDS_PER_RUN = 300

# ── Script QC constraints (from agent5.py / agent6.py) ───────────
TARGET_MIN_WORDS = 150   # 60 sec at 2.5 words/sec
TARGET_MAX_WORDS = 225   # 90 sec at 2.5 words/sec

SECTION_ORDER = [
    "HOOK", "S1_CONTEXT", "S1_CORE", "S1_TWIST",
    "S2_HOOK", "S2_CORE", "S2_TWIST",
    "S3_HOOK", "S3_CORE",
    "CTA",
]
