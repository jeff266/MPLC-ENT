# Phone Mismatch Hard-Reject: Scoped Implementation

**Branch:** `fix/phone-mismatch-rejection`
**Date:** 2026-11-20
**Status:** Awaiting review before merge

---

## Problem

Validation run #3 found that the phone layer (commit b4ce8af) catches **1 of 3 known wrong-store false positives**:

- ✅ Classic Auto Group (OK, 918) → Galveston (TX, 409): Phone mismatch correctly rejected
- ❌ Findlay KIA (UT, 435) → Las Vegas (NV, 702): Phone mismatch **ignored**, name similarity passed it
- ❌ Classic Buick GMC (OH, 440) → Houston (TX, 346): Phone mismatch **ignored**, name similarity passed it

**Root cause**: When phones don't match, the phone layer just falls through to Layer 5 (name similarity). For retail/service locations, different phone numbers = different physical locations. A phone mismatch should be a hard reject.

---

## Why Not a Global Fix

**Question**: Why not just hard-reject all phone mismatches globally?

**Answer**: Not every channel uses phone as the primary identity anchor.

### Examples where global hard-reject would break things:

1. **Image search channels** (Corporate, Healthcare):
   - Use Serper image search → extract business name from image metadata
   - Phone may be present in Salesforce but NOT in image search results
   - A missing phone on the evidence side shouldn't block a valid image match

2. **Website scraping channels** (MDU):
   - Scrape amenity pages for TV evidence
   - Phone extraction from scraped pages is unreliable (contact forms, multiple numbers)
   - Should match on domain/name, not reject due to phone extraction failure

3. **Legacy channels** without phone extraction:
   - Many existing channels don't pass `evidence_phone` at all
   - A global hard-reject would treat "no evidence phone" the same as "wrong phone"
   - This would break existing working channels

### The key distinction:

- **Phone-pinned channels** (web_text): Use phone-first pinning in `_pin_store()` → phone is the PRIMARY identity signal
- **Other channels**: Use image metadata, domain matching, or name-based pinning → phone is SECONDARY or absent

---

## Scoped Solution

Add an **opt-in** parameter `phone_is_primary_pin: bool = False` to `verify_entity_match()`:

### Behavior:

| Condition | phone_is_primary_pin=False (default) | phone_is_primary_pin=True (web_text) |
|-----------|-------------------------------------|--------------------------------------|
| Phones match | ✅ Return high-confidence match | ✅ Return high-confidence match |
| Phones don't match | Fall through to next layer | ❌ **Hard reject** |
| No evidence phone | Fall through to next layer | Fall through to next layer |

### Why this works:

1. **Preserves existing behavior**: All existing channels (image search, website scraping) continue working unchanged (default `False`)
2. **Fixes phone-pinned channels**: web_text explicitly sets `phone_is_primary_pin=True` because it uses phone-first pinning
3. **Signals intent**: The parameter name makes it clear WHY the rejection happens (not just "phones available but different")

---

## Implementation

### Changes:

1. **entity_verification.py**:
   - Add `phone_is_primary_pin: bool = False` parameter
   - When phones don't match AND `phone_is_primary_pin=True`: return hard reject with `layer: 'phone_mismatch'`
   - Otherwise: fall through to next layer (unchanged behavior)

2. **web_text_channel.py**:
   - Pass `phone_is_primary_pin=True` when calling `verify_entity_match()`
   - Rationale: web_text uses phone-first pinning in `_pin_store()` (line 165-173)

### Lines changed:

- entity_verification.py: +19 lines (new parameter, docstring, mismatch logic)
- web_text_channel.py: +1 line (pass new parameter)

---

## Expected Impact

**Before** (validation run #3):
- Findlay KIA: Phone mismatch (435 vs 702) → fell through to name similarity → **PROSPECT** ❌
- Classic Buick GMC: Phone mismatch (440 vs 346) → fell through to name similarity → **PROSPECT** ❌

**After** (with this fix):
- Findlay KIA: Phone mismatch (435 vs 702) → hard reject → **REJECTED or SUSPECT** ✅
- Classic Buick GMC: Phone mismatch (440 vs 346) → hard reject → **REJECTED or SUSPECT** ✅

**Success criteria**: Both accounts should return REJECTED or SUSPECT tier (not PROSPECT) when tested against this branch.

---

## Review Items

1. **Scoping rationale**: Does the opt-in approach (default False) correctly preserve existing channel behavior?
2. **Parameter naming**: Is `phone_is_primary_pin` clear enough about when to use it?
3. **Edge cases**: What happens if only one phone is present? (Answer: falls through, as intended)
4. **Other callers**: Should any other channels set `phone_is_primary_pin=True`? (Likely not yet, but future phone-pinned channels could)

---

## Next Steps

1. **Review this diff** before merging to main
2. **Test on Findlay KIA + Classic Buick GMC** to confirm both now reject/suspect
3. **Re-run full 20-account validation** to ensure no regressions
4. **Document in entity_verification.py docstring** when to use `phone_is_primary_pin=True`
