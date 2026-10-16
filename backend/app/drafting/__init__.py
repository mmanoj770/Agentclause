"""
Drafting Agent (D4-D8).

Flow:
    D4 retrieval.retrieve_clauses  -> find the right clause(s) in the corpus
    D5 adaptation.adapt_clause     -> fill in deal facts, never change legal substance
    D7 citations.resolve_citations -> statute citations come from metadata, never the LLM
    D6 assembly.assemble_document  -> numbered contract with definitions and cross-references
    D8 guard.render_for            -> only verified clauses reach lawyer-facing output
"""
