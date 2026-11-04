# Advocate Review Pack (R3 Completeness & R5 Seed Rules)

> [!IMPORTANT]
> **For Verifying Advocate / Legal Counsel**:
> This review pack is compiled automatically from the AgentClause repository configurations and rule files.
> In accordance with platform governance, production strict mode returns zero findings on unverified rules until
> a licensed Indian advocate verifies these quotes against authoritative sources (India Code) and confirms the required clauses.

## Review Instructions
1. **Statutory Quotes (R5)**: Open each India Code URL and check whether the staged quote matches the operative statutory text word-for-word. Note any corrections.
2. **Required Clause Lists (R3)**: Confirm that the mandatory clause lists reflect standard practice and legal enforceability under Indian law.
3. **Sign-off**: Mark verified rows in `docs/advocate_review_pack.csv` with `verified` = `yes` and provide your name, Bar Council enrollment number, and date.

---

## Part 1: Statutory Seed Rules (7 Rules)

### 1. Rule `MSMED_S15_PAYMENT_BEYOND_45_DAYS`
- **Statute & Section**: Micro, Small and Medium Enterprises Development Act, 2006, s. 15
- **Severity**: `high` | **Applies To**: msa, sla, vendor_supplier
- **India Code Verification URL**: [https://www.indiacode.nic.in/handle/123456789/2013?view_type=browse&sam_handle=123456789/1362](https://www.indiacode.nic.in/handle/123456789/2013?view_type=browse&sam_handle=123456789/1362)
- **Rule Logic**: The contract allows payment more than 45 days after the goods or services are delivered. If the supplier is a micro or small enterprise, s.15 caps the agreed payment period at 45 days from acceptance, whatever the contract says.
- **Remedy Suggested**: Shorten the payment period to 45 days or less from acceptance of the goods or services. First check whether the supplier is registered as a micro or small enterprise (Udyam registration): the cap only protects those suppliers.
- **Staged Quote**:
  > s.15: "Where any supplier supplies any goods or renders any services to any buyer, the buyer shall make payment therefor on or before the date agreed upon between him and the supplier in writing or, where there is no agreement in this behalf, before the appointed day: Provided that in no case the period agreed upon between the supplier and the buyer in writing shall exceed forty-five days from the day of acceptance or the day of deemed acceptance."

| Verified (Yes/No) | Corrected Quote (if any) | Advocate Notes |
| :---: | :--- | :--- |
| [ ] | | |

### 2. Rule `MSMED_S16_INTEREST_WAIVER`
- **Statute & Section**: Micro, Small and Medium Enterprises Development Act, 2006, s. 16
- **Severity**: `high` | **Applies To**: msa, sla, vendor_supplier
- **India Code Verification URL**: [https://www.indiacode.nic.in/handle/123456789/2013?view_type=browse&sam_handle=123456789/1362](https://www.indiacode.nic.in/handle/123456789/2013?view_type=browse&sam_handle=123456789/1362)
- **Rule Logic**: The contract waives or limits interest on late payment. If the supplier is a micro or small enterprise, s.16 makes a buyer who pays late liable for compound interest at three times the RBI bank rate, notwithstanding anything in the agreement, so this clause cannot take that right away.
- **Remedy Suggested**: Remove the waiver or cap on late-payment interest. Either say nothing, or state that interest on late payment is payable as provided in section 16 of the MSMED Act. First check whether the supplier is a registered micro or small enterprise.
- **Staged Quote**:
  > s.16: "Where any buyer fails to make payment of the amount to the supplier, as required under section 15, the buyer shall, notwithstanding anything contained in any agreement between the buyer and the supplier or in any law for the time being in force, be liable to pay compound interest with monthly rests to the supplier on that amount from the appointed day or, as the case may be, from the date immediately following the date agreed upon, at three times of the bank rate notified by the Reserve Bank."

| Verified (Yes/No) | Corrected Quote (if any) | Advocate Notes |
| :---: | :--- | :--- |
| [ ] | | |

### 3. Rule `NDA_CONFIDENTIAL_INFO_DEFINITION_MISSING`
- **Statute & Section**: Internal, s. NDA baseline, definition of Confidential Information
- **Severity**: `high` | **Applies To**: nda
- **India Code Verification URL**: [N/A (Internal Baseline)](N/A (Internal Baseline))
- **Rule Logic**: The NDA never defines "Confidential Information", so it is unclear what the obligations protect.
- **Remedy Suggested**: Add a definition: "Confidential Information" means all information disclosed by the Disclosing Party, in any form, that is marked confidential or would reasonably be understood to be confidential.
- **Staged Quote**:
  > (none staged)

| Verified (Yes/No) | Corrected Quote (if any) | Advocate Notes |
| :---: | :--- | :--- |
| [ ] | | |

### 4. Rule `NDA_GOVERNING_LAW_MISSING`
- **Statute & Section**: Internal, s. NDA baseline, governing law
- **Severity**: `high` | **Applies To**: nda
- **India Code Verification URL**: [N/A (Internal Baseline)](N/A (Internal Baseline))
- **Rule Logic**: The NDA does not say which law governs it or which courts hear disputes, so enforcing it starts with a fight over forum and law.
- **Remedy Suggested**: Add a clause: this Agreement is governed by the laws of India, and the courts at [city] have exclusive jurisdiction.
- **Staged Quote**:
  > (none staged)

| Verified (Yes/No) | Corrected Quote (if any) | Advocate Notes |
| :---: | :--- | :--- |
| [ ] | | |

### 5. Rule `ICA_S27_RESTRAINT_OF_TRADE`
- **Statute & Section**: Indian Contract Act, 1872, s. 27
- **Severity**: `critical` | **Applies To**: nda, employment_contract, consultant_freelancer, non_compete_non_solicit
- **India Code Verification URL**: [https://www.indiacode.nic.in/handle/123456789/2187?view_type=browse&sam_handle=123456789/1362](https://www.indiacode.nic.in/handle/123456789/2187?view_type=browse&sam_handle=123456789/1362)
- **Rule Logic**: The contract restrains a party from carrying on a business or trade. Under s.27 such a restraint is void unless it falls within the sale-of-goodwill exception.
- **Remedy Suggested**: Remove the restraint, or narrow it to non-solicitation and non-use of Confidential Information, which s.27 does not void.
- **Staged Quote**:
  > (none staged)

| Verified (Yes/No) | Corrected Quote (if any) | Advocate Notes |
| :---: | :--- | :--- |
| [ ] | | |

### 6. Rule `ICA_S28_RESTRAINT_OF_LEGAL_PROCEEDINGS`
- **Statute & Section**: Indian Contract Act, 1872, s. 28
- **Severity**: `high` | **Applies To**: commercial_lease, consultant_freelancer, distributor_dealership, employment_contract, equipment_lease, esop, founders_agreement, intercreditor_hypothecation, jva, leave_and_license, loan_debt, msa, nda, non_compete_non_solicit, partnership_deed, sha, sla, term_sheet_investment, vendor_supplier
- **India Code Verification URL**: [https://www.indiacode.nic.in/handle/123456789/2187?view_type=browse&sam_handle=123456789/1362](https://www.indiacode.nic.in/handle/123456789/2187?view_type=browse&sam_handle=123456789/1362)
- **Rule Logic**: The contract appears to stop a party from going to court to enforce its rights, or to cut short the time for doing so. Under s.28 such an agreement is void to that extent. An agreement to refer disputes to arbitration is an exception and is not void.
- **Remedy Suggested**: Remove the bar on court proceedings and any shortened deadline for bringing claims, so the normal limitation period applies. If the aim is to keep disputes out of court, use an arbitration clause instead, which s.28 allows.
- **Staged Quote**:
  > s.28: "Every agreement,— (a) by which any party thereto is restricted absolutely from enforcing his rights under or in respect of any contract, by the usual legal proceedings in the ordinary tribunals, or which limits the time within which he may thus enforce his rights; or (b) which extinguishes the rights of any party thereto, or discharges any party thereto, from any liability, under or in respect of any contract on the expiry of a specified period so as to restrict any party from enforcing his rights, is void to that extent." Exception 1: "This section shall not render illegal a contract, by which two or more persons agree that any dispute which may arise between them in respect of any subject or class of subjects shall be referred to arbitration ..."

| Verified (Yes/No) | Corrected Quote (if any) | Advocate Notes |
| :---: | :--- | :--- |
| [ ] | | |

### 7. Rule `ICA_S74_PENALTY_OR_LIQUIDATED_DAMAGES`
- **Statute & Section**: Indian Contract Act, 1872, s. 74
- **Severity**: `medium` | **Applies To**: commercial_lease, consultant_freelancer, distributor_dealership, employment_contract, equipment_lease, esop, founders_agreement, intercreditor_hypothecation, jva, leave_and_license, loan_debt, msa, nda, non_compete_non_solicit, partnership_deed, sha, sla, term_sheet_investment, vendor_supplier
- **India Code Verification URL**: [https://www.indiacode.nic.in/handle/123456789/2187?view_type=browse&sam_handle=123456789/1362](https://www.indiacode.nic.in/handle/123456789/2187?view_type=browse&sam_handle=123456789/1362)
- **Rule Logic**: The contract names a sum or a penalty payable on breach. Under s.74 a court awards only reasonable compensation, up to the amount named, so the sum may not be recoverable in full. It needs a reasonableness check.
- **Remedy Suggested**: Check that the named sum is a genuine pre-estimate of the loss a breach would cause, and record how it was worked out. Remove any amount meant to punish rather than compensate.
- **Staged Quote**:
  > s.74: "When a contract has been broken, if a sum is named in the contract as the amount to be paid in case of such breach, or if the contract contains any other stipulation by way of penalty, the party complaining of the breach is entitled, whether or not actual damage or loss is proved to have been caused thereby, to receive from the party who has broken the contract reasonable compensation not exceeding the amount so named or, as the case may be, the penalty stipulated for."

| Verified (Yes/No) | Corrected Quote (if any) | Advocate Notes |
| :---: | :--- | :--- |
| [ ] | | |

---

## Part 2: Required Clauses by Contract Type (4 Types)

### Contract Type: Non-Disclosure Agreement (NDA) (`nda`)
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
- **Current Verification Status**: `unverified`
- **Total Required Clauses**: 3

| Clause Key | Severity | Description / Purpose | Verified Enforceability Baseline |
| :--- | :---: | :--- | :---: |
| `governing-law` | `high` | Standard mandatory clause | [ ] |
| `confidentiality` | `medium` | Standard mandatory clause | [ ] |
| `term` | `medium` | Standard mandatory clause | [ ] |

### Contract Type: Founders' Agreement (`founders_agreement`)
- **Current Verification Status**: `unverified`
- **Total Required Clauses**: 3

| Clause Key | Severity | Description / Purpose | Verified Enforceability Baseline |
| :--- | :---: | :--- | :---: |
| `governing-law` | `high` | Standard mandatory clause | [ ] |
| `confidentiality` | `high` | Standard mandatory clause | [ ] |
| `term` | `medium` | Standard mandatory clause | [ ] |

### Contract Type: Shareholders' Agreement (SHA) (`sha`)
- **Current Verification Status**: `unverified`
- **Total Required Clauses**: 3

| Clause Key | Severity | Description / Purpose | Verified Enforceability Baseline |
| :--- | :---: | :--- | :---: |
| `governing-law` | `high` | Standard mandatory clause | [ ] |
| `confidentiality` | `high` | Standard mandatory clause | [ ] |
| `term` | `medium` | Standard mandatory clause | [ ] |

