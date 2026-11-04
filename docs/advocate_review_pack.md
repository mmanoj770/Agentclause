# Advocate Review Pack (R3 Completeness, R5 Seed Rules & Database Statutes)

> [!IMPORTANT]
> **For Verifying Advocate / Legal Counsel**:
> This review pack is compiled automatically from the AgentClause repository configurations, rule files,
> and database seed statutes. In accordance with platform governance, production strict mode returns zero
> findings on unverified rules until a licensed Indian advocate verifies these quotes against authoritative
> sources (India Code) and confirms the required clauses.

## Review Instructions
1. **Statutory Quotes (R5 & Database Statutes)**: Open each India Code URL and check whether the staged quote matches the operative statutory text word-for-word. Note any corrections.
2. **Required Clause Lists (R3)**: Confirm that the mandatory clause lists reflect standard practice and legal enforceability under Indian law.
3. **Sign-off**: Mark verified rows in `docs/advocate_review_pack.csv` with `verified` = `yes`, `advocate_name` = `<Your Name>`, and `verification_date` = `<YYYY-MM-DD>`.

---

## Part 1: Statutory Seed Rules & Database Statutes (8 Entries)

### 1. `MSMED_S15_PAYMENT_BEYOND_45_DAYS` (Micro, Small and Medium Enterprises Development Act, 2006, s. 15)
- **Store**: `rules + seed_statutes`
- **Severity**: `high` | **Applies To**: msa, sla, vendor_supplier
- **India Code Verification URL**: [https://www.indiacode.nic.in/handle/123456789/2013?view_type=browse&sam_handle=123456789/1362](https://www.indiacode.nic.in/handle/123456789/2013?view_type=browse&sam_handle=123456789/1362)
- **Rule Logic / Heading**: The contract allows payment more than 45 days after the goods or services are delivered. If the supplier is a micro or small enterprise, s.15 caps the agreed payment period at 45 days from acceptance, whatever the contract says.
- **Remedy Suggested**: Shorten the payment period to 45 days or less from acceptance of the goods or services. First check whether the supplier is registered as a micro or small enterprise (Udyam registration): the cap only protects those suppliers.
- **Staged Quote**:
  > s.15: "Where any supplier supplies any goods or renders any services to any buyer, the buyer shall make payment therefor on or before the date agreed upon between him and the supplier in writing or, where there is no agreement in this behalf, before the appointed day: Provided that in no case the period agreed upon between the supplier and the buyer in writing shall exceed forty-five days from the day of acceptance or the day of deemed acceptance."

| Verified (Yes/No) | Advocate Name | Date (YYYY-MM-DD) | Corrected Quote (if any) | Notes |
| :---: | :---: | :---: | :--- | :--- |
| [ ] | | | | |

### 2. `MSMED_S16_INTEREST_WAIVER` (Micro, Small and Medium Enterprises Development Act, 2006, s. 16)
- **Store**: `rules + seed_statutes`
- **Severity**: `high` | **Applies To**: msa, sla, vendor_supplier
- **India Code Verification URL**: [https://www.indiacode.nic.in/handle/123456789/2013?view_type=browse&sam_handle=123456789/1362](https://www.indiacode.nic.in/handle/123456789/2013?view_type=browse&sam_handle=123456789/1362)
- **Rule Logic / Heading**: The contract waives or limits interest on late payment. If the supplier is a micro or small enterprise, s.16 makes a buyer who pays late liable for compound interest at three times the RBI bank rate, notwithstanding anything in the agreement, so this clause cannot take that right away.
- **Remedy Suggested**: Remove the waiver or cap on late-payment interest. Either say nothing, or state that interest on late payment is payable as provided in section 16 of the MSMED Act. First check whether the supplier is a registered micro or small enterprise.
- **Staged Quote**:
  > s.16: "Where any buyer fails to make payment of the amount to the supplier, as required under section 15, the buyer shall, notwithstanding anything contained in any agreement between the buyer and the supplier or in any law for the time being in force, be liable to pay compound interest with monthly rests to the supplier on that amount from the appointed day or, as the case may be, from the date immediately following the date agreed upon, at three times of the bank rate notified by the Reserve Bank."

| Verified (Yes/No) | Advocate Name | Date (YYYY-MM-DD) | Corrected Quote (if any) | Notes |
| :---: | :---: | :---: | :--- | :--- |
| [ ] | | | | |

### 3. `NDA_CONFIDENTIAL_INFO_DEFINITION_MISSING` (Internal, s. NDA baseline, definition of Confidential Information)
- **Store**: `rules`
- **Severity**: `high` | **Applies To**: nda
- **India Code Verification URL**: [N/A (Internal Baseline)](N/A (Internal Baseline))
- **Rule Logic / Heading**: The NDA never defines "Confidential Information", so it is unclear what the obligations protect.
- **Remedy Suggested**: Add a definition: "Confidential Information" means all information disclosed by the Disclosing Party, in any form, that is marked confidential or would reasonably be understood to be confidential.
- **Staged Quote**:
  > (none staged)

| Verified (Yes/No) | Advocate Name | Date (YYYY-MM-DD) | Corrected Quote (if any) | Notes |
| :---: | :---: | :---: | :--- | :--- |
| [ ] | | | | |

### 4. `NDA_GOVERNING_LAW_MISSING` (Internal, s. NDA baseline, governing law)
- **Store**: `rules`
- **Severity**: `high` | **Applies To**: nda
- **India Code Verification URL**: [N/A (Internal Baseline)](N/A (Internal Baseline))
- **Rule Logic / Heading**: The NDA does not say which law governs it or which courts hear disputes, so enforcing it starts with a fight over forum and law.
- **Remedy Suggested**: Add a clause: this Agreement is governed by the laws of India, and the courts at [city] have exclusive jurisdiction.
- **Staged Quote**:
  > (none staged)

| Verified (Yes/No) | Advocate Name | Date (YYYY-MM-DD) | Corrected Quote (if any) | Notes |
| :---: | :---: | :---: | :--- | :--- |
| [ ] | | | | |

### 5. `ICA_S27_RESTRAINT_OF_TRADE` (Indian Contract Act, 1872, s. 27)
- **Store**: `rules + seed_statutes`
- **Severity**: `critical` | **Applies To**: nda, employment_contract, consultant_freelancer, non_compete_non_solicit
- **India Code Verification URL**: [https://www.indiacode.nic.in/handle/123456789/2187?view_type=browse&sam_handle=123456789/1362](https://www.indiacode.nic.in/handle/123456789/2187?view_type=browse&sam_handle=123456789/1362)
- **Rule Logic / Heading**: The contract restrains a party from carrying on a business or trade. Under s.27 such a restraint is void unless it falls within the sale-of-goodwill exception.
- **Remedy Suggested**: Remove the restraint, or narrow it to non-solicitation and non-use of Confidential Information, which s.27 does not void.
- **Staged Quote**:
  > Every agreement by which any one is restrained from exercising a lawful profession, trade or business of any kind, is to that extent void.

| Verified (Yes/No) | Advocate Name | Date (YYYY-MM-DD) | Corrected Quote (if any) | Notes |
| :---: | :---: | :---: | :--- | :--- |
| [ ] | | | | |

### 6. `ICA_S28_RESTRAINT_OF_LEGAL_PROCEEDINGS` (Indian Contract Act, 1872, s. 28)
- **Store**: `rules + seed_statutes`
- **Severity**: `high` | **Applies To**: commercial_lease, consultant_freelancer, distributor_dealership, employment_contract, equipment_lease, esop, founders_agreement, intercreditor_hypothecation, jva, leave_and_license, loan_debt, msa, nda, non_compete_non_solicit, partnership_deed, sha, sla, term_sheet_investment, vendor_supplier
- **India Code Verification URL**: [https://www.indiacode.nic.in/handle/123456789/2187?view_type=browse&sam_handle=123456789/1362](https://www.indiacode.nic.in/handle/123456789/2187?view_type=browse&sam_handle=123456789/1362)
- **Rule Logic / Heading**: The contract appears to stop a party from going to court to enforce its rights, or to cut short the time for doing so. Under s.28 such an agreement is void to that extent. An agreement to refer disputes to arbitration is an exception and is not void.
- **Remedy Suggested**: Remove the bar on court proceedings and any shortened deadline for bringing claims, so the normal limitation period applies. If the aim is to keep disputes out of court, use an arbitration clause instead, which s.28 allows.
- **Staged Quote**:
  > s.28: "Every agreement,— (a) by which any party thereto is restricted absolutely from enforcing his rights under or in respect of any contract, by the usual legal proceedings in the ordinary tribunals, or which limits the time within which he may thus enforce his rights; or (b) which extinguishes the rights of any party thereto, or discharges any party thereto, from any liability, under or in respect of any contract on the expiry of a specified period so as to restrict any party from enforcing his rights, is void to that extent." Exception 1: "This section shall not render illegal a contract, by which two or more persons agree that any dispute which may arise between them in respect of any subject or class of subjects shall be referred to arbitration ..."

| Verified (Yes/No) | Advocate Name | Date (YYYY-MM-DD) | Corrected Quote (if any) | Notes |
| :---: | :---: | :---: | :--- | :--- |
| [ ] | | | | |

### 7. `ICA_S74_PENALTY_OR_LIQUIDATED_DAMAGES` (Indian Contract Act, 1872, s. 74)
- **Store**: `rules + seed_statutes`
- **Severity**: `medium` | **Applies To**: commercial_lease, consultant_freelancer, distributor_dealership, employment_contract, equipment_lease, esop, founders_agreement, intercreditor_hypothecation, jva, leave_and_license, loan_debt, msa, nda, non_compete_non_solicit, partnership_deed, sha, sla, term_sheet_investment, vendor_supplier
- **India Code Verification URL**: [https://www.indiacode.nic.in/handle/123456789/2187?view_type=browse&sam_handle=123456789/1362](https://www.indiacode.nic.in/handle/123456789/2187?view_type=browse&sam_handle=123456789/1362)
- **Rule Logic / Heading**: The contract names a sum or a penalty payable on breach. Under s.74 a court awards only reasonable compensation, up to the amount named, so the sum may not be recoverable in full. It needs a reasonableness check.
- **Remedy Suggested**: Check that the named sum is a genuine pre-estimate of the loss a breach would cause, and record how it was worked out. Remove any amount meant to punish rather than compensate.
- **Staged Quote**:
  > s.74: "When a contract has been broken, if a sum is named in the contract as the amount to be paid in case of such breach, or if the contract contains any other stipulation by way of penalty, the party complaining of the breach is entitled, whether or not actual damage or loss is proved to have been caused thereby, to receive from the party who has broken the contract reasonable compensation not exceeding the amount so named or, as the case may be, the penalty stipulated for."

| Verified (Yes/No) | Advocate Name | Date (YYYY-MM-DD) | Corrected Quote (if any) | Notes |
| :---: | :---: | :---: | :--- | :--- |
| [ ] | | | | |

### 8. `STATUTE_COD_S20` (Code of Civil Procedure, 1908, s. 20)
- **Store**: `seed_statutes`
- **Severity**: `high` | **Applies To**: all (jurisdiction baseline)
- **India Code Verification URL**: [https://www.indiacode.nic.in/handle/123456789/2191?view_type=browse&sam_handle=123456789/1362](https://www.indiacode.nic.in/handle/123456789/2191?view_type=browse&sam_handle=123456789/1362)
- **Rule Logic / Heading**: Other suits to be instituted where defendants reside or cause of action arises (Jurisdiction baseline)
- **Remedy Suggested**: Ensure governing law and court submission clauses align with civil procedure jurisdiction limits.
- **Staged Quote**:
  > Subject to the limitations aforesaid, every suit shall be instituted in a Court within the local limits of whose jurisdiction the defendant, or each of the defendants where there are more than one, at the time of the commencement of the suit, actually and voluntarily resides, or carries on business, or personally works for gain; or any of the defendants... or the cause of action, wholly or in part, arises.

| Verified (Yes/No) | Advocate Name | Date (YYYY-MM-DD) | Corrected Quote (if any) | Notes |
| :---: | :---: | :---: | :--- | :--- |
| [ ] | | | | |

---

## Part 2: Required Clauses by Contract Type (4 Types)

### Contract Type: Non-Disclosure Agreement (NDA) (`nda`)
- **Store**: `completeness_config`
- **Current Verification Status**: `unverified`
- **Total Required Clauses**: 8

| Clause Key | Severity | Description / Purpose | Verified Enforceability Baseline |
| :--- | :---: | :--- | :---: |
| `governing-law` | `high` | Standard mandatory clause | [ ] |
| `confidentiality` | `critical` | Standard mandatory clause | [ ] |
| `confidential-info-definition` | `high` | Standard mandatory clause | [ ] |
| `obligations` | `high` | Standard mandatory clause | [ ] |
| `exclusions` | `medium` | Standard mandatory clause | [ ] |
| `term` | `medium` | Standard mandatory clause | [ ] |
| `return-destruction` | `medium` | Standard mandatory clause | [ ] |
| `residuals` | `low` | Standard mandatory clause | [ ] |

### Contract Type: Vendor / Supplier Agreement (`vendor_supplier`)
- **Store**: `completeness_config`
- **Current Verification Status**: `unverified`
- **Total Required Clauses**: 3

| Clause Key | Severity | Description / Purpose | Verified Enforceability Baseline |
| :--- | :---: | :--- | :---: |
| `governing-law` | `high` | Standard mandatory clause | [ ] |
| `confidentiality` | `medium` | Standard mandatory clause | [ ] |
| `term` | `medium` | Standard mandatory clause | [ ] |

### Contract Type: Founders' Agreement (`founders_agreement`)
- **Store**: `completeness_config`
- **Current Verification Status**: `unverified`
- **Total Required Clauses**: 3

| Clause Key | Severity | Description / Purpose | Verified Enforceability Baseline |
| :--- | :---: | :--- | :---: |
| `governing-law` | `high` | Standard mandatory clause | [ ] |
| `confidentiality` | `high` | Standard mandatory clause | [ ] |
| `term` | `medium` | Standard mandatory clause | [ ] |

### Contract Type: Shareholders' Agreement (SHA) (`sha`)
- **Store**: `completeness_config`
- **Current Verification Status**: `unverified`
- **Total Required Clauses**: 3

| Clause Key | Severity | Description / Purpose | Verified Enforceability Baseline |
| :--- | :---: | :--- | :---: |
| `governing-law` | `high` | Standard mandatory clause | [ ] |
| `confidentiality` | `high` | Standard mandatory clause | [ ] |
| `term` | `medium` | Standard mandatory clause | [ ] |

