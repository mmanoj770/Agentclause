# Outreach: Compliance & Legal Counsel (DPDP Act 2023 Intake Review)

**Target Audience**: Data Protection Officer (DPO) / Regulatory Compliance Counsel  
**Subject**: Technical PII Redaction Architecture & DPDP Act 2023 Compliance Review  
**Related Artifact**: [docs/dpdp_intake_note.md](file:///Users/manojmj/Agentclause/docs/dpdp_intake_note.md)

---

## 1. Technical Implementation Summary

To mitigate privacy risks when sending contract documents to Google Gemini API endpoints (`gemini-3.5-flash-lite`), Layer 2 (R2 Intake) features client-side, pre-call redaction and post-inference restoration:

1. **Redacted Identifiers**:
   - GSTIN (`[GST_1]`)
   - PAN (`[PAN_1]`)
   - Aadhaar (`[AADHAAR_1]`)
   - Bank Account Numbers (`[BANK_ACC_1]`)
   - IFSC Codes (`[IFSC_1]`)
   - Mobile / Phone Numbers (`[PHONE_1]`)
   - Email Addresses (`[EMAIL_1]`)
2. **Context Guarding**:
   - Currency figures (`Rs. 5,00,000`, `INR 1,25,00,000`), clause numbers (`1.`, `2.1`), dates (`2026-10-15`), and invoice identifiers (`INV-2026-001`) are protected by context guards and never mistakenly redacted as phone numbers or bank accounts.
3. **Audit Hygiene**:
   - Application logs record only counts and 8-character SHA-256 hashes (`hashes={'PAN': ['...']}`). Raw personal data is strictly prohibited from log streams.

---

## 2. Critical Compliance Disclosure: Scope Limitation

> [!IMPORTANT]
> **"Redaction ON" Does NOT Mean Zero Personal Data.**  
> The redaction engine operates on structured regex rules. The following categories of data are **not redacted** and continue to leave the server boundary to the external Gemini API:
> - **Corporate Entity Names**: e.g., "Tata Consultancy Services Ltd", "Acme Technologies Private Limited".
> - **Individual Signatory / Party Names**: e.g., "Rajesh Sharma", "Priya Verma".
> - **Physical Addresses**: Registered office locations, state and city lines.
> - **Free-Text Personal Data**: Personal data embedded in unstructured narrative clauses.

---

## 3. Formal Actions Required from Compliance

Before moving from pilot to general enterprise availability, legal counsel must formally sign off on:

1. **Google Cloud Data Processing Addendum (DPA)**:
   - Ensure a signed enterprise DPA is active with Google Cloud specifying that customer prompts and completions are zero-retention and not used for model training.
2. **Cross-Border Data Transit (DPDP Act s. 16)**:
   - While primary database and S3 storage reside in Mumbai (`ap-south-1`), API inference requests may dynamically route across global data centers. Counsel must confirm whether contract processing transit complies with DPDP Section 16 regulations.
3. **User Notice and Lawful Basis (DPDP Act ss. 5 & 6)**:
   - Define customer-facing notice language and consent flow required prior to contract upload.
