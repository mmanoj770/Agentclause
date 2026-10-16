"""
Drafting Agent (D4-D5).

Flow:
    D4 retrieval.retrieve_clauses -> find the right clause(s) in the corpus, ranked by score
    D5 adaptation.adapt_clause    -> fill in deal facts, never change legal substance,
                                     with a diff against the source clause

acceptance_check.py runs the lead's "done when" checks against the real database
and the real Gemini API:  python -m app.drafting.acceptance_check
"""
