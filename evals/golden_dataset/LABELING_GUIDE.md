# Agent 3 Credibility Classification — Labeling Guide

## Task
Given a story's **title** and **content**, assign exactly one label:
`REAL`, `OPINION`, or `SPAM`.

## Label Definitions

### REAL
A genuine product, technology, company, research finding, scientific
discovery, engineering achievement, or event.

Key signals:
- Reports or announces a concrete thing that exists or happened
- Show HN posts with a real product/demo → REAL (promotional tone is fine)
- GitHub repos with working code → REAL
- Academic papers / research results → REAL
- Company engineering blog posts describing a real system → REAL
- Product launch pages → REAL (even if marketing-heavy)
- News reporting on a real event or technology → REAL

**Promotional tone does NOT make something OPINION.**
A company describing its own product is still REAL if the product exists.

### OPINION
A personal essay, rant, commentary, or subjective argument that is not
primarily reporting a thing.

Key signals:
- First-person perspective arguing a position ("I think...", "We should...")
- "Stop doing X", "X considered harmful", "Why X is broken"
- Philosophical or cultural commentary on technology
- Personal retrospectives with no concrete deliverable being announced
- Listicles of personal recommendations (curated, not reported)

**The test:** if you removed the author's opinions, would anything
concrete remain? If no → OPINION. If yes → probably REAL.

### SPAM
Scam, clickbait, misinformation, or content with no real substance.

Key signals:
- Sensational claims with no evidence
- Crypto/NFT pump schemes
- SEO-bait with no real content
- Misleading headlines with fabricated information
- Content that exists solely to drive traffic, not inform

**SPAM is rare on HackerNews.** HN's moderation filters most of it.
If you're unsure between SPAM and OPINION, it's almost always OPINION.

## Edge Cases

| Scenario | Label | Reason |
|----------|-------|--------|
| "Show HN: My new tool" with working demo | REAL | Real product |
| Company blog: "How we scaled X" | REAL | Real engineering, real system |
| "Why I quit using X" | OPINION | Personal essay |
| Academic paper on arXiv | REAL | Research finding |
| Curated list: "Best tools for Y" | OPINION | Subjective curation |
| News article: "Company X acquires Y" | REAL | Real event |
| Product page with pricing | REAL | Real product |
| "An open letter to X" | OPINION | Advocacy/argument |
| Satire / humor post | OPINION | Not reporting a real thing |

## Process
1. Read the title and first ~500 chars of content
2. Ask: "Is this reporting/announcing a concrete thing?" → REAL
3. Ask: "Is this primarily someone's argument or perspective?" → OPINION
4. Ask: "Is this deceptive or substanceless?" → SPAM
5. When genuinely unsure, note it in the `comments` field

## Dataset Requirements
- Minimum 40 labeled examples
- Distribution should reflect HN reality: ~70% REAL, ~25% OPINION, ~5% SPAM
- Include edge cases (promotional-but-real, technical-opinion-pieces)
