# Agent 3 — Credibility Classification Eval Baseline

**Date:** 2026-10-07
**Script:** `evals/quality/ref_based/test_agent3.py`
**Golden dataset:** `evals/golden_dataset/agent3_credibility_v1.json` (n=30)
**Framework:** DeepEval (BaseMetric + custom ClassificationMetric)
**Gate metric:** Macro-F1 ≥ 0.70

---

## What Agent 3 Does

Agent 3 classifies each HackerNews story as **REAL**, **OPINION**, or **SPAM** using three inputs:

```
┌─────────────────────────────────┐
│         Agent 3 Input           │
│  • story title                  │
│  • story content (scraped)      │
│  • story background (enriched)  │
└──────────────┬──────────────────┘
               │
               ▼
┌─────────────────────────────────┐
│      LLM Classification        │
│                                 │
│  Primary:  gpt-oss-120b (Groq) │
│  Fallback: qwen3.5:9b (Ollama, │
│            thinking=False)      │
└──────────────┬──────────────────┘
               │
       ┌───────┼───────┐
       ▼       ▼       ▼
    ┌──────┐┌───────┐┌──────┐
    │ REAL ││OPINION││ SPAM │
    └──────┘└───────┘└──────┘
```

The LLM returns a float score (+0.9 → REAL, +0.1 → OPINION, −0.7 → SPAM), which is mapped back to a label.

---

## How the Eval Works

**Golden dataset:** 30 stories manually labelled by the developer (human judgement, not machine-generated). Each entry stores `title`, `content`, and the human-assigned `expected_label`.

**Evaluation method:** The eval calls Agent 3's actual `llm_credibility_check()` function on each golden story, collects predicted labels, and compares them to the human labels. This is **deterministic/code-based comparison** — no LLM judge is needed because the output is a discrete category (REAL/OPINION/SPAM), not free-form text. DeepEval provides the test harness; the scoring is pure Python.

---

## Why Macro-F1 (not accuracy, not micro-F1)

The golden dataset has a **class imbalance**: 26 REAL / 4 OPINION / 0 SPAM.

**Accuracy fails here.** A model that blindly predicts "REAL" for everything scores 26/30 = 87% accuracy — looks great, but catches zero OPINION stories.

**F1 = harmonic mean of precision and recall.** It punishes lopsided performance — if you have perfect precision but zero recall, F1 = 0 (not 0.5 like arithmetic mean would give).

**Macro-F1 vs Micro-F1:**
- **Micro-F1** pools all predictions together and computes one F1. Classes with more examples dominate. With 26 REAL vs 4 OPINION, getting REAL right matters ~6× more than OPINION. A lazy "always REAL" model still scores high.
- **Macro-F1** computes F1 per class separately, then averages them equally. OPINION's F1 counts as much as REAL's F1, regardless of support count. A lazy "always REAL" model gets F1_OPINION = 0.0, dragging macro-F1 down hard.

**Choice: Macro-F1** — because we care equally about catching OPINION stories (even though there are only 4) as we do about getting REAL right.

---

## Results

| Backend | Model | Macro-F1 | Accuracy | Verdict |
|---------|-------|----------|----------|---------|
| Groq (primary) | gpt-oss-120b | 0.990 | 29/30 (96.7%) | PASS ✓ |
| Local (fallback) | qwen3.5:9b | 0.990 | 29/30 (96.7%) | PASS ✓ |

---

## Confusion Matrix (identical for both backends)

```
            REAL   OPINION   SPAM
REAL          25         0      1
OPINION        0         4      0
SPAM           0         0      0
```

## Per-Class Metrics

| Class | Precision | Recall | F1 | Support |
|-------|-----------|--------|----|---------| 
| REAL | 1.000 | 0.962 | 0.980 | 26 |
| OPINION | 1.000 | 1.000 | 1.000 | 4 |
| SPAM | 0.000 | 0.000 | 0.000 | 0 |

> Note: SPAM has 0 support in golden dataset — F1 undefined, excluded from macro average.

---

## Failure Analysis

**1 failure across both backends:**

| Story | Expected | Predicted | Root Cause |
|-------|----------|-----------|------------|
| Stolen Buttons | REAL | SPAM | Scraped content is random UI button labels from an art project. Content *looks* like spam but the website is a legitimate creative project. |

**Decision:** Label kept as REAL — the website genuinely exists. This tests whether the model can distinguish unconventional-but-real content from actual spam.

---

## Dataset Notes

- **Class imbalance:** 26 REAL / 4 OPINION / 0 SPAM — no SPAM examples in golden set; future expansion should add SPAM samples
- **Content source:** `experiments/data/stories_cache.json` provides article text; golden dataset stores titles + labels + story_key references
- **Content guard:** Stories with < 500 chars of content return 0.0 (NEUTRAL) and are not classified — these are excluded from the eval

---

## Key Takeaway

Both primary and fallback models produce identical classifications on this dataset. The fallback (qwen3.5:9b) is a reliable substitute for the primary (gpt-oss-120b) on this task.
