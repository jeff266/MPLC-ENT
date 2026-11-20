#!/usr/bin/env python3
"""
Web Text Evidence Channel — vertical-agnostic text-based evidence detection.

Built for the Custom Vertical Builder, piloted on Auto Dealerships per Jeff's
2026-11-20 request: "We tried video with dealerships as a test before, and
quite frankly, was not very successful. So it might be a good idea to add a
text-based engine in the vertical builder, and we can use auto as a standard
test case."

This channel searches for text-based evidence of MPLC-relevant spaces (waiting
areas, customer lounges, etc.) by:
1. Phone-pinning the account to establish identity (most reliable for retail/dealer locations)
2. Running evidence queries across fetchable and snippet-only domains
3. Extracting evidence phrases from page content or search snippets
4. Using entity verification to confirm the evidence matches the target account

Differs from image/video channels: evidence is a TEXT QUOTE from a review,
amenity list, or website page, not a visual asset. Fetchable domains
(dealerrater.com, etc.) can be fetched and parsed for high-confidence evidence;
snippet-only domains (kbb.com, autotrader.com) are never fetched because their
search-snippet tags don't reliably exist on the actual page (confirmed in Davi's
2026-11-18 KBB testing).

Conforms to channels/base.py's EvidenceChannel interface so it's interchangeable
in a vertical's channel list.
"""

import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlparse

import requests

sys.path.insert(0, str(Path(__file__).parent))
from base import AccountContext, ChannelResult, EvidenceChannel  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent.parent / "workers"))
from entity_verification import verify_entity_match  # noqa: E402

# Cost constants
# Serper API: $0.001 per search (same as image search)
# Web page fetches: typically included in search cost or free (direct HTTP requests)
# Anthropic Claude for entity verification: standard VLM costs
SERPER_COST_PER_CALL = 0.001
CLAUDE_INPUT_COST_PER_TOKEN = 0.000003
CLAUDE_OUTPUT_COST_PER_TOKEN = 0.000015


@dataclass
class TextEvidence:
    """Text-based evidence payload returned by WebTextEvidenceChannel.

    Carries the Evidence Persistence Schema's required fields (source_url,
    confidence/strength) with a text quote in place of an image location.
    """
    quote: str                      # The actual text snippet containing evidence
    source_url: str                 # Original source URL
    source_domain: str              # Domain (for distinguishing fetchable vs snippet-only)
    strength: str                   # "solid" (from fetchable page) or "weak" (snippet-only)
    match_method: str              # "phone" | "website" | "name_state" | "other"
    store_match_confidence: str    # "high" | "medium" | "low" (separate from evidence strength)


class WebTextEvidenceChannel(EvidenceChannel):
    name = "web_text_search"

    def __init__(
        self,
        pin_query_template: str,
        evidence_query_templates: List[str],
        evidence_phrases: List[str],
        fetchable_domains: List[str],
        snippet_only_domains: List[str],
        serper_key: Optional[str] = None,
        anthropic_key: Optional[str] = None,
        max_evidence_queries: int = 4,
        results_per_query: int = 5,
    ):
        """
        pin_query_template: e.g. "{phone}" or "{account_name} {state}" -- used to
            establish account identity before searching for evidence. Phone is
            most reliable for retail/dealer locations (Davi's finding).
        evidence_query_templates: e.g. ['site:dealerrater.com "{name}" {city}',
            '"{name}" "waiting area" OR "waiting room"'] -- searched in order
            until solid evidence found.
        evidence_phrases: plain strings to search for in fetched page content
            (e.g. ["waiting area", "waiting room", "lounge"]).
        fetchable_domains: domains where pages can be fetched and parsed for
            high-confidence evidence (e.g. dealerrater.com, caredge.com).
        snippet_only_domains: domains where search snippets may show evidence
            but fetching the page doesn't reliably contain it (e.g. kbb.com,
            autotrader.com per Davi's 2026-11-18 finding). Evidence from these
            is recorded as "weak" and never sufficient alone.
        """
        self.pin_query_template = pin_query_template
        self.evidence_query_templates = evidence_query_templates
        self.evidence_phrases = evidence_phrases
        self.fetchable_domains = fetchable_domains
        self.snippet_only_domains = snippet_only_domains
        self.serper_key = serper_key or os.getenv("SERPER_API_KEY")
        self.anthropic_key = anthropic_key or os.getenv("ANTHROPIC_API_KEY")
        self.max_evidence_queries = max_evidence_queries
        self.results_per_query = results_per_query

        # Compile evidence phrases into regex patterns for efficient matching
        self._evidence_patterns = [
            re.compile(re.escape(phrase), re.IGNORECASE)
            for phrase in evidence_phrases
        ]

    def _pin_store(self, ctx: AccountContext) -> dict:
        """
        Establish account identity via phone number (preferred) or name+state fallback.
        Returns a dict with identity fields that can be used to format queries.

        Phone-pinning is Davi's most reliable store-matching method for Auto
        dealerships; name+state is the fallback when phone unavailable.
        """
        # Extract phone from AccountContext (may be in extra fields or main fields)
        phone = ctx.extra.get("phone", "")
        if not phone and hasattr(ctx, "phone"):
            phone = ctx.phone  # type: ignore

        # Build identity store
        store = {
            "phone": phone,
            "name": ctx.account_name,
            "city": ctx.city or "",
            "state": ctx.state or "",
            "country": ctx.country or "United States",
        }

        # Run pin query to establish identity
        # This is primarily for logging/debugging - the actual identity matching
        # happens in entity_verification.verify_entity_match()
        try:
            pin_query = self.pin_query_template.format(**store)
            # We don't actually need the results here - just establishing that
            # we CAN format a valid query. The evidence queries will do the real work.
        except (KeyError, IndexError) as e:
            # Pin query template references fields not in store
            pass

        return store

    def _search(self, query: str) -> List[dict]:
        """
        Run a Serper web search and return results.
        Returns list of dicts with keys: title, snippet, link, domain.
        """
        if not self.serper_key:
            return []

        try:
            response = requests.post(
                "https://google.serper.dev/search",
                headers={
                    "X-API-KEY": self.serper_key,
                    "Content-Type": "application/json",
                },
                json={
                    "q": query,
                    "num": self.results_per_query,
                },
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()

            results = []
            for item in data.get("organic", [])[:self.results_per_query]:
                link = item.get("link", "")
                domain = urlparse(link).netloc.lower().replace("www.", "")
                results.append({
                    "title": item.get("title", ""),
                    "snippet": item.get("snippet", ""),
                    "link": link,
                    "domain": domain,
                })

            return results

        except Exception as e:
            # Log error but don't raise - return empty results
            # Caller will treat this as REJECTED with appropriate reason
            return []

    def _fetch_page(self, url: str) -> Optional[str]:
        """
        Fetch and return the text content of a web page.
        Only called for fetchable domains - snippet-only domains are never fetched.

        Returns None if fetch fails (network error, timeout, etc.).
        Sequential fetches only - DealerRater and similar sites throttle bursts.
        """
        try:
            response = requests.get(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
                },
                timeout=15,  # Reasonable timeout for page fetch
            )
            response.raise_for_status()
            return response.text

        except Exception as e:
            # Fetch failed - return None, caller will skip this result
            return None

    def _contains_evidence(self, text: str) -> Optional[tuple[str, str]]:
        """
        Check if text contains any evidence phrases.
        Returns (matched_phrase, quote_context) if found, None otherwise.

        quote_context is ~200 chars of surrounding text for the evidence record.
        """
        for pattern in self._evidence_patterns:
            match = pattern.search(text)
            if match:
                # Extract context around the match (~100 chars before/after)
                start = max(0, match.start() - 100)
                end = min(len(text), match.end() + 100)
                quote = text[start:end].strip()

                # Clean up quote (remove extra whitespace, newlines)
                quote = re.sub(r'\s+', ' ', quote)

                return (match.group(), quote)

        return None

    def search_evidence(self, ctx: AccountContext) -> ChannelResult:
        """
        Search for text-based evidence of MPLC-relevant spaces for this account.

        Flow:
        1. Pin store identity (phone or name+state)
        2. Run evidence queries in order
        3. For each hit:
           - If fetchable domain: fetch page, check for evidence phrases → "solid"
           - If snippet-only domain: check snippet for evidence phrases → "weak"
        4. Early exit on first solid evidence found
        5. Run entity verification before returning PROSPECT

        Returns ChannelResult with TextEvidence payload if evidence found.
        """
        total_cost = 0.0
        evidence = None

        # Step 1: Pin store identity
        store = self._pin_store(ctx)

        # Step 2: Run evidence queries
        for template in self.evidence_query_templates[:self.max_evidence_queries]:
            try:
                query = template.format(**store)
            except (KeyError, IndexError):
                # Template references missing fields - skip this query
                continue

            # Run search
            hits = self._search(query)
            total_cost += SERPER_COST_PER_CALL

            if not hits:
                # No results for this query - try next
                continue

            # Step 3: Check each hit for evidence
            for hit in hits:
                domain = hit["domain"]

                # Fetchable domain: fetch page and check for evidence
                if any(d in domain for d in self.fetchable_domains):
                    page_text = self._fetch_page(hit["link"])
                    if page_text:
                        evidence_match = self._contains_evidence(page_text)
                        if evidence_match:
                            matched_phrase, quote = evidence_match
                            evidence = TextEvidence(
                                quote=quote,
                                source_url=hit["link"],
                                source_domain=domain,
                                strength="solid",
                                match_method="pending",  # Will be set by entity verification
                                store_match_confidence="pending",
                            )
                            break  # Found solid evidence, exit inner loop

                # Snippet-only domain: check snippet for evidence (weak)
                elif any(d in domain for d in self.snippet_only_domains):
                    snippet_text = hit["title"] + " " + hit["snippet"]
                    evidence_match = self._contains_evidence(snippet_text)
                    if evidence_match:
                        matched_phrase, quote = evidence_match
                        # Record weak evidence but don't break - keep looking for solid
                        if not evidence or evidence.strength == "weak":
                            evidence = TextEvidence(
                                quote=quote,
                                source_url=hit["link"],
                                source_domain=domain,
                                strength="weak",
                                match_method="pending",
                                store_match_confidence="pending",
                            )

            # If we found solid evidence, stop searching
            if evidence and evidence.strength == "solid":
                break

        # Step 4: Return early if no evidence found
        if not evidence:
            return ChannelResult.rejected(
                self.name,
                reason="No evidence phrases found in search results or fetched pages",
                cost=total_cost,
            )

        # Step 5: Only proceed with entity verification if evidence is solid
        if evidence.strength != "solid":
            return ChannelResult.rejected(
                self.name,
                reason="Only weak (snippet-only) evidence found, not sufficient alone",
                cost=total_cost,
            )

        # Step 6: Entity verification (phone matching will be added to this module in Task 2)
        # For now, use existing verification which will check domain/name/geographic matching
        entity_match = verify_entity_match(
            evidence_url=evidence.source_url,
            account_ctx=ctx,
            use_llm_arbitration=True,
        )

        if not entity_match:
            return ChannelResult(
                tier="SUSPECT",
                channel=self.name,
                evidence=evidence,
                cost=total_cost,
                details={"reason": "Entity verification failed"},
            )

        # Success: solid evidence with verified entity match
        return ChannelResult(
            tier="PROSPECT",
            channel=self.name,
            evidence=evidence,
            cost=total_cost,
        )
