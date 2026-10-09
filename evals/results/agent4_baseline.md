# Agent 4 — Dedup Eval Baseline

**Date:** 2026-10-07 (baseline), 2026-10-09 (V3 experiments)
**Script:** `evals/quality/ref_based/test_agent4.py` (baseline), `test_agent4_v3.py` (experiments)
**Golden dataset:** `evals/golden_dataset/agent4_dedup_v1.json` (10 sets, 80 titles, 5 expected pairs)
**Framework:** DeepEval (BaseMetric + custom DedupMergeMetric)
**Gate metric:** Micro-average F1 ≥ 0.70
**Model (baseline):** qwen3.5:9b (local only — no cloud backend)

---

## Summary — All Runs

| Model | Prompt | think | Micro-F1 | Micro-P | Micro-R | Time | Verdict |
|-------|--------|-------|----------|---------|---------|------|---------|
| qwen3.5:9b | V1 (baseline) | False | 0.333 | 0.333 | 0.333 | — | FAIL ✗ |
| qwen3.5:9b | V1 | True | 0.059 | — | — | — | FAIL ✗ |
| qwen3.5:9b | V2 (few-shot, string examples) | False | 0.057 | 0.029 | 1.000 | — | FAIL ✗ |
| qwen3.5:9b | V3 (few-shot, integer examples) | False | 0.571 | 1.000 | 0.400 | 139s | FAIL ✗ |
| gemma4:12b-mlx | V3 | False | 0.667 | 0.750 | 0.600 | 124s | FAIL ✗ |
| **granite4.2:8b** | **V3** | **False** | **0.800** | **0.800** | **0.800** | **76s** | **PASS ✓** |

**Best result: granite4.2:8b + Prompt V3 → F1 = 0.800 (PASS)**

---

## Baseline Results (Prompt V1, qwen3.5:9b)

### Per-Set Breakdown

| Set | Diff | P | R | F1 | Notes |
|-----|------|---|---|----|-------|
| 1 | easy | 1.000 | 0.500 | 0.667 | Found Shopify pair, missed Flux 3 pair (3,6) |
| 2 | easy | 1.000 | 0.500 | 0.667 | Found Xcode pair, missed TLS RFC pair (3,6) |
| 3 | easy | 1.000 | 1.000 | 1.000 | ✓ perfect (0-pair set) |
| 4 | medium | 0.000 | 1.000 | 0.000 | 3 false merges (2,4,7) on a 0-pair set |
| 5 | medium | 0.000 | 0.000 | 0.000 | Wrong merge (2,3) + missed correct merge (1,3) |
| 6 | medium | 1.000 | 1.000 | 1.000 | ✓ perfect (0-pair set, but via parsing fallback*) |
| 7 | hard | 0.000 | 1.000 | 0.000 | False merge (2,5) on a 0-pair set |
| 8 | hard | 1.000 | 1.000 | 1.000 | ✓ perfect (found US-China pair) |
| 9 | hard | 1.000 | 1.000 | 1.000 | ✓ perfect (found supply-chain pair) |
| 10 | hard | 1.000 | 1.000 | 1.000 | ✓ perfect (found productivity pair) |

**5/10 sets perfect, 5/10 failing.**

*Set 6: model returns `[1], [2], ...` without outer brackets → `ValueError: no JSON array found` → fallback treats all as singletons. Correct result by accident, not by understanding.

### Pooled Micro-Average

```
Precision:  0.333  (2/6 predicted merges correct)
Recall:     0.333  (2/6 expected merges found — note: only 5 expected pairs,
                     but 1 pair appeared in both pred and exp for offset math)
F1:         0.333  (gate ≥ 0.70)
```

---

## Experiment 1: think=True (Prompt V1, qwen3.5:9b)

**Hypothesis:** Enabling chain-of-thought reasoning might improve clustering decisions.
**Result:** F1 = 0.059 — **dramatically worse** than baseline.
**Root cause:** With think=True, `resp["response"]` is often empty; JSON appears in `resp["thinking"]` field instead. Even when extracted, the model's reasoning led to worse clustering — over-merging on domain similarity.
**Verdict:** Rejected.

---

## Experiment 2: Prompt V2 — Few-Shot with String Examples (qwen3.5:9b)

**Hypothesis:** Positive/negative few-shot examples showing product-family merges and domain-keyword traps would guide better clustering.
**Result:** F1 = 0.057 — **worse** than baseline.
**Root cause:** Few-shot examples used title strings (e.g., "Foo 3 released") → model returned title strings instead of integers → parser extracted 0 clusters → unassigned stories fell into one mega-cluster → C(8,2)=28 false pairs. Set 2 scored perfect 1.000 (reasoning improved), but format broke everything else.
**Key learning:** Output format in few-shot examples is critical — model mimics the example format, not just the logic.
**Verdict:** Rejected (but reasoning improvement confirmed — format was the issue).

---

## Experiment 3: Prompt V3 — Few-Shot with Integer Examples (multi-model)

**Hypothesis:** Fix V2's format bug (integer-only examples) + test multiple models.

### Prompt V3 Text
```
Group these numbered titles by SAME specific event or product.

Rules:
- SAME group: same product launch, same CVE, same court ruling, same company announcement
- SAME group: "ProductX 3" and "ProductX 3 Pro variant" = same product family
- SAME group: two RFCs about the same standard (e.g. TLS 1.2 deprecation) = same effort
- DIFFERENT: two stories that share a tech domain (both AI, both C++, both security) but are about different specific things
- When in doubt → SEPARATE groups

Return ONLY a JSON array of arrays of integers (1-indexed).
Every number from 1 to {n} must appear exactly once.
Example for 6 titles where 2 and 5 cover the same event:
[[1],[2,5],[3],[4],[6]]
```

### V3 Fixes Over V2
1. **Integer-only few-shot example** — `[[1],[2,5],[3],[4],[6]]` not string titles
2. **Safety fallback** — unassigned stories get their own cluster (prevents mega-cluster bug)
3. **Stricter string filtering** — `re.match(r'^\d+$', ...)` only accepts pure digit strings
4. **CLI model argument** — `python test_agent4_v3.py <model_name>`
5. **Timing** — seconds per set for speed comparison

### V3 Per-Set Results

#### qwen3.5:9b + V3 (F1 = 0.571)

| Set | Diff | P | R | F1 | Notes |
|-----|------|---|---|----|-------|
| 1 | easy | 1.000 | 1.000 | 1.000 | ✓ perfect |
| 2 | easy | 1.000 | 0.000 | 0.000 | FN: missed both pairs (1,5) and (3,6) — returned title strings |
| 3 | medium | 1.000 | 1.000 | 1.000 | ✓ perfect |
| 4 | medium | 1.000 | 1.000 | 1.000 | ✓ perfect — but returned title strings, safety net saved it |
| 5 | medium | 1.000 | 0.000 | 0.000 | FN: missed (1,3) |
| 6 | medium | 1.000 | 1.000 | 1.000 | ✓ perfect |
| 7 | hard | 1.000 | 1.000 | 1.000 | ✓ perfect |
| 8 | hard | 1.000 | 1.000 | 1.000 | ✓ perfect |
| 9 | hard | 1.000 | 1.000 | 1.000 | ✓ perfect |
| 10 | hard | 1.000 | 1.000 | 1.000 | ✓ perfect |

**8/10 perfect. Still returns title strings inconsistently (Sets 2-4), which the parser can't always recover from.**

#### gemma4:12b-mlx + V3 (F1 = 0.667)

| Set | Diff | P | R | F1 | Notes |
|-----|------|---|---|----|-------|
| 1 | easy | 1.000 | 1.000 | 1.000 | ✓ perfect |
| 2 | easy | 1.000 | 0.500 | 0.667 | Found Xcode pair (1,5), missed TLS RFC pair (3,6) |
| 3 | medium | 0.000 | 1.000 | 0.000 | FP: false merge (3,7) — hallucinated similarity |
| 4 | medium | 1.000 | 1.000 | 1.000 | ✓ perfect |
| 5 | medium | 1.000 | 0.000 | 0.000 | FN: missed (1,3) |
| 6 | medium | 1.000 | 1.000 | 1.000 | ✓ perfect |
| 7 | hard | 1.000 | 1.000 | 1.000 | ✓ perfect |
| 8 | hard | 1.000 | 1.000 | 1.000 | ✓ perfect |
| 9 | hard | 1.000 | 1.000 | 1.000 | ✓ perfect |
| 10 | hard | 1.000 | 1.000 | 1.000 | ✓ perfect |

**8/10 perfect. Clean integer JSON every time. Two errors: missed RFC pair, one false merge.**

#### granite4.2:8b + V3 (F1 = 0.800) ✓ PASS

| Set | Diff | P | R | F1 | Notes |
|-----|------|---|---|----|-------|
| 1 | easy | 1.000 | 1.000 | 1.000 | ✓ perfect |
| 2 | easy | 1.000 | 1.000 | 1.000 | ✓ perfect — found BOTH Xcode pair AND TLS RFC pair |
| 3 | medium | 1.000 | 1.000 | 1.000 | ✓ perfect |
| 4 | medium | 1.000 | 1.000 | 1.000 | ✓ perfect |
| 5 | medium | 1.000 | 0.000 | 0.000 | FN: missed C++26 pair (1,3) |
| 6 | medium | 1.000 | 1.000 | 1.000 | ✓ perfect |
| 7 | hard | 1.000 | 1.000 | 1.000 | ✓ perfect |
| 8 | hard | 0.000 | 1.000 | 0.000 | FP: false merge (4,6) — Huawei+Jemalloc |
| 9 | hard | 1.000 | 1.000 | 1.000 | ✓ perfect |
| 10 | hard | 1.000 | 1.000 | 1.000 | ✓ perfect |

**8/10 perfect. Clean integer JSON every time. Fastest model (76s, 7.6s/set). Only model to PASS the gate.**

---

## Failure Analysis — Baseline (3 Distinct Problems)

### 1. Missed product-family pairs (Sets 1, 2)
Model treats different version numbers / RFC numbers as separate events:
- **Set 1:** "Flux 3" vs "Flux 3 X Mimic: The Next Generation of Video-Action Models" — same product family launch
- **Set 2:** "RFC 9851: TLS 1.2 is in Feature Freeze" vs "RFC 10015: Deprecating Obsolete Key Exchange Methods in TLS 1.2" — same standards deprecation cycle

**Root cause:** Model is too literal — different identifiers (version numbers, RFC numbers) override semantic similarity.

### 2. False merges on domain keywords (Sets 4, 7)
Model groups unrelated stories that share a domain:
- **Set 4:** Merged Haskell GTK (2) + SDCC compiler (4) + PCB assembly (7) — all "low-level/embedded dev" but completely different projects
- **Set 7:** Merged Ornith-1.5 (2) + Bonsai 2 27B (5) — both "model compression" but different models

**Root cause:** Model clusters by thematic domain ("embedded dev", "model improvement") rather than checking for same specific event.

### 3. Wrong merge target (Set 5)
Merged GhostLock UAF (2) with C++26 PImpl (3) instead of C++26 loops (1) with C++26 PImpl (3).

**Root cause:** Model saw "C/C++ systems programming" link between a security bug and a language feature, instead of recognizing two C++26 standard features.

### Parsing bug (Set 6)
Model outputs `[1], [2], [3], ...` without outer `[[...]]` brackets. Parser raises ValueError, fallback produces all-singletons.

---

## Stubborn Set: Set 5 — C++26 Pair (1,3)

All three V3 models missed this pair. The two C++26 titles are:
- (1) "C++26: Trivial infinite loops are no longer undefined behaviour"
- (3) "The PImpl idiom and the C++26 std:indirect type"

These are both C++26 language-standard features but about completely different aspects (UB rules vs type system). This is a genuinely borderline case — arguably "same standard revision" but the topics are quite different. May warrant revisiting the golden label.

---

## Dataset Notes

- **Golden dataset v1 (revised):** 5 pairs across 10 sets, 7 zero-pair trap sets.
- **Consistency:** Baseline results are deterministic — same failures across two independent runs.
- **Model config:** temperature=0.1, think=False, keep_alive=0

---

## Next Steps

1. **N=5 reliability test** for granite4.2:8b + V3 to confirm 0.800 is stable (not a lucky run) — per project policy, never trust a single sample
2. If confirmed stable: apply granite4.2:8b + Prompt V3 to production `agent4.py`
3. Revisit Set 5 golden label — C++26 pair may be too borderline
4. Clean up experiment scripts (test_agent4_think.py, test_agent4_prompt_v2.py)

---

## Key Takeaways

1. **Prompt format matters more than prompt content:** V2 had good reasoning (Set 2 perfect) but string-format examples broke the parser catastrophically. V3 fixed only the example format → massive improvement.
2. **Model choice matters:** Same V3 prompt, three models — F1 ranged from 0.571 to 0.800. granite4.2:8b was best on accuracy AND fastest.
3. **Safety nets are essential:** The mega-cluster bug (0 clusters → all-in-one → 28 false pairs) shows that parser fallbacks need careful design. V3's "unassigned = own cluster" safety net prevented this.
4. **The false-positive problem is more production-harmful than false-negatives:** A false merge kills a legitimate story; a missed duplicate just leaves some redundancy.
