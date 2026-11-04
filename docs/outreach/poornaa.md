# Outreach: Poornaa (Clause Manifest & Drafting Agent Integration)

**Target Audience**: Poornaa  
**Subject**: Clause Manifest (R8 #7) & Drafting Agent Interface (D1–D8)  
**Status**: Ready for manifest integration; drafting code strictly isolated

---

## 1. Boundary & Non-Interference Confirmation

As established in team guidelines, all Drafting Agent files (`app/drafting/`, `D1–D8`) and the clause manifest specification have been left completely untouched on branch `blockers-prep`. No stubs were introduced that bypass the citation gate.

---

## 2. Review Pipeline Touchpoints with the Clause Manifest

The Review Agent layers interface with your work at two primary junctures:

1. **Layer 6 (Cross-Clause Consistency)**:
   - Evaluates contradictory terms and mismatching timeframes between clauses.
   - Currently requires the canonical clause manifest (R8 #7) so findings reference standard contract section mappings rather than provisional heuristics.

2. **Layer 7 (Risk Asymmetry & Market Baselines)**:
   - Emits findings citing `Internal: Clause <n> baseline:<entry>`.
   - The Citation Gate (Layer 8) checks these internal citations against allowed baseline entries.
   - With your clause manifest in place, the gate will validate clause references against the document's structured section manifest without false-positive blocks.

3. **Status of Asymmetry & Triage Weights**:
   - `asymmetry.json` and `triage.json` remain marked with `"status": "PLACEHOLDER"`.
   - Both layers now output `provisional: True` with explicit reasons so that drafting reviews do not treat interim weights as calibrated market counsel baselines.
