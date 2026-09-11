"""Central configuration for the eval suite.

All thresholds live here so a reviewer can see -- at a glance -- what
"production quality" means for this pipeline. Every value is derived
from real constraints already encoded in the agents (e.g. script
word-count limits in agent6.py) or from the project's own claims
(e.g. "150-225 word script" in AGENTS.md), NOT invented for evals.
"""

from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────
EXPERIMENTS_DIR = Path(__file__).resolve().parent.parent   # .../experiments
DATA_DIR = EXPERIMENTS_DIR / "data"
CHECKPOINT_DIR = DATA_DIR / "checkpoints"
STORIES_CACHE_PATH = DATA_DIR / "stories_cache.json"
ENV_PATH = EXPERIMENTS_DIR / ".env"

# Checkpoint used as the golden full-pipeline state (real run, 2026-07+)
GOLDEN_CHECKPOINT = "till-agent9.json"

# ── Script QC thresholds (mirror agent6.py TARGET_MIN/TARGET_MAX) ─
TARGET_MIN_WORDS = 150
TARGET_MAX_WORDS = 225

# The 10 sections Agent 6 validates, in script order.
SECTION_ORDER = [
    "HOOK", "S1_CONTEXT", "S1_CORE", "S1_TWIST",
    "S2_HOOK", "S2_CORE", "S2_TWIST",
    "S3_HOOK", "S3_CORE", "CTA",
]

# ── Content-eval judge LLM (same model family the pipeline itself
#    uses for QC -- gpt-oss-120b via Groq). Keeps cost near zero.
JUDGE_PROVIDER = "groq"
JUDGE_MODEL = "openai/gpt-oss-120b"
FAITHFULNESS_THRESHOLD = 0.80   # script claims must be grounded in sources
RELEVANCE_THRESHOLD = 0.80      # title/hook must relate to selected stories

# ── Cost guardrail (validates the "3x lower token" claim we make in
#    the resume -- script + context should stay well under this) ────
MAX_WORDS_PER_RUN = 350