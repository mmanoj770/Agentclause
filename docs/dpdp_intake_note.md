# DPDP Act 2023 Intake Data Flow & PII Mitigation Note

**Status**: Technical Architecture & Data Flow Reference (Pending Legal/Compliance Review)  
**Date**: November 2026  
**Component**: Layer 2 (R2) Contract Intake Normalisation (`backend/app/intake/service.py`)  
**Scope**: Pre-call redaction, external LLM payload boundary, and open compliance questions under India's Digital Personal Data Protection Act, 2023 (DPDP Act).

---

## 1. Context & Architecture Overview

The AgentClause contract review platform uses Gemini models (`gemini-3.5-flash-lite`) via Google's Generative Language API to perform structural extraction and normalisation of uploaded legal agreements into a standardised schema (`NormalizedDocument`).

To minimise the exposure of sensitive Indian Personal Identifiable Information (PII) to third-party model inference endpoints, the platform implements client-side, pre-call redaction and post-response restoration.

> [!IMPORTANT]
> **No Compliance Claim**: This note documents technical implementation and mitigations only. It does not constitute legal advice or establish statutory compliance under the DPDP Act 2023. Compliance determination requires formal review by designated Data Protection Officer (DPO) and external legal counsel.

---

## 2. Data Flow & System Boundaries

### What Leaves the System (Payload to Google Gemini API)
- The structured prompt containing the contract text wrapped in `<contract>` tags.
- Non-redacted business contract clauses, general operational terms, dates, and governing law clauses.
- Redacted placeholder tokens (e.g., `[PAN_1]`, `[AADHAAR_1]`, `[PHONE_1]`, `[EMAIL_1]`, `[BANK_ACC_1]`, `[IFSC_1]`, `[GST_1]`).

### What Stays Strictly Local (Never Transmitted Outside Server Boundary)
- **Raw PII Values**: Stored only in local server process memory during the request lifecycle.
- **Redaction Mapping Table**: Transient dictionary mapping placeholders to raw PII (`{"[PAN_1]": "ABCDE1234F"}`). Kept in local memory and discarded once extraction completes.
- **Original Contract Files & Extracted Text**: Stored in customer-tenant AWS S3 storage (`ap-south-1` Mumbai) and application PostgreSQL database (`ap-south-1`).
- **Verbatim Substring Verification**: Executed locally inside `service.py` comparing restored clause text against the original local document text.

---

## 3. Redaction Specifications (`INTAKE_REDACT_PII`)

Redaction is enabled by default via `INTAKE_REDACT_PII=True` in `backend/app/config.py`.

| Identifier Category | Pattern / Format | Placeholder Pattern | Example Raw Match | Redacted Token |
| :--- | :--- | :--- | :--- | :--- |
| **GSTIN** | `\b\d{2}[A-Z]{5}\d{4}[A-Z]{1}[A-Z\d]{1}Z[A-Z\d]{1}\b` | `[GST_n]` | `27ABCDE1234F1Z5` | `[GST_1]` |
| **PAN** | `\b[A-Z]{5}[0-9]{4}[A-Z]\b` | `[PAN_n]` | `ABCDE1234F` | `[PAN_1]` |
| **Aadhaar** | `\b[2-9]\d{3}[\s-]?\d{4}[\s-]?\d{4}\b` | `[AADHAAR_n]` | `2345 6789 0123` | `[AADHAAR_1]` |
| **IFSC Code** | `\b[A-Z]{4}0[A-Z0-9]{6}\b` | `[IFSC_n]` | `HDFC0001234` | `[IFSC_1]` |
| **Bank Account** | `(?i:\b(?:a/c\|account\|acc(?:\s*no\.?)?)\s*[:#-]?\s*)(\d{9,18})\b` | `[BANK_ACC_n]` | `Account No: 987654321012` | `Account No: [BANK_ACC_1]` |
| **Email** | `\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b` | `[EMAIL_n]` | `contact@acme.in` | `[EMAIL_1]` |
| **Phone / Mobile** | `(?:\+91[\s-]?)?[6-9]\d{9}\b` | `[PHONE_n]` | `+91 9876543210` | `[PHONE_1]` |

### Invariant Rules
1. **Multi-Occurrence Consistency**: Multiple occurrences of the same identifier map to the same placeholder index.
2. **Replacement Precedence**: GSTIN is replaced prior to PAN to prevent sub-string truncation of tax identifiers.
3. **Audit & Log Hygiene**: Server logs must **never** write raw PII strings. Logs record only counts and truncated 8-character SHA-256 hashes (`logger.info("... counts=%s hashes=%s", ...)`).

---

## 4. Open Policy & Legal Questions for Compliance Team

The compliance and legal team must investigate and formally resolve the following questions before moving beyond trial/pilot deployments:

1. **Google Cloud / Gemini Data Processing Terms (DPA)**:
   - Does the active Google Workspace / Google Cloud enterprise agreement incorporate a signed Data Processing Addendum (DPA)?
   - Does the API tier guarantee that input prompts and completions are **not logged or retained** for foundational model training or human evaluation?
2. **Lawful Basis & Consent Notices (DPDP Act ss. 5 & 6)**:
   - What notice format must be displayed to startup founders and enterprise users before document ingestion?
   - Is contract review classified as performance of a contract or specified purpose requiring explicit consent under Section 6?
3. **Cross-Border Transfer & Data Residency (DPDP Act s. 16)**:
   - The primary application data and S3 storage are strictly hosted in India (`ap-south-1`).
   - Google Gemini API calls may route across global regions if dynamic load balancing is enabled. Compliance counsel must confirm whether contract text transit across borders complies with DPDP Section 16 transfer regulations.
4. **Data Retention & Eradication (DPDP Act s. 8(7))**:
   - Establish formal operational procedures to guarantee that transient processing buffers are purged immediately upon transaction conclusion.

