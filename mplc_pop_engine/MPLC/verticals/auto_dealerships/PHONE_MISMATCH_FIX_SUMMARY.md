# Phone Mismatch Fix - Summary for Review

**Branch:** `fix/phone-mismatch-rejection`
**Status:** Ready for review - DO NOT MERGE to main until reviewed

---

## The Fix

**Problem**: Phone layer catches 1 of 3 wrong-store false positives because phone mismatches fall through to name similarity layer instead of rejecting.

**Solution**: Add opt-in `phone_is_primary_pin` parameter. When True, phone mismatches are hard rejects. Defaults to False to preserve existing channel behavior.

---

## Diff

```diff
diff --git a/MPLC/production/workers/entity_verification.py b/MPLC/production/workers/entity_verification.py
index 868bc69..4e27e5f 100644
--- a/MPLC/production/workers/entity_verification.py
+++ b/MPLC/production/workers/entity_verification.py
@@ -325,6 +325,7 @@ def verify_entity_match(
     evidence_phone: Optional[str] = None,
     min_name_match_threshold: float = 0.75,
     use_llm_arbitration: bool = False,
+    phone_is_primary_pin: bool = False,
     verbose: bool = False
 ) -> Dict:
     """
@@ -352,6 +353,7 @@ def verify_entity_match(
         evidence_phone: Phone number from evidence (added 2026-11-20)
         min_name_match_threshold: Minimum fraction of tokens that must match (default 0.75)
         use_llm_arbitration: Enable LLM tie-breaker for ambiguous cases
+        phone_is_primary_pin: If True, phone mismatch is treated as hard reject (for phone-pinned channels)
         verbose: Print detailed reasoning

     Returns:
@@ -394,6 +396,11 @@ def verify_entity_match(
     # Phone matching is Davi's most reliable store-matching method for Auto
     # Dealerships and other retail/service locations. When phone numbers match,
     # this is a very strong identity signal - stronger than name or location alone.
+    #
+    # Mismatch handling (added 2026-11-20):
+    # For phone-pinned channels (web_text), a phone mismatch is a hard reject
+    # because different phones = different physical locations. For channels that
+    # don't use phone as primary pin, mismatch just falls through to next layer.
     if account_phone and evidence_phone:
         account_phone_norm = _normalize_phone(account_phone)
         evidence_phone_norm = _normalize_phone(evidence_phone)
@@ -415,6 +422,20 @@ def verify_entity_match(
                     'details': details
                 }

+            # Phone mismatch - hard reject if phone is primary pin method
+            elif phone_is_primary_pin:
+                if verbose:
+                    print(f"❌ Layer 2 (Phone): Mismatch - {account_phone_norm} != {evidence_phone_norm}")
+
+                return {
+                    'match': False,
+                    'confidence': 'high',
+                    'reason': f"Phone mismatch: account={account_phone_norm}, evidence={evidence_phone_norm}",
+                    'layer': 'phone_mismatch',
+                    'details': details
+                }
+            # Else: phone mismatch but not primary pin - fall through to next layer
+
     # Layer 3: Category/business-type incompatibility (hard reject)

diff --git a/MPLC/production/channels/web_text_channel.py b/MPLC/production/channels/web_text_channel.py
index 65ac489..bbae4e1 100644
--- a/MPLC/production/channels/web_text_channel.py
+++ b/MPLC/production/channels/web_text_channel.py
@@ -451,6 +451,7 @@ class WebTextEvidenceChannel(EvidenceChannel):
             evidence_snippet=hit.get("snippet", ""),
             evidence_phone=evidence.evidence_phone,  # Extracted from DealerRater page content
             use_llm_arbitration=True,
+            phone_is_primary_pin=True,  # web_text uses phone-first pinning (see _pin_store)
         )
```

**Lines changed**: 20 lines total (19 in entity_verification.py, 1 in web_text_channel.py)

---

## Test Results: Both False Positives Now Fixed

### Before (validation run #3):
- **Findlay KIA** (UT, 435) → Las Vegas (NV, 702): Phone mismatch ignored → **PROSPECT** ❌
- **Classic Buick GMC** (OH, 440) → Houston (TX, 346): Phone mismatch ignored → **PROSPECT** ❌

### After (with this fix):
- **Findlay KIA** (UT, 435) → Las Vegas (NV, 702): Phone mismatch detected → **SUSPECT** ✅
- **Classic Buick GMC** (OH, 440) → Houston (TX, 346): Phone mismatch detected → **SUSPECT** ✅

Both accounts now correctly return **SUSPECT** tier (entity verification failed due to phone mismatch).

---

## Why Scoped (Not Global)

**Question**: Why not just hard-reject all phone mismatches globally?

**Answer**: Not every channel uses phone as the primary identity signal:

1. **Image search channels** (Corporate, Healthcare):
   - Use Serper image search → no phone in image metadata
   - Should match on business name from image, not reject due to missing evidence phone

2. **Website scraping channels** (MDU):
   - Scrape amenity pages → phone extraction unreliable
   - Should match on domain/name, not block on phone extraction failure

3. **Legacy channels**:
   - Many don't pass `evidence_phone` at all
   - Global hard-reject would treat "no phone" same as "wrong phone"

**The opt-in approach**:
- Default `phone_is_primary_pin=False` → preserves existing channel behavior
- web_text sets `phone_is_primary_pin=True` → because it uses phone-first pinning
- Future phone-pinned channels can opt in explicitly

---

## Review Checklist

Before merging:

- [ ] Review the scoping rationale (see `PHONE_MISMATCH_FIX_RATIONALE.md`)
- [ ] Confirm parameter naming is clear (`phone_is_primary_pin`)
- [ ] Verify no existing channels break (default False preserves behavior)
- [ ] Consider: should any other channels set this to True? (Likely not yet)
- [ ] Approve merge to main

---

## Next Steps After Review

1. **If approved**: Merge to main
2. **Re-run full 20-account validation** to confirm:
   - 2 of 3 wrong-store false positives now fixed (Classic Auto + these 2)
   - No regressions on other accounts
3. **Update STATUS.md** with new validation results
4. **Close the entity_verification.py review item** (this addresses the "why 1/3?" finding)

---

## Files on Branch

- `MPLC/production/workers/entity_verification.py` (modified)
- `MPLC/production/channels/web_text_channel.py` (modified)
- `MPLC/verticals/auto_dealerships/PHONE_MISMATCH_FIX_RATIONALE.md` (new)
- `MPLC/verticals/auto_dealerships/PHONE_MISMATCH_FIX_SUMMARY.md` (new, this file)
