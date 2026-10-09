"""
DeepEval LLM judge backed by Groq API.

Subclasses DeepEvalBaseLLM so DeepEval metrics (GEval, Faithfulness, etc.)
call Groq natively instead of requiring an OpenAI-compatible endpoint.

Usage:
    from evals.quality.groq_judge import GroqJudge
    judge = GroqJudge()                            # uses default model
    judge = GroqJudge(model_name="gpt-oss-120b")   # override model

    from deepeval.metrics import GEval
    metric = GEval(name="coherence", criteria="...", model=judge)

Requires GROQ_KEY in environment (loaded from experiments/.env).
"""

import os
from pathlib import Path

from deepeval.models.base_model import DeepEvalBaseLLM


# Default judge model — non-reasoning, returns answers immediately.
# gpt-oss-120b is reasoning-mode and can consume all max_tokens on
# chain-of-thought, returning empty (known defect in Production Plan).
_DEFAULT_MODEL = "qwen/qwen3.8-27b"

# Project .env location
_ENV_PATH = Path(__file__).resolve().parent.parent.parent / "experiments" / ".env"


class GroqJudge(DeepEvalBaseLLM):
    """DeepEval-compatible LLM judge using Groq cloud inference."""

    def __init__(self, model_name: str = _DEFAULT_MODEL):
        self._model_name = model_name
        self._ensure_env()
        super().__init__(model=model_name)

    @staticmethod
    def _ensure_env():
        """Load .env if GROQ_KEY isn't already set."""
        if not os.getenv("GROQ_KEY"):
            from dotenv import load_dotenv
            load_dotenv(_ENV_PATH)

    def load_model(self):
        """Return a Groq client instance (stored as self.model by super)."""
        from groq import Groq
        key = os.getenv("GROQ_KEY")
        if not key:
            raise RuntimeError(
                "GROQ_KEY not set. Add it to experiments/.env or export it."
            )
        return Groq(api_key=key)

    def generate(self, prompt: str, schema=None) -> str:
        """Synchronous generation. DeepEval calls this for metric scoring."""
        resp = self.model.chat.completions.create(
            model=self._model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=500,
        )
        return resp.choices[0].message.content or ""

    async def a_generate(self, prompt: str, schema=None) -> str:
        """Async generation (required by DeepEval, used in batch evals)."""
        from groq import AsyncGroq
        key = os.getenv("GROQ_KEY")
        client = AsyncGroq(api_key=key)
        resp = await client.chat.completions.create(
            model=self._model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=500,
        )
        return resp.choices[0].message.content or ""

    def get_model_name(self) -> str:
        return self._model_name
