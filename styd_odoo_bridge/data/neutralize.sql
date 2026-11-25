-- A neutralized copy of this database (odoo-bin neutralize, or a duplicate
-- marked as a test copy) is never paired with Speak To Your Database: every
-- pairing is unpaired and its secrets are cleared. Pair the copy again if needed.
UPDATE styd_odoo_bridge_pairing
   SET state = 'revoked',
       secret = NULL,
       pending_secret = NULL,
       pending_rotation_id = NULL,
       previous_secret = NULL,
       previous_secret_until = NULL,
       pair_attempt = NULL,
       approved_at = NULL,
       revoked_at = NOW() AT TIME ZONE 'UTC',
       revoked_reason = 'neutralized',
       status_code = 'revoked',
       status_since = NOW() AT TIME ZONE 'UTC'
 WHERE state != 'revoked' OR secret IS NOT NULL OR pending_secret IS NOT NULL OR previous_secret IS NOT NULL;
