# Outreach: Legal Advocate (Statutory Verification Sign-Off)

**Target Audience**: Designated Legal Advocate / Verification Counsel  
**Subject**: Statutory Verification Sign-Off Pack for AgentClause (ICA, MSMED, CPC)  
**Related Artifacts**: 
- Pack: `docs/advocate_review_pack.md`
- Data Sheet: `docs/advocate_review_pack.csv`
- Tool: `scripts/apply_advocate_review.py`

---

## 1. Context & Objective

AgentClause operates with a strict verification barrier: in production (`strict=True`), the rules engine evaluates statutory and completeness findings **only** when verified by a qualified legal advocate against official gazetted text on India Code. Unverified seed rules return zero findings so that users never receive unverified advice.

To promote our seed rules from staging to verified, we require your professional review and sign-off on the 7 statutory provisions and required NDA clauses.

---

## 2. Review Package

All seed provisions have been compiled into a review pack:
- [Advocate Review Pack (Markdown)](file:///Users/manojmj/Agentclause/docs/advocate_review_pack.md)
- [Advocate Review Pack (CSV Spreadsheet)](file:///Users/manojmj/Agentclause/docs/advocate_review_pack.csv)

### Provisions Requiring Verification:
1. **Indian Contract Act, 1872**:
   - Section 27 (Agreement in restraint of trade void)
   - Section 28 (Agreements in restraint of legal proceedings void)
   - Section 74 (Compensation for breach of contract where penalty stipulated)
2. **Micro, Small and Medium Enterprises Development Act, 2006**:
   - Section 15 (Liability of buyer to make payment)
   - Section 16 (Date from which and rate at which interest is payable)
3. **Code of Civil Procedure, 1908**:
   - Section 20 (Other suits to be instituted where defendants reside or cause of action arises)
4. **Required NDA Baseline Clauses**:
   - Definition of Confidential Information, Governing Law, Term & Survival, Permitted Purpose, Standard of Care.

---

## 3. How to Execute Verification

Once you have verified the statutory quotes against [India Code](https://www.indiacode.nic.in/):

### Option A: Edit and Apply via Review Pack CSV
1. Open `docs/advocate_review_pack.csv`.
2. Inspect the text in `statute_quote`.
3. If text is accurate verbatim from India Code, mark `decision` as `VERIFIED`.
4. Provide your Bar ID / Name in `advocate_name` and the official India Code handle in `verification_ref`.
5. Run the review tool:
   ```bash
   # Dry-run validation:
   python scripts/apply_advocate_review.py --file docs/advocate_review_pack.csv --dry-run
   
   # Apply changes atomically:
   python scripts/apply_advocate_review.py --file docs/advocate_review_pack.csv --apply
   ```

### Option B: Command-Line Single Statute Verification
For individual database rows:
```bash
python scripts/verify_statute.py \
    --act "Indian Contract Act, 1872" \
    --section "27" \
    --advocate "Adv. <Your Full Name>" \
    --verification-ref "https://indiacode.nic.in/handle/123456789/2187"
```

The script automatically records your advocate credentials and timestamp in the immutable audit log and updates the database row.
