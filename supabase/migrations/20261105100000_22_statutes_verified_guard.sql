-- 22: statutes verified guard trigger (R8 #3 / Audit hardening)
-- Resets verified statutes to 'staging' and clears verification evidence whenever
-- substantive quote or citation fields are edited without providing re-certified evidence
-- (including a mandatory distinct verification_ref), and guards direct INSERTs.
--
-- Manual verification test (execute in transaction):
-- BEGIN;
--   -- Case 1: Direct INSERT as 'verified' without complete evidence -> demotes to 'staging'
--   INSERT INTO public.statutes (act, section, statute_text, effective_from, status)
--   VALUES ('Test Guard Act, 2026', '0', 'Direct insert without evidence', '2026-01-01', 'verified');
--   SELECT status = 'staging' AND verified_by IS NULL AND verification_ref IS NULL AS test_1_passed
--   FROM public.statutes WHERE act = 'Test Guard Act, 2026' AND section = '0';
--
--   -- Case 2: INSERT with complete evidence triple -> accepted as 'verified'
--   INSERT INTO public.statutes (act, section, statute_text, effective_from, status, verified_by, verified_at, verification_ref)
--   VALUES ('Test Guard Act, 2026', '1', 'Original statutory text', '2026-01-01', 'verified', 'Adv. Sharma', now(), 'https://www.indiacode.nic.in/ref1');
--   SELECT status = 'verified' AND verified_by = 'Adv. Sharma' AS test_2_passed
--   FROM public.statutes WHERE act = 'Test Guard Act, 2026' AND section = '1';
--
--   -- Case 3: Quote edited without new verification_ref (even if verified_at changes) -> demotes to 'staging'
--   UPDATE public.statutes
--   SET statute_text = 'Modified quote text', verified_at = now()
--   WHERE act = 'Test Guard Act, 2026' AND section = '1';
--   SELECT status = 'staging' AND verified_by IS NULL AND verified_at IS NULL AND verification_ref IS NULL AS test_3_passed
--   FROM public.statutes WHERE act = 'Test Guard Act, 2026' AND section = '1';
--
--   -- Case 4: Quote edited WITH complete new evidence including NEW verification_ref -> remains 'verified'
--   UPDATE public.statutes
--   SET statute_text = 'Re-verified quote text',
--       status = 'verified',
--       verified_by = 'Adv. Patel',
--       verified_at = now(),
--       verification_ref = 'https://www.indiacode.nic.in/ref2'
--   WHERE act = 'Test Guard Act, 2026' AND section = '1';
--   SELECT status = 'verified' AND verified_by = 'Adv. Patel' AND verification_ref = 'https://www.indiacode.nic.in/ref2' AS test_4_passed
--   FROM public.statutes WHERE act = 'Test Guard Act, 2026' AND section = '1';
-- ROLLBACK;

CREATE OR REPLACE FUNCTION public.statutes_guard_verified_edits()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
  substantive_change boolean;
  new_evidence_provided boolean;
BEGIN
  -- 1. INSERT Guard: A row cannot be inserted directly as 'verified' without complete verification evidence
  IF TG_OP = 'INSERT' THEN
    IF NEW.status = 'verified' AND (
      NEW.verified_by IS NULL
      OR NEW.verified_at IS NULL
      OR NEW.verification_ref IS NULL
    ) THEN
      NEW.status := 'staging';
      NEW.verified_by := NULL;
      NEW.verified_at := NULL;
      NEW.verification_ref := NULL;
    END IF;
    RETURN NEW;
  END IF;

  -- 2. UPDATE Guard: Substantive statutory fields: statute_text, act, section, effective_from, effective_to
  substantive_change := (
    NEW.statute_text IS DISTINCT FROM OLD.statute_text
    OR NEW.act IS DISTINCT FROM OLD.act
    OR NEW.section IS DISTINCT FROM OLD.section
    OR NEW.effective_from IS DISTINCT FROM OLD.effective_from
    OR NEW.effective_to IS DISTINCT FROM OLD.effective_to
  );

  -- If old row was 'verified' and substantive statutory content was edited:
  IF OLD.status = 'verified' AND substantive_change THEN
    -- Check if UPDATE provides a new complete evidence triple WITH a distinct new verification_ref.
    -- Changing verified_at alone or verified_by alone without a new verification_ref is strictly rejected.
    new_evidence_provided := (
      NEW.status = 'verified'
      AND NEW.verified_by IS NOT NULL
      AND NEW.verified_at IS NOT NULL
      AND NEW.verification_ref IS NOT NULL
      AND NEW.verification_ref IS DISTINCT FROM OLD.verification_ref
    );

    IF NOT new_evidence_provided THEN
      -- Demote back to staging and clear stale evidence
      NEW.status := 'staging';
      NEW.verified_by := NULL;
      NEW.verified_at := NULL;
      NEW.verification_ref := NULL;
    END IF;
  END IF;

  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS statutes_verified_guard ON public.statutes;
CREATE TRIGGER statutes_verified_guard
BEFORE INSERT OR UPDATE ON public.statutes
FOR EACH ROW EXECUTE FUNCTION public.statutes_guard_verified_edits();
