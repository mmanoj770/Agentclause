# Public Contract Benchmark Set (R11)

This directory holds anonymized real-world Indian contracts sourced from public domain repositories for evaluation of the review pipeline beyond synthetic unit fixtures.

> [!IMPORTANT]
> **Strict Separation from Synthetic Fixtures**:  
> The synthetic fixtures in `backend/tests/fixtures/contracts/` hold planted defects with fixed unit expectations (`expected_findings.json`).  
> In contrast, this directory (`public_contracts/`) is an open-ended benchmark set evaluated against real-world Indian legal drafting standards.

---

## 1. Permitted Sources

Contracts placed here must originate exclusively from public domain and open-access Indian repositories:
1. **Government e-Marketplace (GeM)**: Publicly published General Terms & Conditions (GTC), Service Level Agreements (SLA), and Special Terms & Conditions (STC).
2. **Central Public Procurement Portal (CPPP / tenders.gov.in)**: Public standard tender documents, model RFP contract formats, and general conditions of contract (GCC).
3. **Published Model Agreements**: Standard forms published by Indian chambers of commerce (e.g. FICCI, CII), publicly filed SEBI/MCA exhibits, or statutory sample forms.

---

## 2. Mandatory Anonymization Protocol

Before committing any contract file into this directory, ensure all identifiers have been anonymized:
- **Parties & Signatories**: Replace legal names with standard placeholders (e.g., `[Vendor Alpha Private Limited]`, `[Procuring Agency]`, `[Signatory Name]`).
- **Statutory & Tax IDs**: Ensure PAN, GSTIN, Aadhaar, and CIN numbers are stripped or replaced with placeholder tokens.
- **Financial Details**: Commercial rate tables, bank account numbers, IFSC codes, and specific pricing values must be replaced with `[Amount]` or standard dummy amounts.
- **Addresses & Contact**: Replace specific street addresses, phone numbers, and direct email addresses.
- **Confidentiality Check**: Never commit a non-public, customer-proprietary, or non-disclosure-bound agreement under any circumstances.

---

## 3. Contract Format

Each benchmark case consists of:
1. `<name>.txt`: The plain-text contract content.
2. `<name>.meta.json` (optional): Benchmark metadata:
   ```json
   {
     "name": "GeM Public Procurement Model Agreement",
     "source": "GeM Portal Model Contract",
     "document_type": "vendor_supplier",
     "source_url": "https://gem.gov.in",
     "notes": "Anonymized public service procurement agreement"
   }
   ```

---

## 4. Running the Benchmark

Run the automated evaluation benchmark runner:
```bash
python3 scripts/benchmark_public_contracts.py
```
This script executes the review layers (R2 Intake, R3 Completeness, R4/R5 Statutory Rules), measures execution runtime, and outputs a per-layer findings and coverage summary table.
