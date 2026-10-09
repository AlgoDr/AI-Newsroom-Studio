"""Interactive labeling helper for Agent 3 golden dataset.

Shows each story in readable form (decoded unicode, no JSON escapes).
Type R (REAL), O (OPINION), or S (SPAM). Saves valid JSON automatically.
Press Enter to skip, Q to quit and save progress.
"""

import json
from pathlib import Path

CANDIDATES = Path(__file__).resolve().parent / "agent3_credibility_candidates.json"
OUTPUT     = Path(__file__).resolve().parent / "agent3_credibility_v1.json"

# Load raw file as text, fix bare REAL/OPINION/SPAM → quoted strings
raw = CANDIDATES.read_text()
for word in ["REAL", "OPINION", "SPAM"]:
    raw = raw.replace(f': {word},', f': "{word}",')
    raw = raw.replace(f': {word}\n', f': "{word}"\n')

try:
    data = json.loads(raw)
except json.JSONDecodeError as e:
    print(f"JSON parse error: {e}")
    print("Fix agent3_credibility_candidates.json manually, then re-run.")
    exit(1)

# Count already labeled
labeled = sum(1 for d in data if d["expected_output"] is not None)
total = len(data)
print(f"\n{'='*60}")
print(f"Agent 3 Golden Dataset Labeler")
print(f"{'='*60}")
print(f"Stories: {total} | Already labeled: {labeled} | Remaining: {total - labeled}")
print(f"\nFor each story, type:")
print(f"  R = REAL    O = OPINION    S = SPAM")
print(f"  Enter = skip    Q = quit and save")
print(f"  C = add a comment")
print(f"{'='*60}\n")

SHORTCUT = {"R": "REAL", "O": "OPINION", "S": "SPAM"}

for i, item in enumerate(data):
    if item["expected_output"] is not None:
        continue  # already labeled

    meta = item["additional_metadata"]
    print(f"\n--- [{i+1}/{total}] ---")
    print(f"TITLE:   {item['input']}")
    print(f"DOMAIN:  {meta['domain']}")
    print(f"URL:     {meta['url']}")
    print(f"\nCONTENT PREVIEW:")
    # Show decoded, clean content
    preview = meta["content_preview"]
    # Strip markdown image tags for readability
    import re
    clean = re.sub(r'!\[.*?\]\(.*?\)', '[image]', preview)
    print(f"  {clean[:400]}")
    print()

    while True:
        choice = input("Label (R/O/S/Enter/Q/C): ").strip().upper()
        if choice == "":
            print("  → skipped")
            break
        elif choice == "Q":
            # Save and quit
            with open(OUTPUT, "w") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            labeled = sum(1 for d in data if d["expected_output"] is not None)
            print(f"\nSaved to {OUTPUT.name} ({labeled}/{total} labeled)")
            exit(0)
        elif choice == "C":
            comment = input("Comment: ").strip()
            item["comments"] = comment
            print(f"  → comment saved, now label this story:")
            continue
        elif choice in SHORTCUT:
            item["expected_output"] = SHORTCUT[choice]
            item_label = SHORTCUT[choice]
            print(f"  → {item_label}")
            break
        else:
            print("  Invalid. Use R, O, S, Enter, Q, or C.")

# All done
with open(OUTPUT, "w") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)

labeled = sum(1 for d in data if d["expected_output"] is not None)
print(f"\n{'='*60}")
print(f"Done! Saved to {OUTPUT.name} ({labeled}/{total} labeled)")
print(f"{'='*60}")
