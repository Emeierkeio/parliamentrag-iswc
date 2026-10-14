"""4-stage generation pipeline orchestrator.

Stage 1 (analyst) decomposes the query into claims, stage 2 (sectional
writer) writes per-party sections, stage 3 (integrator) merges them into a
coherent narrative, stage 4 (surgeon) resolves verbatim citations. A
citation registry, a coherence validator and an integrator guard track
citations through the stages and verify that all of them are resolved.
"""
import re
import time
import asyncio
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime

from .analyst import ClaimAnalyst
from .sectional import SectionalWriter
from .evidence_first_writer import EvidenceFirstWriter
from .integrator import NarrativeIntegrator
from .surgeon import CitationSurgeon
from .citation_registry import CitationRegistry
from .coherence_validator import CoherenceValidator
from ...config import get_config
from ...tracing import stage

logger = logging.getLogger(__name__)


class GenerationPipeline:
    """Orchestrate the 4-stage generation pipeline with citation integrity."""

    def __init__(self):
        self.config = get_config()
        config_data = self.config.load_config()
        integrity_config = config_data.get("citation", {}).get("integrity", {})

        self.analyst = ClaimAnalyst()
        self.sectional_writer = SectionalWriter()
        # Substitutes hard-removed citations: intros coherent by construction
        self.evidence_first_writer = EvidenceFirstWriter()
        self.integrator = NarrativeIntegrator()
        self.surgeon = CitationSurgeon()
        self.coherence_validator = CoherenceValidator(
            min_coherence_score=integrity_config.get("min_coherence_score", 0.6),
            method=integrity_config.get("coherence_method", "embedding"),
        )

    @stage("generation_pipeline")
    async def generate(
        self,
        query: str,
        evidence_list: List[Dict[str, Any]],
        stream_callback: Optional[callable] = None,
        query_context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Run the complete generation pipeline with citation integrity.

        stream_callback, when given, receives progress events per stage.
        Returns the final text with citations, metadata and integrity report.
        """
        start_time = datetime.now()
        pipeline_metadata = {
            "stages": {},
            "start_time": start_time.isoformat(),
            "citation_integrity": {}
        }

        registry = CitationRegistry()
        registry.register_evidence(evidence_list)

        # Stage 1: analyst
        if stream_callback:
            await stream_callback({
                "type": "progress",
                "stage": 1,
                "message": "Analyzing query and evidence..."
            })

        _stage_t0 = time.perf_counter()
        claims_result = self.analyst.analyze(query, evidence_list)
        claims = claims_result.get("claims", [])

        pipeline_metadata["stages"]["analyst"] = {
            "claims_count": len(claims),
            "query_type": claims_result.get("query_type"),
            "requires_government": claims_result.get("requires_government_view", False),
            "duration_ms": round((time.perf_counter() - _stage_t0) * 1000, 1),
            "model": self.analyst.model,
        }

        logger.info(f"Stage 1 complete: {len(claims)} claims identified")

        evidence_by_party = self._group_evidence_by_party(evidence_list)
        government_evidence = self._get_government_evidence(evidence_list)
        evidence_map = {
            e.get("evidence_id"): e for e in evidence_list if e.get("evidence_id")
        }

        # Stage 2: sectional writer
        if stream_callback:
            await stream_callback({
                "type": "progress",
                "stage": 2,
                "message": "Writing party sections..."
            })

        sections = []
        _stage_t0 = time.perf_counter()
        async for section in self.sectional_writer.write_sections(
            query=query,
            claims=claims,
            evidence_by_party=evidence_by_party,
            government_evidence=government_evidence,
            query_context=query_context,
        ):
            sections.append(section)

            # Register citation bindings in registry
            content = section.get("content", "")
            party = section.get("party", "")
            citation_ids = re.findall(r'\[CIT:([^\]]+)\]', content)
            for cit_id in citation_ids:
                # Extract intro text (text before [CIT:id])
                pattern = rf'([^.!?]*)\[CIT:{re.escape(cit_id)}\]'
                match = re.search(pattern, content)
                intro = match.group(1).strip() if match else ""
                registry.bind_citation(cit_id, party, intro)

            if stream_callback:
                await stream_callback({
                    "type": "section",
                    "party": party,
                    "has_evidence": section.get("has_evidence", False),
                })

        pipeline_metadata["stages"]["sectional"] = {
            "sections_count": len(sections),
            "parties_with_evidence": sum(1 for s in sections if s.get("has_evidence")),
            "citations_bound": len(registry.get_expected_citations()),
            "duration_ms": round((time.perf_counter() - _stage_t0) * 1000, 1),
            "model": self.sectional_writer.model,
        }

        logger.info(f"Stage 2 complete: {len(sections)} sections written, "
                    f"{len(registry.get_expected_citations())} citations bound")

        # Stage 3: narrative integrator with citation guard
        if stream_callback:
            await stream_callback({
                "type": "progress",
                "stage": 3,
                "message": "Integrating narrative..."
            })

        topic_statistics = self._compute_topic_statistics(evidence_list)

        _stage_t0 = time.perf_counter()
        integrated = self.integrator.integrate_with_guard(
            query, sections, registry, topic_statistics=topic_statistics
        )

        pipeline_metadata["stages"]["integrator"] = {
            "integration_success": not integrated.get("integration_failed", False),
            "citation_verification": integrated.get("citation_verification", {}),
            "citations_repaired": integrated.get("citations_repaired", 0),
            "duration_ms": round((time.perf_counter() - _stage_t0) * 1000, 1),
            "model": self.integrator.model,
        }

        logger.info(f"Stage 3 complete: Narrative integrated, "
                    f"{integrated.get('citations_repaired', 0)} citations repaired")

        # Party-name completeness check: the integrator LLM occasionally drops
        # a party's "Per [Party Name]," prefix or uses an abbreviation. Detect
        # and inject the original section content as a fallback paragraph so
        # the metric is not penalised unfairly.
        integrated_text_after_guard = integrated.get("text", "")
        integrated_text_after_guard, injected_parties = self._inject_missing_party_paragraphs(
            integrated_text_after_guard, sections
        )
        if injected_parties:
            pipeline_metadata["stages"]["party_injection"] = {"injected_parties": injected_parties}

        # The integrator can duplicate one party's quote inside ANOTHER
        # party's paragraph ("enriched" citation-free sections): the same
        # [CIT:id] twice is always an error, keep only the right paragraph.
        integrated_text_after_guard = self._dedupe_citation_occurrences(
            integrated_text_after_guard, evidence_map
        )
        integrated["text"] = integrated_text_after_guard

        # Balance check (coverage-based fairness)
        balance_info = self._check_coalition_balance(integrated.get("text", ""))
        pipeline_metadata["stages"]["balance"] = balance_info
        if balance_info.get("balance_warning"):
            logger.warning(
                f"Coalition imbalance detected: "
                f"majority={balance_info['majority_words']} words, "
                f"opposition={balance_info['opposition_words']} words, "
                f"ratio={balance_info['ratio']:.1f}:1"
            )

        # Pre-surgeon coherence validation. Pour the picker-chosen quotes
        # into evidence_map BEFORE validating: the validator must compare the
        # intro against the chosen QUOTE, not the embedding of the whole
        # chunk (~1200 multi-topic chars) → score 0.15-0.20 and systematic
        # hard-removal (observed 2026-07-23).
        for section in sections:
            for pick_eid, pick_quote in (section.get("picked_quotes") or {}).items():
                if pick_eid in evidence_map and pick_quote:
                    evidence_map[pick_eid]["quote_text"] = pick_quote
                    evidence_map[pick_eid]["quote_vetted"] = True
        coherence_report = self.coherence_validator.validate_all_citations(
            integrated.get("text", ""),
            evidence_map
        )

        pipeline_metadata["citation_integrity"]["coherence"] = {
            "all_coherent": coherence_report["all_coherent"],
            "coherent_count": coherence_report["coherent_citations"],
            "incoherent_count": coherence_report["incoherent_citations"],
            "average_score": coherence_report["average_score"],
        }

        integrated_text = integrated.get("text", "")

        if not coherence_report["all_coherent"]:
            incoherent = self.coherence_validator.get_incoherent_citations(coherence_report)
            logger.warning(f"Coherence issues: {len(incoherent)} incoherent citations")
            for ic in incoherent[:3]:  # Log first 3
                logger.warning(f"  - {ic.get('evidence_id')}: {ic.get('warning')}")

            # Hard-remove citations with extreme mismatch (likely wrong source cited)
            HARD_REMOVE_THRESHOLD = 0.35
            # Picker-VETTED quotes are exempt from hard-removal: the writer
            # builds the intro AROUND the mandatory quote, so coherence is
            # guaranteed by construction. Embedding similarity between two
            # short texts is a worse judge than the picker+writer contract:
            # on niche queries it dropped below 0.35 for almost all good
            # citations, triggering chain substitutions (and quote-less
            # sections where the pool is thin, 2026-07-24).
            hard_mismatches = [
                ic for ic in incoherent
                if ic.get("score", 1.0) < HARD_REMOVE_THRESHOLD
                and not evidence_map.get(ic.get("evidence_id", ""), {}).get("quote_vetted")
            ]
            n_exempt = sum(
                1 for ic in incoherent
                if ic.get("score", 1.0) < HARD_REMOVE_THRESHOLD
                and evidence_map.get(ic.get("evidence_id", ""), {}).get("quote_vetted")
            )
            if n_exempt:
                logger.info(
                    f"Coherence: {n_exempt} low-score citations kept (picker-vetted)"
                )
            if hard_mismatches:
                logger.warning(f"Hard-removing {len(hard_mismatches)} citations with score < {HARD_REMOVE_THRESHOLD}")
                for ic in hard_mismatches:
                    eid = ic.get("evidence_id", "")
                    # Remove «inline quote» [CIT:id] together to prevent bare «» in output.
                    # Allow punctuation/whitespace between » and [CIT: (LLM may insert . or ,)
                    integrated_text = re.sub(
                        rf'«[^»]+»[.,;:!?\s]*\[CIT:{re.escape(eid)}\]',
                        '',
                        integrated_text
                    )
                    # Also remove bare [CIT:id] if no inline quote preceded it
                    integrated_text = re.sub(rf'\[CIT:{re.escape(eid)}\]', '', integrated_text)

                # Substitution before giving up: for each hard-removed
                # citation try the party's next evidence via
                # EvidenceFirstWriter (intro coherent by construction, its
                # original purpose). Only when no alternative exists fall
                # back to a citation-free paragraph.
                if hard_mismatches:
                    removed_ids = {ic.get("evidence_id", "") for ic in hard_mismatches}
                    used_ids = set(re.findall(r'\[CIT:([^\]]+)\]', integrated_text))

                    rewrite_tasks = {}
                    for ic in hard_mismatches:
                        eid = ic.get("evidence_id", "")
                        removed_ev = evidence_map.get(eid, {})
                        party = removed_ev.get("party", "")
                        is_gov = (
                            removed_ev.get("coalition") == "governo"
                            or removed_ev.get("speaker_role") == "GovernmentMember"
                        )

                        # GOVERNO: substitute inside the dedicated section
                        if is_gov:
                            gov_alternatives = [
                                e for e in government_evidence
                                if e.get("evidence_id") not in removed_ids
                                and e.get("evidence_id") not in used_ids
                            ]
                            if gov_alternatives:
                                # Substitutions also go through the quote
                                # picker (2026-07-23: Meloni's chunk_3 opened
                                # with the Ukraine sentence — the
                                # EvidenceFirstWriter cited it, bypassing every
                                # self-sufficiency criterion)
                                pick_eid, pick_quote = await self.sectional_writer._pick_quote(
                                    query, gov_alternatives, query_context=query_context
                                )
                                if not pick_eid:
                                    logger.info(
                                        f"No citable GOVERNO substitute (picker) for {eid}"
                                    )
                                    continue
                                gov_alternatives = [
                                    {**e, "quote_text": pick_quote}
                                    for e in gov_alternatives
                                    if e.get("evidence_id") == pick_eid
                                ]
                                if pick_eid in evidence_map:
                                    evidence_map[pick_eid]["quote_text"] = pick_quote
                                    evidence_map[pick_eid]["quote_vetted"] = True
                                section = await self.evidence_first_writer.write_section_evidence_first(
                                    query=query, party="GOVERNO",
                                    evidence=gov_alternatives, max_citations=1,
                                )
                                new_body = re.sub(r'^###[^\n]*\n+', '', section.get("content", "")).strip()
                                new_ids = re.findall(r'\[CIT:([^\]]+)\]', new_body)
                                if new_body and new_ids:
                                    replaced = re.sub(
                                        r'(## Posizione del Governo\s*\n+).*?(?=\n\n##|\Z)',
                                        lambda m: m.group(1) + new_body,
                                        integrated_text, count=1, flags=re.DOTALL,
                                    )
                                    if replaced != integrated_text:
                                        integrated_text = replaced
                                        used_ids.update(new_ids)
                                        logger.info(
                                            f"Substituted hard-removed GOVERNO citation "
                                            f"{eid} with {new_ids[0]}"
                                        )
                                        continue
                            logger.info(f"No GOVERNO substitute available for {eid}")
                            continue

                        if not party or party in rewrite_tasks:
                            continue
                        # Only act if the party has no remaining [CIT:] in the text
                        remaining = re.findall(r'\[CIT:[^\]]+\]', integrated_text)
                        party_eids = {e.get("evidence_id") for e in evidence_by_party.get(party, [])}
                        has_other_citations = any(
                            r in party_eids for r in remaining
                        )
                        if has_other_citations:
                            logger.info(f"Skipping rewrite for '{party}': still has other citations")
                            continue
                        party_evidence = evidence_by_party.get(party, [])

                        # Party: try substitution with the next evidence
                        alternatives = [
                            e for e in party_evidence
                            if e.get("evidence_id") not in removed_ids
                            and e.get("evidence_id") not in used_ids
                        ]
                        if alternatives:
                            pick_eid, pick_quote = await self.sectional_writer._pick_quote(
                                query, alternatives, query_context=query_context
                            )
                            if not pick_eid:
                                logger.info(
                                    f"No citable substitute (picker) for '{party}'"
                                )
                                if party_evidence:
                                    rewrite_tasks[party] = party_evidence
                                continue
                            alternatives = [
                                {**e, "quote_text": pick_quote}
                                for e in alternatives
                                if e.get("evidence_id") == pick_eid
                            ]
                            if pick_eid in evidence_map:
                                evidence_map[pick_eid]["quote_text"] = pick_quote
                                evidence_map[pick_eid]["quote_vetted"] = True
                            section = await self.evidence_first_writer.write_section_evidence_first(
                                query=query, party=party,
                                evidence=alternatives, max_citations=1,
                            )
                            new_body = re.sub(r'^###[^\n]*\n+', '', section.get("content", "")).strip()
                            new_ids = re.findall(r'\[CIT:([^\]]+)\]', new_body)
                            if new_body and new_ids:
                                before = integrated_text
                                integrated_text = self._replace_party_paragraph(
                                    integrated_text, party, new_body
                                )
                                if integrated_text != before:
                                    used_ids.update(new_ids)
                                    logger.info(
                                        f"Substituted hard-removed citation for '{party}': "
                                        f"{eid} -> {new_ids[0]}"
                                    )
                                    continue

                        # No alternative: old behavior (paragraph without quotes)
                        if party_evidence:
                            rewrite_tasks[party] = party_evidence

                    if rewrite_tasks:
                        logger.info(f"Rewriting {len(rewrite_tasks)} citation-free paragraphs: {list(rewrite_tasks)}")
                        rewrite_results = await asyncio.gather(*[
                            self.sectional_writer.write_section_without_citation(
                                query=query,
                                party=party,
                                evidence=ev,
                                claims=claims,
                            )
                            for party, ev in rewrite_tasks.items()
                        ])
                        failed_rewrites: Dict[str, str] = {}
                        for party, new_body in zip(rewrite_tasks.keys(), rewrite_results):
                            if new_body:
                                before = integrated_text
                                integrated_text = self._replace_party_paragraph(
                                    integrated_text, party, new_body
                                )
                                if integrated_text == before:
                                    # _replace_party_paragraph couldn't locate the paragraph;
                                    # queue for fallback injection into the coalition block.
                                    failed_rewrites[party] = new_body
                        if failed_rewrites:
                            integrated_text = self._inject_rewritten_paragraphs(
                                integrated_text, failed_rewrites
                            )

        # The integrator LLM can emit the same party twice (observed 2026-07-23:
        # double Fratelli d'Italia, one smart-quoted ’ and one straight '), and
        # fallback injections can add a second paragraph when apostrophe
        # mismatches hid the original. One party = one paragraph, always.
        integrated_text = self._dedupe_party_paragraphs(integrated_text)

        for detail in coherence_report.get("details", []):
            eid = detail.get("evidence_id")
            score = detail.get("score", 0)
            registry.set_coherence_score(eid, score)

        # Stage 4: citation surgeon
        if stream_callback:
            await stream_callback({
                "type": "progress",
                "stage": 4,
                "message": "Inserting citations..."
            })

        _stage_t0 = time.perf_counter()
        final_result = self.surgeon.insert_citations(
            text=integrated_text,
            evidence_map=evidence_map,
            query=query
        )

        for cit in final_result.get("citations", []):
            registry.mark_resolved(cit.get("evidence_id"), success=True)

        for cit in final_result.get("failed_citations", []):
            registry.mark_resolved(
                cit.get("evidence_id"),
                success=False,
                error=cit.get("reason")
            )

        pipeline_metadata["stages"]["surgeon"] = {
            "citations_inserted": final_result.get("total_citations", 0),
            "citations_failed": final_result.get("failed_count", 0),
            "duration_ms": round((time.perf_counter() - _stage_t0) * 1000, 1),
        }

        logger.info(
            f"Stage 4 complete: {final_result.get('total_citations', 0)} citations inserted"
        )

        # Final verification and cleanup
        final_text = final_result.get("text", "")

        # Safety net: post-coherence substitution splices can leave orphaned
        # tails of the same link — «…»](id) with no opening right after the
        # complete link (observed 2026-07-24, Misto). Any second occurrence
        # of ](id) is a leftover to remove.
        final_text = self._strip_residual_citation_fragments(final_text)
        # "Ninety-one interventions" → "91 interventions" (intro only): the
        # prompt alone does not beat the English stylistic convention.
        final_text = self._spelled_stats_to_digits(final_text)
        final_result["text"] = final_text

        # Collect citation IDs found in text but NOT in evidence_map.
        # These may be valid DB chunks the LLM cited from broader context
        # (e.g. sectional writer saw them but they weren't in the top-20 sidebar).
        # We pass them to the caller (chat.py) so it can verify them against
        # the DB and add them to the sidebar — instead of stripping them here.
        valid_evidence_ids = set(evidence_map.keys())
        all_text_ids = set(
            m[1] for m in re.findall(
                r'\[([^\]]+)\]\(((?:sen_)?leg1[89]_[^)]+)\)', final_text
            )
        )
        extra_citation_ids = list(all_text_ids - valid_evidence_ids)
        if extra_citation_ids:
            logger.info(
                f"Found {len(extra_citation_ids)} citation IDs in text not in "
                f"evidence_map — passing to caller for DB verification: "
                f"{extra_citation_ids[:5]}"
            )

        # Recover untracked citations after the surgeon.
        # The Integrator LLM sometimes outputs direct markdown links
        # [«quote»](evidence_id) instead of [CIT:id] placeholders.
        # These bypass the Surgeon's regex and are NOT in the citations list.
        # Extract them here so the frontend can match clicks to metadata.
        tracked_ids = {
            c.get("evidence_id") for c in final_result.get("citations", [])
        }
        untracked_links = re.findall(
            r'\[([^\]]+)\]\(((?:sen_)?leg1[89]_[^)]+)\)', final_text
        )
        for display_text, eid in untracked_links:
            if eid not in tracked_ids and eid in evidence_map:
                evidence = evidence_map[eid]
                # Use raw quote_text from evidence (verbatim extraction from source),
                # NOT the display text which has been modified by _format_citation
                # (parenthetical removal, dangling words, lowercase, etc.).
                raw_quote = evidence.get("quote_text", "") or evidence.get("chunk_text", "")

                final_result.get("citations", []).append({
                    "evidence_id": eid,
                    "quote_text": raw_quote,
                    "speaker_name": evidence.get("speaker_name"),
                    "party": evidence.get("party"),
                    "date": str(evidence.get("date", "")),
                    "span_start": evidence.get("span_start", 0),
                    "span_end": evidence.get("span_end", 0),
                })
                tracked_ids.add(eid)
                registry.mark_resolved(eid, success=True)
                logger.info(
                    f"Recovered untracked citation: {eid} "
                    f"(quote: '{raw_quote[:60]}...')"
                )

        if len(tracked_ids) > final_result.get("total_citations", 0):
            recovered = len(tracked_ids) - final_result.get("total_citations", 0)
            logger.info(f"Recovered {recovered} untracked citations from final text")

        # Check for bare «» citations not wrapped in markdown links and remove them.
        # These can appear when hard-removed citations leave orphaned quotes (e.g. when
        # the integrator LLM moves [CIT:id] after a period, separating it from «»).
        bare_citations = re.findall(r'(?<!\[)«[^»]+»', final_text)
        if bare_citations:
            logger.warning(
                f"Found {len(bare_citations)} bare citations without markdown links: "
                f"{[c[:50] for c in bare_citations[:3]]}"
            )
            final_text = re.sub(r'(?<!\[)«[^»]+»', '', final_text)

        # Clean up verb-phrase artifacts left after removing a quote (bare or
        # hard-removed). Runs unconditionally because the coherence
        # hard-removal above strips «quote»[CIT:id] but leaves attribution
        # phrases like "**Lupi** afferma: ." intact — and since no bare «»
        # remain afterwards, the bare_citations block above never fires.
        #
        # Three artifact patterns, applied in order:
        #
        # 1. "afferma: ."  → "."  (colon left after quote stripped in sectional)
        final_text = re.sub(r':\s*\.', '.', final_text)
        # 2. "afferma che ." → "."  (dangling conjunction left after [CIT:id] stripped)
        final_text = re.sub(r'\s+(?:che|come|di)\s+\.', '.', final_text)
        # 3. "afferma ."  → "afferma."  (bare space before period from bare-quote removal)
        final_text = re.sub(r' \.', '.', final_text)
        # 4. "**nome** afferma."  → ""  (standalone attribution sentence with no content).
        #    After steps 1-3 all paths converge on this pattern: bold name + single bridge
        #    verb + period and nothing else. Safe to strip because a verb immediately
        #    followed by a period (no object) is never a meaningful sentence here.
        final_text = re.sub(r'\*\*[^*\n]+\*\*\s+\w+\.', '', final_text)

        # Attribution enforcement: a deputy's bold name may only appear in a
        # sentence that carries their citation. The writer prompt states the
        # rule and the sectional stage anonymizes, but the LLM integrator can
        # still move names into citation-free sentences.
        final_text, attribution_fixes = self._enforce_bold_name_attribution(
            final_text, evidence_map
        )
        if attribution_fixes:
            pipeline_metadata["stages"]["attribution_enforcement"] = {
                "names_anonymized": attribution_fixes,
            }

        # Replace unresolved [CIT:id] placeholders with an error marker
        remaining_placeholders = re.findall(r'\[CIT:([^\]]+)\]', final_text)
        if remaining_placeholders:
            logger.error(f"Unresolved citation placeholders: {remaining_placeholders}")
            for cit_id in remaining_placeholders:
                final_text = final_text.replace(
                    f"[CIT:{cit_id}]",
                    "[Citazione non risolta]"
                )
                registry.mark_resolved(cit_id, success=False, error="unresolved_placeholder")

        # Save text with resolved placeholders (link stripping deferred to chat.py)
        final_result["text"] = final_text

        unsupported_claims = self.surgeon.extract_unsupported_claims(final_text)
        integrity_report = registry.get_final_report()

        pipeline_metadata["citation_integrity"]["final"] = integrity_report
        pipeline_metadata["citation_integrity"]["unsupported_claims"] = unsupported_claims

        end_time = datetime.now()
        duration_ms = (end_time - start_time).total_seconds() * 1000

        pipeline_metadata["end_time"] = end_time.isoformat()
        pipeline_metadata["duration_ms"] = duration_ms

        return {
            "text": final_result.get("text", ""),
            "citations": final_result.get("citations", []),
            "failed_citations": final_result.get("failed_citations", []),
            "extra_citation_ids": extra_citation_ids,
            "claims": claims,
            "sections": [
                {"party": s["party"], "has_evidence": s.get("has_evidence", False)}
                for s in sections
            ],
            "metadata": pipeline_metadata,
            "topic_statistics": topic_statistics,
            "citation_integrity": {
                "is_complete": integrity_report["is_complete"],
                "success_rate": integrity_report["success_rate"],
                "coherence_verified": coherence_report["all_coherent"],
                "unsupported_claims_count": len(unsupported_claims),
                "unresolved_placeholders": remaining_placeholders,
            }
        }

    def _compute_topic_statistics(
        self,
        evidence_list: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Compute real statistics about the topic from retrieved evidence.

        Returns both aggregate counts (for the integrator prompt) and detailed
        lists (for the frontend clickable stats in the introduction).
        """
        if not evidence_list:
            return {
                "intervention_count": 0,
                "speaker_count": 0,
                "first_date": None,
                "last_date": None,
                "debate_title": None,
                "speakers_detail": [],
                "interventions_detail": [],
                "sessions_detail": [],
            }

        from collections import Counter

        unique_speeches = set(
            e.get("speech_id") for e in evidence_list if e.get("speech_id")
        )
        unique_speakers = set(
            e.get("speaker_id") for e in evidence_list if e.get("speaker_id")
        )
        dates = [e.get("date") for e in evidence_list if e.get("date")]

        # Find the most frequent debate title to name the specific provvedimento.
        # Procedural continuation headings ("Si riprende la discussione...") name
        # no provvedimento: excluded so the intro never leads with them.
        procedural_title = re.compile(
            r'(?i)^\s*(si riprende la discussione'
            r'|seguito della discussione\.?\s*$'
            r'|ripresa della discussione'
            r'|discussione congiunta\.?\s*$'
            r'|missioni\.?\s*$'
            r'|interventi di fine seduta'
            r'|ordine del giorno della prossima seduta)'
        )
        debate_titles = [
            e.get("debate_title") for e in evidence_list
            if e.get("debate_title")
            and not procedural_title.match(e.get("debate_title", ""))
        ]
        most_common_title = (
            Counter(debate_titles).most_common(1)[0][0]
            if debate_titles else None
        )

        # Collect session numbers for academic traceability
        session_numbers = [
            e.get("session_number") for e in evidence_list
            if e.get("session_number")
        ]

        # Detailed lists for frontend clickable stats

        # Speakers: one entry per unique speaker with intervention count
        speaker_interventions: Dict[str, Dict[str, Any]] = {}
        for e in evidence_list:
            sid = e.get("speaker_id")
            if not sid:
                continue
            if sid not in speaker_interventions:
                speaker_interventions[sid] = {
                    "speaker_id": sid,
                    "speaker_name": e.get("speaker_name", ""),
                    "party": e.get("party", ""),
                    "coalition": e.get("coalition", ""),
                    "speech_ids": set(),
                }
            speech_id = e.get("speech_id")
            if speech_id:
                speaker_interventions[sid]["speech_ids"].add(speech_id)

        speakers_detail = []
        for info in speaker_interventions.values():
            speakers_detail.append({
                "speaker_id": info["speaker_id"],
                "speaker_name": info["speaker_name"],
                "party": info["party"],
                "coalition": info["coalition"],
                "intervention_count": len(info["speech_ids"]),
            })
        speakers_detail.sort(key=lambda x: x["intervention_count"], reverse=True)

        # Interventions: one entry per unique speech
        seen_speeches: Dict[str, Dict[str, Any]] = {}
        for e in evidence_list:
            speech_id = e.get("speech_id")
            if not speech_id or speech_id in seen_speeches:
                continue
            seen_speeches[speech_id] = {
                "speech_id": speech_id,
                # Official page of the speech (Senate); None for the Camera.
                "url": e.get("url"),
                "speaker_id": e.get("speaker_id", ""),
                "speaker_name": e.get("speaker_name", ""),
                "party": e.get("party", ""),
                "coalition": e.get("coalition", ""),
                "date": str(e.get("date", "")),
                "debate_title": e.get("debate_title", ""),
                "session_number": e.get("session_number", 0),
            }
        interventions_detail = sorted(
            seen_speeches.values(),
            key=lambda x: x["date"],
            reverse=True,
        )

        # Sessions: one entry per sitting. Numbers repeat across chambers
        # (Senate 463 is not Camera 463), so the sitting id is the key.
        seen_sessions: Dict[str, Dict[str, Any]] = {}
        for e in evidence_list:
            sn = e.get("session_number")
            key = e.get("doc_id") or str(sn)
            if not sn or key in seen_sessions:
                continue
            seen_sessions[key] = {
                "session_number": sn,
                "session_id": e.get("doc_id", ""),
                "chamber": "senato" if str(e.get("doc_id", "")).startswith("sen_") else "camera",
                # Sitting page on senato.it: the speech link without its anchor.
                "url": (e.get("url") or "").split("&part=", 1)[0] or None,
                "date": str(e.get("date", "")),
                "debate_title": e.get("debate_title", ""),
            }
        sessions_detail = sorted(
            seen_sessions.values(),
            key=lambda x: (x["chamber"], x["session_number"]),
        )

        # Per chamber, for answers that mix the two houses (Senate ids: sen_...).
        by_chamber: Dict[str, Dict[str, set]] = {}
        for e in evidence_list:
            chamber = "senato" if str(e.get("doc_id", "")).startswith("sen_") else "camera"
            slot = by_chamber.setdefault(chamber, {"speeches": set(), "speakers": set()})
            if e.get("speech_id"):
                slot["speeches"].add(e["speech_id"])
            if e.get("speaker_id"):
                slot["speakers"].add(e["speaker_id"])

        return {
            "by_chamber": {
                c: {"intervention_count": len(v["speeches"]), "speaker_count": len(v["speakers"])}
                for c, v in by_chamber.items()
            },
            "intervention_count": len(unique_speeches),
            "speaker_count": len(unique_speakers),
            "first_date": min(dates) if dates else None,
            "last_date": max(dates) if dates else None,
            "debate_title": most_common_title,
            "session_numbers": list(set(session_numbers)),
            "speakers_detail": speakers_detail,
            "interventions_detail": interventions_detail,
            "sessions_detail": sessions_detail,
        }

    def _replace_party_paragraph(self, text: str, party: str, new_body: str) -> str:
        """
        Replace the body of a party's paragraph in the integrated text.

        Party paragraphs follow the integrator's mandatory format:
            "Per [Full Party Name], [body text]"
        and end before the next paragraph ("Per ") or section header ("##").

        Only the body is replaced; the "Per [Party], " prefix is preserved so
        the output keeps the correct paragraph structure.

        Falls back to a loose match when the integrator used a non-standard
        opening (e.g. "Il {party} critica..." instead of "Per {party}, ...").
        """
        # Apostrophe tolerance: the integrator LLM smart-quotes ' into ’, so
        # "Fratelli d'Italia" (config) never matches "Fratelli d'Italia" (text).
        # Every apostrophe in the pattern matches both variants; loose
        # comparison normalizes both sides.
        party_escaped = re.escape(party).replace(r"'", "['’]").replace("’", "['’]")
        # Strict match: canonical "Per {party}," format
        pattern = rf'(Per {party_escaped},\s+).*?(?=\n\nPer |\n\n##|\Z)'
        new_text, n = re.subn(pattern, rf'\g<1>{new_body}', text, flags=re.DOTALL)
        if n > 0:
            logger.info(f"Rewrote citation-free paragraph for '{party}'")
            return new_text

        # Loose match: integrator may have opened with "Il {party} ..." or similar.
        # Split on double-newlines and find the paragraph whose first sentence
        # contains the party name; replace the whole paragraph.
        party_norm = party.replace("’", "'")
        parts = text.split('\n\n')
        for i, part in enumerate(parts):
            stripped = part.lstrip()
            if stripped.startswith('##'):
                continue
            first_sentence = stripped.split('.')[0].replace("’", "'")
            if party_norm in first_sentence:
                parts[i] = f"Per {party}, {new_body}"
                logger.info(f"Rewrote citation-free paragraph for '{party}' (loose match)")
                return '\n\n'.join(parts)

        logger.warning(f"Could not locate paragraph for '{party}' in integrated text — skipping rewrite")
        return text

    @staticmethod
    def _dedupe_party_paragraphs(text: str) -> str:
        """Enforce one paragraph per party in the integrated text.

        Duplicates arise from LLM repetition or fallback injections that
        missed the original paragraph due to apostrophe variants. The kept
        paragraph is the one WITH citations ([CIT: or «»-linked); on parity,
        the first occurrence wins. Party keys are apostrophe-normalized.
        """
        parts = text.split('\n\n')
        # First pass: index "Per {party}," paragraphs by normalized party key
        party_of_part: Dict[int, str] = {}
        by_party: Dict[str, list] = {}
        for i, part in enumerate(parts):
            m = re.match(r'\s*Per ([^,]{3,90}),', part)
            if not m:
                continue
            key = m.group(1).replace("’", "'").strip().lower()
            party_of_part[i] = key
            by_party.setdefault(key, []).append(i)

        to_drop: set = set()
        for key, idxs in by_party.items():
            if len(idxs) < 2:
                continue
            # Keep the paragraph with citations; on parity keep the first
            def has_cit(i: int) -> bool:
                return '[CIT:' in parts[i] or '](' in parts[i] or '«' in parts[i]
            keeper = next((i for i in idxs if has_cit(i)), idxs[0])
            for i in idxs:
                if i != keeper:
                    to_drop.add(i)
            logger.warning(
                f"Deduped duplicate party paragraph(s) for {key!r}: "
                f"kept #{keeper}, dropped {sorted(to_drop & set(idxs))}"
            )

        if not to_drop:
            return text
        return '\n\n'.join(p for i, p in enumerate(parts) if i not in to_drop)

    # Spelled-out English numbers (1-99): at sentence start the model writes
    # "Ninety-one interventions" by stylistic convention even when told to
    # use digits — and the frontend makes stats clickable only via \d+.
    # Deterministic conversion, applied to the intro only.
    _EN_UNITS = {
        "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
        "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
        "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
        "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    }
    _EN_TENS = {
        "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
        "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
    }

    @classmethod
    def _spelled_stats_to_digits(cls, text: str) -> str:
        """Convert spelled-out English numbers to digits when they precede a
        statistics noun (interventions/deputies/…) in the introduction."""
        tens = "|".join(cls._EN_TENS)
        units = "|".join(cls._EN_UNITS)
        nouns = r"(interventions?|deput(?:y|ies)|parliamentarians?|speeches|sessions?|sittings?)"
        pattern = re.compile(
            rf"\b((?:{tens})(?:[-\s](?:{units}))?|(?:{units}))\s+{nouns}",
            re.IGNORECASE,
        )

        def to_digits(m: re.Match) -> str:
            word = m.group(1).lower().replace("-", " ")
            parts = word.split()
            value = 0
            for p in parts:
                value += cls._EN_TENS.get(p, cls._EN_UNITS.get(p, 0))
            if value == 0:
                return m.group(0)
            return f"{value} {m.group(2)}"

        # Intro section only (from the first ## to the second ##): verbatim
        # quotes in the party sections must never be altered.
        first = re.search(r"^##\s", text, re.M)
        if not first:
            return text
        second = re.search(r"^##\s", text[first.end():], re.M)
        end = first.end() + second.start() if second else len(text)
        intro = text[:end]
        converted = pattern.sub(to_digits, intro)
        if converted != intro:
            logger.info("[INTRO] Spelled-out stat numbers converted to digits")
        return converted + text[end:]

    @staticmethod
    def _enforce_bold_name_attribution(
        text: str,
        evidence_map: Dict[str, Any],
    ) -> tuple:
        """Anonymize bold speaker names in sentences without their citation.

        A bold **Name** implies "these are their words": without a citation
        link in the same sentence the attribution is unverifiable, so the
        name becomes a generic group reference. Only names of known evidence
        speakers are touched — other bold text is left alone. Link IDs
        contain periods, so sentence boundaries are computed on a masked
        copy where every link is padded out.

        Returns (possibly modified text, number of anonymized names).
        """
        names = set()
        for e in evidence_map.values():
            full = (e.get("speaker_name") or "").strip()
            if full:
                names.add(full)
                names.add(full.split()[-1])
        if not names:
            return text, 0

        link_re = re.compile(r'\[«[^\]]*»\]\([^)\s]+\)')
        masked_chars = list(text)
        for m in link_re.finditer(text):
            for i in range(m.start(), m.end()):
                masked_chars[i] = '\x01'
        masked = ''.join(masked_chars)

        replacements = []
        for m in re.finditer(r'\*\*([^*\n]+)\*\*', text):
            if m.group(1).strip() not in names:
                continue
            start = max(masked.rfind(ch, 0, m.start()) for ch in '.!?\n') + 1
            ends = [
                idx for idx in (masked.find(ch, m.end()) for ch in '.!?\n')
                if idx != -1
            ]
            end = min(ends) if ends else len(masked)
            sentence = masked[start:end]
            if '\x01' in sentence or '[CIT:' in sentence or '«' in sentence:
                continue
            replacements.append((m.start(), m.end(), m.group(1).strip()))

        for a, b, name in reversed(replacements):
            replacement = 'Il gruppo' if a == 0 or text[a - 1] in '.!?\n' else 'il gruppo'
            text = text[:a] + replacement + text[b:]
            logger.info(f"Attribution enforcement: anonymized bold name {name!r}")

        return text, len(replacements)

    @staticmethod
    def _strip_residual_citation_fragments(text: str) -> str:
        """Remove residual/duplicate occurrences of the same citation link.

        After the surgeon every citation is a [«quote»](chunk_id) link and
        each chunk_id must appear once. Post-coherence substitution splices
        can leave orphaned tails («…»](id) with no opening) appended to the
        complete link. Keep the first complete occurrence and remove every
        other ](id), extending leftward to the fragment opening (« or
        sentence boundary).
        """
        link_re = re.compile(r'\[«[^»]{1,600}»\]\(((?:sen_)?leg1[89]_[^)\s]+)\)')
        first_span: Dict[str, tuple] = {}
        for m in link_re.finditer(text):
            first_span.setdefault(m.group(1), (m.start(), m.end()))

        tail_re = re.compile(r'»?\]\(((?:sen_)?leg1[89]_[^)\s]+)\)')
        removals = []
        for m in tail_re.finditer(text):
            eid = m.group(1)
            kept = first_span.get(eid)
            if kept and kept[0] <= m.start() < kept[1]:
                continue  # this is the kept link
            if not kept:
                continue  # single occurrence in unexpected format: leave alone
            start = m.start()
            idx_open = text.rfind('«', 0, start)
            idx_sent = max(text.rfind(ch, 0, start) for ch in '.!?\n')
            if idx_open > idx_sent:
                left = idx_open
                if left > 0 and text[left - 1] == '[':
                    left -= 1
            else:
                left = idx_sent + 1
            end = m.end()
            if end < len(text) and text[end] in '.,;':
                end += 1
            removals.append((left, end))

        if not removals:
            return text
        for a, b in sorted(removals, reverse=True):
            logger.warning(
                f"Stripped residual citation fragment: {text[a:b][:90]!r}"
            )
            text = text[:a] + text[b:]
        return re.sub(r' {2,}', ' ', text)

    @staticmethod
    def _dedupe_citation_occurrences(text: str, evidence_map: Dict[str, Any]) -> str:
        """Remove duplicate occurrences of the same [CIT:id] across paragraphs.

        The integrator sometimes "enriches" citation-free paragraphs by
        copying another party's quote+CIT (observed 2026-07-23: a
        Bonetti/Azione quote attributed to M5S with contradictory framing).
        The same CIT id twice is always an error: keep the occurrence in the
        evidence's own party paragraph (fallback: the first) and remove the
        whole sentence elsewhere.
        """
        ids = re.findall(r'\[CIT:([^\]]+)\]', text)
        dup_ids = {i for i in ids if ids.count(i) > 1}
        if not dup_ids:
            return text

        def para_key(p: str) -> Optional[str]:
            m = re.match(r"\s*Per ([^,]{3,90}),", p)
            return m.group(1).replace("’", "'").strip().lower() if m else None

        parts = text.split('\n\n')
        for eid in dup_ids:
            ev = evidence_map.get(eid, {})
            ev_party = (
                ev.get("current_party")
                if ev.get("party_changed") and ev.get("current_party")
                else ev.get("party", "")
            ) or ""
            key = ev_party.replace("’", "'").strip().lower()
            occ = [i for i, p in enumerate(parts) if f'[CIT:{eid}]' in p]
            if len(occ) < 2:
                continue
            keeper = next((i for i in occ if para_key(parts[i]) == key), occ[0])
            for i in occ:
                if i == keeper:
                    continue
                cleaned = re.sub(
                    r'[^.!?\n]*«[^»]*»\s*\[CIT:' + re.escape(eid) + r'\][^.!?\n]*[.!?]?',
                    '',
                    parts[i],
                )
                # Fallback: CIT without adjacent «» (unexpected format)
                cleaned = cleaned.replace(f'[CIT:{eid}]', '')
                parts[i] = re.sub(r'  +', ' ', cleaned).strip()
                logger.warning(
                    f"Removed misattributed duplicate citation {eid} "
                    f"(evidence party={ev_party!r}) from paragraph "
                    f"{para_key(parts[i]) or '<no header>'!r}"
                )
        return '\n\n'.join(p for p in parts if p.strip())

    def _inject_rewritten_paragraphs(
        self,
        text: str,
        rewritten: Dict[str, str],
    ) -> str:
        """
        Fallback injection for parties whose paragraph could not be located by
        _replace_party_paragraph (e.g. the integrator used a non-standard format).

        Appends each rewritten body as a fresh «Per {party}, {body}» paragraph
        inside the correct coalition block, mirroring the logic used by
        _inject_missing_party_paragraphs.
        """
        config = get_config()
        MAGGIORANZA = config.coalitions.get("maggioranza", [])
        MISTO = config.coalitions.get("misto", [])

        magg_injections: list = []
        opp_injections: list = []
        misto_injections: list = []

        for party, body in rewritten.items():
            para = f"Per {party}, {body}"
            if party in MAGGIORANZA:
                magg_injections.append(para)
            elif party in MISTO:
                # The Misto has its own block: not ascribable to either side
                misto_injections.append(para)
            else:
                opp_injections.append(para)
            logger.info(f"Fallback injection: appending rewritten paragraph for '{party}'")

        if magg_injections:
            magg_header = "## Posizioni della Maggioranza"
            inject_block = "\n\n".join(magg_injections)
            if magg_header in text:
                pos = text.find(magg_header)
                next_sec = text.find("\n\n##", pos + len(magg_header))
                if next_sec > 0:
                    text = text[:next_sec] + "\n\n" + inject_block + text[next_sec:]
                else:
                    text = text + "\n\n" + inject_block
            else:
                text = text + f"\n\n{magg_header}\n\n{inject_block}"

        if opp_injections:
            opp_header = "## Posizioni dell\u2019Opposizione"
            opp_header_alt = "## Posizioni dell'Opposizione"
            inject_block = "\n\n".join(opp_injections)
            header_in_text = (
                opp_header if opp_header in text
                else (opp_header_alt if opp_header_alt in text else None)
            )
            if header_in_text:
                text = text + "\n\n" + inject_block
            else:
                text = text + f"\n\n{opp_header_alt}\n\n{inject_block}"

        if misto_injections:
            misto_header = "## Gruppo Misto"
            inject_block = "\n\n".join(misto_injections)
            if misto_header in text:
                text = text + "\n\n" + inject_block
            else:
                text = text + f"\n\n{misto_header}\n\n{inject_block}"

        return text

    def _group_evidence_by_party(
        self,
        evidence_list: List[Dict[str, Any]]
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Group evidence by parliamentary party.

        Sorting strategy — "most authoritative speaker first": the goal is
        that each parliamentary group is answered by its most authoritative
        person. A pure linear score mix lets high-similarity chunks from a
        lower-authority speaker crowd out the capogruppo. We prevent this
        with a two-step speaker-first interleaving:

        1. Group chunks by speaker within each party.
        2. For each speaker compute best_chunk_score =
               0.75 * similarity + 0.25 * salience
        3. Rank speakers by:
               0.70 * authority_score + 0.30 * best_chunk_score
           → the most authoritative speaker with any relevant chunk is #1.
        4. Interleave: best chunk from speaker #1, best chunk from speaker #2,
           then 2nd-best chunk from speaker #1, etc.

        Result: position #1 always belongs to the highest-authority speaker,
        position #2 to a different speaker, giving the sectional writer (and
        the semantic dedup) a genuinely diverse pair to work with.

        Government members (GovernmentMember) are excluded: they have their
        own separate section.
        """
        from collections import defaultdict

        all_parties = get_config().get_all_parties()
        by_party: Dict[str, List[Dict[str, Any]]] = {party: [] for party in all_parties}

        for evidence in evidence_list:
            # Skip government members - they go in the GOVERNO section
            if evidence.get("speaker_role") == "GovernmentMember":
                continue

            # Use current party if the speaker has changed group, so that only
            # current members appear under their current group.
            party = (
                evidence.get("current_party")
                if evidence.get("party_changed") and evidence.get("current_party")
                else evidence.get("party", "Misto")
            )

            # Handle potential party name variations
            if party not in by_party:
                # Try to find a matching party
                matched = False
                for known_party in all_parties:
                    if party in known_party or known_party in party:
                        by_party[known_party].append(evidence)
                        matched = True
                        break
                if not matched:
                    by_party["Misto"].append(evidence)
            else:
                by_party[party].append(evidence)

        # Speaker-first interleaving sort (see docstring for rationale)
        for party in by_party:
            chunks = by_party[party]
            if not chunks:
                continue

            # Step 1: ensure salience computed for all chunks
            # (index-time citability score if present, neutral 0.5 otherwise)
            for e in chunks:
                if e.get("salience") is None:
                    cit = e.get("citability_score")
                    e["salience"] = float(cit) if cit is not None else 0.5

            # Step 2: group chunks by speaker
            speaker_chunks: Dict[str, list] = defaultdict(list)
            for e in chunks:
                speaker_chunks[e.get("speaker_id", "")].append(e)

            # Step 3: sort each speaker's chunks by chunk quality
            def _chunk_quality(e):
                return 0.75 * e.get("similarity", 0.0) + 0.25 * (e.get("salience") or 0.0)

            for sid in speaker_chunks:
                speaker_chunks[sid].sort(key=_chunk_quality, reverse=True)

            # Step 4: rank speakers by authority (primary) + best chunk quality (secondary)
            def _speaker_rank(sid):
                auth = speaker_chunks[sid][0].get("authority_score", 0.0)
                best = _chunk_quality(speaker_chunks[sid][0])
                return 0.70 * auth + 0.30 * best

            sorted_speakers = sorted(speaker_chunks.keys(), key=_speaker_rank, reverse=True)

            if sorted_speakers and len(speaker_chunks) > 1:
                top_sid = sorted_speakers[0]
                top_auth = speaker_chunks[top_sid][0].get("authority_score", 0.0)
                top_best = _chunk_quality(speaker_chunks[top_sid][0])
                logger.info(
                    f"[PARTY RANKING] {party}: top speaker = "
                    f"{speaker_chunks[top_sid][0].get('speaker_name', top_sid)} "
                    f"(auth={top_auth:.2f}, best_chunk={top_best:.3f}, "
                    f"rank_score={_speaker_rank(top_sid):.3f}), "
                    f"total_speakers={len(sorted_speakers)}"
                )

            # Step 5: interleave: best from speaker#1, best from speaker#2, ...
            #                     then 2nd-best from speaker#1, 2nd-best speaker#2, ...
            max_depth = max(len(v) for v in speaker_chunks.values())
            interleaved = []
            for depth in range(max_depth):
                for sid in sorted_speakers:
                    evs = speaker_chunks[sid]
                    if depth < len(evs):
                        interleaved.append(evs[depth])

            by_party[party] = interleaved

        return by_party

    def _check_coalition_balance(
        self,
        text: str
    ) -> Dict[str, Any]:
        """Check word count balance between majority and opposition sections.

        Based on Coverage-based Fairness (NAACL 2025) equal coverage principle.
        Logs a warning if the ratio exceeds 2:1.

        Returns:
            Dictionary with word counts, ratio, and balance_warning flag.
        """
        majority_section = ""
        opposition_section = ""

        # Extract sections by header
        sections = re.split(r'##\s+', text)
        for section in sections:
            if section.startswith("Posizioni della Maggioranza"):
                majority_section = section
            elif section.startswith("Posizioni dell'Opposizione") or section.startswith("Posizioni dell\u2019Opposizione"):
                opposition_section = section

        majority_words = len(majority_section.split())
        opposition_words = len(opposition_section.split())

        # Compute ratio (avoid division by zero)
        if opposition_words > 0:
            ratio = majority_words / opposition_words
        elif majority_words > 0:
            ratio = float('inf')
        else:
            ratio = 1.0

        return {
            "majority_words": majority_words,
            "opposition_words": opposition_words,
            "ratio": round(ratio, 2),
            "balance_warning": ratio > 2.0 or (1 / ratio if ratio > 0 else 0) > 2.0,
        }

    # Short identifiers used to detect each party's name inside the generated text.
    # We use the first significant segment (before " - " or " (") as a reliable
    # distinguishing substring.  Checked case-insensitively.
    _PARTY_SHORT_NAMES = {
        "Fratelli d'Italia": "fratelli d'italia",
        "Lega - Salvini Premier": "lega",
        "Forza Italia - Berlusconi Presidente - PPE": "forza italia",
        "Noi Moderati (Noi con l'Italia, Coraggio Italia, UDC e Italia al Centro) - MAIE - Centro Popolare": "noi moderati",
        "Partito Democratico - Italia Democratica e Progressista": "partito democratico",
        "Movimento 5 Stelle": "movimento 5 stelle",
        "Alleanza Verdi e Sinistra": "alleanza verdi",
        "Azione - Popolari Europeisti Riformatori - Renew Europe": "azione",
        "Italia Viva - Casa Riformista": "italia viva",
        # Name in use before the summer 2026 rename
        "Italia Viva - Il Centro - Renew Europe": "italia viva",
        "Misto": "misto",
    }

    def _inject_missing_party_paragraphs(
        self,
        text: str,
        sections: List[Dict[str, Any]],
    ) -> tuple:
        """Check that every party with evidence is named in the integrated text.

        The Integrator LLM occasionally drops the mandatory "Per [Party Name],"
        prefix or uses an abbreviation.  When detected, the original section
        content (already carrying restored [CIT:id] markers) is appended to the
        correct coalition block so the output and the completeness metric are
        not penalised for a pure formatting failure.

        Returns:
            (possibly_modified_text, list_of_injected_party_names)
        """
        config = get_config()
        MAGGIORANZA = config.coalitions.get("maggioranza", [])
        OPPOSIZIONE = config.coalitions.get("opposizione", [])
        MISTO = config.coalitions.get("misto", [])

        text_lower = text.lower()
        magg_injections: List[str] = []
        opp_injections: List[str] = []
        misto_injections: List[str] = []
        injected: List[str] = []

        for section in sections:
            party = section.get("party", "")
            if party == "GOVERNO" or not section.get("has_evidence"):
                continue

            short = self._PARTY_SHORT_NAMES.get(party, party.split(" - ")[0]).lower()
            if short in text_lower:
                continue

            content = section.get("content", "")
            if not content:
                continue

            # Strip any leading ## headers the sectional writer may have added
            content = re.sub(r'^##\s+[^\n]*\n+', '', content.strip(), flags=re.MULTILINE)
            injected_para = f"Per {party}, {content}"

            if party in MAGGIORANZA:
                magg_injections.append(injected_para)
            elif party in OPPOSIZIONE:
                opp_injections.append(injected_para)
            elif party in MISTO:
                misto_injections.append(injected_para)

            injected.append(party)
            logger.warning(f"Party injection: '{party}' missing from integrated text — injecting original section")

        if not injected:
            return text, []

        # Append injected paragraphs inside the appropriate coalition section.
        if magg_injections:
            magg_header = "## Posizioni della Maggioranza"
            inject_block = "\n\n".join(magg_injections)
            if magg_header in text:
                # Insert before the next top-level section (## …) or at end of text
                magg_pos = text.find(magg_header)
                next_section = text.find("\n\n##", magg_pos + len(magg_header))
                if next_section > 0:
                    text = text[:next_section] + "\n\n" + inject_block + text[next_section:]
                else:
                    text = text + "\n\n" + inject_block
            else:
                text = text + f"\n\n{magg_header}\n\n{inject_block}"

        if opp_injections:
            opp_header = "## Posizioni dell\u2019Opposizione"
            opp_header_alt = "## Posizioni dell'Opposizione"
            inject_block = "\n\n".join(opp_injections)
            header_in_text = opp_header if opp_header in text else (opp_header_alt if opp_header_alt in text else None)
            if header_in_text:
                text = text + "\n\n" + inject_block
            else:
                text = text + f"\n\n{opp_header_alt}\n\n{inject_block}"

        if misto_injections:
            misto_header = "## Gruppo Misto"
            inject_block = "\n\n".join(misto_injections)
            if misto_header in text:
                text = text + "\n\n" + inject_block
            else:
                text = text + f"\n\n{misto_header}\n\n{inject_block}"

        return text, injected

    def _get_government_evidence(
        self,
        evidence_list: List[Dict[str, Any]],
        min_similarity: float = 0.35,
        max_per_speaker: int = 3,
    ) -> List[Dict[str, Any]]:
        """Get evidence from government members, ranked by speaker authority.

        Applies a minimum similarity threshold to exclude government members
        whose retrieved chunks are not topically relevant to the query.

        Uses speaker-first interleaving (same logic as _group_evidence_by_party)
        so the most authoritative minister's best chunk is always at position #1.
        This ensures the sectional writer cites the minister with greatest
        institutional relevance rather than the one with the highest chunk similarity.
        """
        from collections import defaultdict

        gov = [
            e for e in evidence_list
            if e.get("speaker_role") == "GovernmentMember"
            and e.get("similarity", 0.5) >= min_similarity
        ]

        if not gov:
            return []

        # Ensure salience is computed for all chunks
        # (index-time citability score if present, neutral 0.5 otherwise)
        for e in gov:
            if e.get("salience") is None:
                cit = e.get("citability_score")
                e["salience"] = float(cit) if cit is not None else 0.5

        # Group by speaker
        speaker_chunks: dict = defaultdict(list)
        for e in gov:
            speaker_chunks[e.get("speaker_id", "")].append(e)

        # Sort each speaker's chunks by chunk quality (similarity + salience)
        def _chunk_quality(e):
            return 0.75 * e.get("similarity", 0.0) + 0.25 * (e.get("salience") or 0.0)

        for sid in speaker_chunks:
            speaker_chunks[sid].sort(key=_chunk_quality, reverse=True)

        # Rank speakers: authority_score (primary) + best chunk quality (secondary)
        def _speaker_rank(sid):
            auth = speaker_chunks[sid][0].get("authority_score", 0.0)
            best = _chunk_quality(speaker_chunks[sid][0])
            return 0.70 * auth + 0.30 * best

        sorted_speakers = sorted(speaker_chunks.keys(), key=_speaker_rank, reverse=True)

        if sorted_speakers:
            top_sid = sorted_speakers[0]
            top_auth = speaker_chunks[top_sid][0].get("authority_score", 0.0)
            top_name = speaker_chunks[top_sid][0].get("speaker_name", top_sid)
            logger.info(
                f"[GOV RANKING] top speaker = {top_name} "
                f"(auth={top_auth:.2f}, rank={_speaker_rank(top_sid):.3f}), "
                f"total_ministers={len(sorted_speakers)}"
            )

        # Interleave: best from minister #1, best from #2, then 2nd-best #1, etc.
        # Respects max_per_speaker limit per minister.
        max_depth = max(len(v) for v in speaker_chunks.values())
        filtered = []
        for depth in range(max_depth):
            if depth >= max_per_speaker:
                break
            for sid in sorted_speakers:
                evs = speaker_chunks[sid]
                if depth < len(evs):
                    filtered.append(evs[depth])

        return filtered
