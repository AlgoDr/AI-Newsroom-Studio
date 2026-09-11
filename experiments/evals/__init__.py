"""Production-level LLM eval suite for AI Newsroom Studio.

Run from anywhere:
    cd experiments
    ../multi-agent-env/bin/python evals/run_all.py            # unit evals only
    ../multi-agent-env/bin/python evals/run_all.py --content  # unit + LLM-judged evals

Purpose: regression net for the ACTUAL pipeline (agents + golden checkpoints),
to be run before ANY cloud deployment and after every pipeline change.
"""