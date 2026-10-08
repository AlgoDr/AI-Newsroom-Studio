# Agent 3 — Credibility Classification Eval Baseline

**Date:** 2026-10-07
**Script:** `evals/quality/ref_based/test_agent3.py`
**Golden dataset:** `evals/golden_dataset/agent3_credibility_v1.json` (n=30)
**Framework:** DeepEval (BaseMetric + custom ClassificationMetric)
**Gate metric:** Macro-F1 ≥ 0.70

---

## Results

| Backend | Model | Macro-F1 | Accuracy | Verdict |
|---------|-------|----------|----------|---------|
| Groq (primary) | gpt-oss-120b | 0.990 | 29/30 (96.7%) | PASS ✓ |
| Local (fallback) | qwen2.5:7b | 0.990 | 29/30 (96.7%) | PASS ✓ |

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

- **Class imbalance:** 26 REAL / 4 OPINION / 0 SPAM — macro-F1 chosen as gate metric specifically because accuracy would mask class-level failures
- **No SPAM examples in golden set** — future dataset expansion should add SPAM samples
- **Content source:** `experiments/data/stories_cache.json` provides article text; golden dataset stores titles + labels + story_key references

---

## Key Takeaway

Both primary and fallback models produce identical classifications on this dataset. The fallback (qwen2.5:7b) is a reliable substitute for the primary (gpt-oss-120b) on this task.
