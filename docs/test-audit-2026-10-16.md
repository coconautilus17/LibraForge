# Test audit 2026-10-16

Scope: all 2,046 tests (app/tests, 156 files) against every production module. Nothing is deleted or changed by this audit; every item below is a candidate for your review.


## OUTCOME (after the fix pass, 2026-10-17)

Scope of the fix pass: tests only. **No production file was changed** (`git diff origin/main` outside `app/tests` is empty). Suite: 2,046 -> **3,558 tests**, all passing, 7 `expectedFailure` (each documents a real defect below). Run twice earlier to check for flakiness.

**Like-for-like metric (replay of the 1,025 original survivors against the new tests):** 655 of 1,048 mutants are now caught (**62%**). The rest are mostly long-tail line mutants in the two big scripts and main.py infrastructure, plus accepted equivalents.

**Fresh-sample metric (new random sample, so not directly comparable):** survival fell from 24.2% (1,025 of 4,242) to **12.1% (529 of 4,389)** across 40 modules.

Modules fully or nearly cleared in replay: tagging 10/10, conversion_discovery 14/14, chaptering_runner 8/8, explicit_evidence 4/4, genre_collections 2/2, pocketfm 1/1, progress_phases 3/3, source_matching 2/2, fixer/search 37/39, debug_trace 40/41, enrichment 14/15, enrichment_sources 21/22.
Still open (replay caught/total): main.py 43/147, fixer v5 script 71/151, organizer script 67/132, review-libraforge-report 43/64, chaptering 26/48, scoring 46/61, parsing 26/39, author_names 19/27, genre_voting 18/26, publisher_policy 11/17 (publisher_policy and genre_taxonomy remainders were hand-checked as equivalent).

Accepted equivalent mutants (recorded, not forced): cosmetic `indent=`, `mkdir(exist_ok)`, mtime sentinel `0`, schema_version constants, daemon-thread flags, clamp edges.

### Real defects found (each has a GitHub issue and an expectedFailure test)
- #373 `is_omnibus_product` misses "Books 1-3" and "Book 1 & 2".
- #374 `is_generic_series_number_title` never matches "Series - Book N".
- #375 `normalize_book_number("1.0")` returns "001.".
- #376 `strip_author_narrator_noise_from_title` leaves a two-author prefix.
- #377 `parse_book_folder_name` reads "Series - Book N - Title" as author=Series, series="Book" (confirmed end to end: such a folder is planned to `<lib>/Series/Book/Book N - Title`).
- #378 `find_marker_candidates`: the END_OF_RE guard can never fire.
- #379 `restore_metadata_backups` raises NameError (`manual_review` undefined) on the first failed file and aborts the restore run.

Quirks noted but not asserted: `smart_title_case("THE (LAST) ONE")` drops a space; `parse_number("one two three four")` returns 6; `resource_guard_message` prints "None GB" for a missing key; `expand_report_categories` crashes on `items=None`; `abs_search` duplicates `_abs_match_to_product` inline (without language).

### Duplicated-code parity
The organizer and fixer scripts each carry copies of the 13 multi-part detection functions; the multi-part suite now runs against both copies. The fixer's `summarize_audio_stream_properties` duplicates `conversion_discovery.summarize_audio_probes`; a parity test covers it. Per the reuse-first rule these are consolidation candidates, not done here.

### B3 smells: status
All listed smells were fixed in tests (self-comparisons, truthy-only checks, catch-all `assertRaises`, swallowed-subject test). Mock-call-only tests were left where "was X called" is the intent.

### Still needs your decision (A)
The dead-code tests below are untouched; see section A.

---

## Method

1. **Mutation pass (B, false positives).** For each module an AST mutator changed one covered line at a time (flipped a comparison, swapped and/or, negated an `if`/`not`, replaced a return value with `None`, flipped a boolean, bumped an int, swapped +/-). Only tests that cover the mutated line (from per-test coverage) were run. A mutant that no test catches is a SURVIVOR: the code was made wrong and the suite stayed green. Timeouts count as caught.
2. **Structure scan (B).** AST scan of every test method for no assertions, assert-on-constant, self-equal assertions, mock-call-only assertions, broad assertRaises, and duplicate or shadowed test bodies.
3. **Dead-subject scan (A).** Functions that production never calls but tests do, plus skip conditions.

## Headline numbers

- Mutants tried: 3742 (sampled up to 150 per module, 400 for the two big scripts). Caught: 2861 (76%). **Survived: 881.**
- Not all survivors are test faults: some mutants are equivalent (the change does not alter behavior, e.g. `0` to `1` in a clamp, `and`/`or` on already exclusive conditions). The ranking below puts the likely real gaps first.
- No test has zero assertions, no test body is duplicated, no method is shadowed or silently never run, and none of the 2,046 tests is skipped in the project container (ffmpeg and quickjs are present). Outside the container, 12 skip conditions (ffmpeg, ffprobe, quickjs) would silently skip tests; I did not count how many.

## Per-module survival (worst first)

| Module | Sites | Tried | Caught | Survived | Survival |
|---|---|---|---|---|---|
| scripts/review-libraforge-report.py | 371 | 150 | 88 | 62 | 41% |
| app/fixer/scoring.py | 755 | 150 | 89 | 61 | 40% |
| app/chaptering_runner.py | 20 | 20 | 12 | 8 | 40% |
| scripts/audible-metadata-fixer-v5.py | 1154 | 400 | 250 | 150 | 37% |
| app/debug_trace.py | 118 | 118 | 77 | 41 | 34% |
| scripts/organize-audiobooks-by-metadata-v3_13.py | 2141 | 400 | 272 | 128 | 32% |
| app/fixer/clues.py | 116 | 116 | 79 | 37 | 31% |
| app/chaptering.py | 430 | 150 | 103 | 47 | 31% |
| app/folder_scan_cache.py | 20 | 20 | 14 | 6 | 30% |
| app/fixer/search.py | 132 | 132 | 93 | 39 | 29% |
| app/conversion_discovery.py | 51 | 51 | 37 | 14 | 27% |
| app/fixer/parsing.py | 594 | 150 | 114 | 36 | 24% |
| app/author_names.py | 117 | 117 | 91 | 26 | 22% |
| app/genre_voting.py | 120 | 120 | 94 | 26 | 21% |
| app/title_noise_policy.py | 115 | 40 | 32 | 8 | 20% |
| app/enrichment_batch.py | 94 | 94 | 77 | 17 | 18% |
| app/goodreads_shelves.py | 104 | 104 | 86 | 18 | 17% |
| app/fixer/tagging.py | 58 | 58 | 48 | 10 | 17% |
| app/conversion_cache.py | 41 | 41 | 34 | 7 | 17% |
| app/enrichment_sources.py | 261 | 150 | 128 | 22 | 14% |
| app/publisher_policy.py | 120 | 120 | 104 | 16 | 13% |
| scripts/normalize-author-names.py | 128 | 128 | 111 | 17 | 13% |
| app/explicit_evidence.py | 31 | 31 | 27 | 4 | 12% |
| scripts/fix-series-book-number-suffix.py | 235 | 150 | 131 | 19 | 12% |
| app/library_index.py | 49 | 49 | 43 | 6 | 12% |
| app/source_matching.py | 17 | 17 | 15 | 2 | 11% |
| app/genre_taxonomy.py | 137 | 137 | 122 | 15 | 10% |
| app/enrichment.py | 350 | 150 | 135 | 15 | 10% |
| app/install_state.py | 41 | 41 | 37 | 4 | 9% |
| app/sidecar_ownership.py | 22 | 22 | 20 | 2 | 9% |
| app/abs_client.py | 303 | 150 | 138 | 12 | 8% |
| app/progress_phases.py | 41 | 41 | 38 | 3 | 7% |
| app/genre_collections.py | 38 | 38 | 36 | 2 | 5% |
| app/pocketfm.py | 52 | 52 | 51 | 1 | 1% |
| app/epub_metadata.py | 9 | 9 | 9 | 0 | 0% |
| app/m4b_naming.py | 14 | 14 | 14 | 0 | 0% |
| app/manual_candidates.py | 4 | 4 | 4 | 0 | 0% |
| app/manual_review.py | 5 | 5 | 5 | 0 | 0% |
| app/settings_paths.py | 3 | 3 | 3 | 0 | 0% |

## B1. Strongest false-positive evidence

Survivors where a condition was negated or a return value replaced and nothing failed. Format: `file:line  mutated expression  (tests covering the line)`.

- `app/abs_client.py:63` ifneg: `if qs:` (1 test, e.g. test_manual_review_ebook_endpoints.EbookApplyEndpointTests.test_abs_index_hit_patches_directly)
- `app/conversion_discovery.py:60` ifneg: `if mixed['sample_rate']:` (1 test, e.g. test_conversion_discovery.ConversionDiscoveryTests.test_mixed_sample_rate_recommends_conversion)
- `app/conversion_discovery.py:62` ifneg: `if mixed['channels']:` (1 test, e.g. test_conversion_discovery.ConversionDiscoveryTests.test_mixed_sample_rate_recommends_conversion)
- `app/debug_trace.py:88` ifneg: `if self._fh is not None:` (1 test, e.g. test_debug_trace.DebugTraceTest.test_file_sink_writes)
- `app/fixer/parsing.py:395` ifneg: `if not value:` (1 test, e.g. test_metadata_sanitization.MetadataTitleFallbackTests.test_loose_root_file_title_is_not_corrupted_by_scan_root_folder_name)
- `app/fixer/parsing.py:1195` not: `not is_generic_chapter_title(left)` (1 test, e.g. test_fixer_v5_run_failures.PartNumbersAreNotABookNumberTests.test_distinct_part_numbers_give_no_book_number_or_series)
- `app/fixer/scoring.py:675` ifneg: `if duration['status'] not in {'perfect', 'strong'}:` (1 test, e.g. test_fixer_v5_scoring.RecurringSubtitleSequenceConflictTests.test_large_sequence_gap_in_same_series_is_a_conflict)
- `app/fixer/tagging.py:293` ifneg: `if metadata.get('isbn'):` (1 test, e.g. test_fixer_v5_publisher.PublisherWriteTests.test_metadata_carries_publisher)
- `app/fixer/tagging.py:287` ifneg: `if metadata.get('asin'):` (1 test, e.g. test_fixer_v5_publisher.PublisherWriteTests.test_metadata_carries_publisher)
- `app/fixer/tagging.py:284` ifneg: `if metadata.get('sequence'):` (1 test, e.g. test_fixer_v5_publisher.PublisherWriteTests.test_metadata_carries_publisher)
- `app/fixer/tagging.py:290` ifneg: `if metadata.get('write_summary') and metadata.get('summary'):` (1 test, e.g. test_fixer_v5_publisher.PublisherWriteTests.test_metadata_carries_publisher)
- `scripts/audible-metadata-fixer-v5.py:2816` ifneg: `if use_backup_tags:` (1 test, e.g. test_fixer_v5_run_failures.TagProbeTests.test_empty_cached_snapshot_is_not_trusted)
- `scripts/fix-series-book-number-suffix.py:821` ifneg: `if not rows:` (1 test, e.g. test_fix_series_book_number_suffix.PlanAllChangesViaAbsApiTests.test_cli_reads_credentials_from_a_config_file_not_the_command_line)
- `scripts/fix-series-book-number-suffix.py:657` not: `not sequence` (1 test, e.g. test_fix_series_book_number_suffix.AbsSeriesCleanupTests.test_bare_number_needs_corroboration)
- `scripts/organize-audiobooks-by-metadata-v3_13.py:5004` ifneg: `if not alias_norm or not source_norm.startswith(alias_norm):` (1 test, e.g. test_organizer_routing_naming.CrossAuthorSeriesGuardTests.test_prefix_fallback_rejects_foreign_author)
- `scripts/organize-audiobooks-by-metadata-v3_13.py:5103` not: `not trusted` (1 test, e.g. test_organizer_dry_run_review_fixes.BracketOnlyTitleTests.test_trusted_sidecar_title_that_is_only_a_tag_falls_back_to_the_sequence)
- `scripts/organize-audiobooks-by-metadata-v3_13.py:3448` ifneg: `if parsed_narrator:` (1 test, e.g. test_organizer_v3_7.OrganizerMetadataInferenceTests.test_clean_author_series_volume_path_supplies_all_path_clues)
- `scripts/organize-audiobooks-by-metadata-v3_13.py:1166` ifneg: `if int(first) >= int(second):` (1 test, e.g. test_organizer_naming_default_parity.DefaultTemplateParityTests.test_matches_build_default_target_dir_for_every_case)
- `scripts/organize-audiobooks-by-metadata-v3_13.py:2848` not: `not plausible_author_credit(first)` (1 test, e.g. test_metadata_sanitization.MetadataTitleFallbackTests.test_organizer_matches_fixer_for_identity_rich_folder_names)
- `scripts/organize-audiobooks-by-metadata-v3_13.py:2085` ifneg: `if result.returncode != 0:` (1 test, e.g. test_organizer_sidecar_extended_fields.InferMetadataExtendedFieldsTests.test_infer_metadata_defaults_extended_fields_to_empty)
- `scripts/review-libraforge-report.py:1197` ifneg: `if explicit_kind in {'metadata_fixer', 'fixer'}:` (1 test, e.g. test_review_libraforge_report.AddSeriesGroupSuspectsTests.test_extract_suspects_includes_series_groups)
- `scripts/review-libraforge-report.py:662` not: `not is_folder_like_series(local.get('series', ''))` (1 test, e.g. test_review_libraforge_report.AddSeriesGroupSuspectsTests.test_extract_suspects_includes_series_groups)
- `app/fixer/parsing.py:941` not: `not looks_like_person_name(last)` (2 tests, e.g. test_fixer_v5_title_recovery.TitleSeriesBareNumberParseTests.test_existing_book_keyword_format_still_parses)
- `app/genre_voting.py:143` ifneg: `if min(fantasy, scifi) < 0.5 * max(fantasy, scifi):` (2 tests, e.g. test_enrichment.CompileSeriesEnrichmentTests.test_evidence_note_counts_significant_goodreads_explicit_shelving)
- `scripts/audible-metadata-fixer-v5.py:4771` not: `not is_supported_audio_file(root)` (2 tests, e.g. test_m4b_discovery_staleness.M4BDiscoveryStalenessTests.test_file_target_path_scopes_signature_to_parent_folder_not_the_file)
- `scripts/fix-series-book-number-suffix.py:693` ifneg: `if 'UNCERTAIN' in kinds:` (2 tests, e.g. test_fix_series_book_number_suffix.AbsSeriesCleanupTests.test_duplicate_after_cleaning_collapses_into_one_entry)
- `scripts/fix-series-book-number-suffix.py:695` ifneg: `if 'FILL_SEQUENCE' in kinds:` (2 tests, e.g. test_fix_series_book_number_suffix.AbsSeriesCleanupTests.test_duplicate_after_cleaning_collapses_into_one_entry)
- `scripts/normalize-author-names.py:289` ifneg: `if abs_entries:` (2 tests, e.g. test_normalize_author_names.ApplyAndRevertTests.test_apply_then_revert_restores_everything)
- `scripts/organize-audiobooks-by-metadata-v3_13.py:1948` ifneg: `if candidate and (not title_is_bad_after_cleanup(candidate)):` (2 tests, e.g. test_organizer_dry_run_review_fixes.SequenceOnlyNoteIsNotFlaggedForNoiseTests.test_path_title_that_is_only_author_and_asin_noise_adds_no_review_reason)
- `scripts/organize-audiobooks-by-metadata-v3_13.py:1913` ifneg: `if longer and shorter / longer >= 0.75:` (2 tests, e.g. test_organizer_naming_template_endpoints.ExamplePreviewEndpointTests.test_filename_cleanup_visible_on_bundled_examples)
- `scripts/organize-audiobooks-by-metadata-v3_13.py:3704` not: `not is_marketing_descriptor(path_title)` (2 tests, e.g. test_organizer_naming_template_endpoints.ExamplePreviewEndpointTests.test_filename_cleanup_visible_on_bundled_examples)
- `scripts/organize-audiobooks-by-metadata-v3_13.py:3427` not: `not clues.get('book_folder_author_series')` (2 tests, e.g. test_organizer_v3_7.OrganizerMetadataInferenceTests.test_clean_author_series_volume_path_supplies_all_path_clues)
- `scripts/review-libraforge-report.py:582` not: `not local_seq` (2 tests, e.g. test_review_libraforge_report.ReviewMetadataItemMissingFieldsTests.test_present_series_is_not_flagged)
- `scripts/review-libraforge-report.py:272` ifneg: `if not re.fullmatch('\\d{1,2}(?:\\.\\d+)?', tail):` (2 tests, e.g. test_review_libraforge_report.ReviewMetadataItemMissingFieldsTests.test_present_series_is_not_flagged)
- `app/chaptering.py:2448` ifneg: `if transcript:` (3 tests, e.g. test_chapter_forge_audible_backend.RunAudibleChaptersBackendTests.test_asin_auto_resolved_from_sidecar_when_not_overridden)
- `app/chaptering.py:2371` not: `not review` (3 tests, e.g. test_chapter_forge_audible_backend.RunAudibleChaptersBackendTests.test_asin_auto_resolved_from_sidecar_when_not_overridden)
- `app/chaptering.py:2446` ifneg: `if srt:` (3 tests, e.g. test_chapter_forge_audible_backend.RunAudibleChaptersBackendTests.test_asin_auto_resolved_from_sidecar_when_not_overridden)
- `scripts/organize-audiobooks-by-metadata-v3_13.py:4910` ifneg: `if cache_entry.get('series'):` (3 tests, e.g. test_organizer_naming_validation_and_wiring.BuildCachedTargetDirNamingTemplateTests.test_existing_cache_match_applies_canonical_author_correction_to_template)
- `scripts/organize-audiobooks-by-metadata-v3_13.py:1842` ifneg: `if normalize_for_compare(remainder) == normalize_for_compare(value):` (3 tests, e.g. test_organizer_bracketed_standalone_clue.NarratorClueTitleCorruptionTests.test_series_title_survives_when_marker_narrator_is_empty)
- `scripts/organize-audiobooks-by-metadata-v3_13.py:1838` ifneg: `if not value or not series:` (3 tests, e.g. test_organizer_bracketed_standalone_clue.NarratorClueTitleCorruptionTests.test_series_title_survives_when_marker_narrator_is_empty)
- `scripts/review-libraforge-report.py:339` ifneg: `if _MULTI_BOOK_KW.search(part):` (3 tests, e.g. test_review_libraforge_report.AddSeriesGroupSuspectsTests.test_no_series_groups_when_nothing_qualifies)
- `app/chaptering.py:2211` ifneg: `if not review.get('parse_error'):` (4 tests, e.g. test_chaptering_credits_check.DetectChaptersHybridCreditsCheckDecouplingTests.test_credits_check_survives_when_main_review_call_raises)
- `app/chaptering.py:2305` ifneg: `if _ABS_CONFIG_FILE.exists():` (4 tests, e.g. test_chaptering_credits_check.ResolveBookCreditsTests.test_falls_back_to_metadata_json_authors_narrators_lists)
- `app/fixer/clues.py:125` ifneg: `if path_meta.get('book_number'):` (4 tests, e.g. test_fixer_v5_current_metadata.BuildSearchContextCurrentIsolationTests.test_path_override_changes_clues_but_not_current)
- `app/fixer/scoring.py:1722` ifneg: `if clues.get('title') and title_score < 0.55:` (4 tests, e.g. test_enrichment_sources.AudioSiloTests.test_asin_miss_falls_back_to_title)
- `app/fixer/tagging.py:260` ifneg: `if value:` (4 tests, e.g. test_fixer_v5_field_policy.Mp3FieldPolicyTests.test_fill_leaves_every_blank_field_untouched)
- `scripts/audible-metadata-fixer-v5.py:2173` not: `not probe.get('channels')` (4 tests, e.g. test_fixer_v5_field_policy.M4bToolSidecarAsinFieldPolicyTests.test_fill_preserves_current_asin_when_blank)
- `scripts/audible-metadata-fixer-v5.py:713` ifneg: `if group_search.get('applied'):` (4 tests, e.g. test_fixer_v5_field_policy.M4bToolSidecarAsinFieldPolicyTests.test_fill_preserves_current_asin_when_blank)
- `scripts/audible-metadata-fixer-v5.py:2134` ifneg: `if profile and profile.lower() not in codec_label.lower():` (4 tests, e.g. test_fixer_v5_field_policy.M4bToolSidecarAsinFieldPolicyTests.test_fill_preserves_current_asin_when_blank)
- `scripts/audible-metadata-fixer-v5.py:1563` ifneg: `if backup:` (4 tests, e.g. test_fixer_v5_field_policy.Mp3FieldPolicyTests.test_fill_leaves_every_blank_field_untouched)
- `scripts/audible-metadata-fixer-v5.py:5462` ifneg: `if workers and workers > 1:` (4 tests, e.g. test_fixer_v5_dup_asin.BuildDiskAsinMapTests.test_falls_back_to_media_probe)
- `scripts/fix-series-book-number-suffix.py:576` ifneg: `if include_tags and folder.is_dir():` (4 tests, e.g. test_fix_series_book_number_suffix.PlanAllChangesViaAbsApiTests.test_matches_the_walk_based_result_for_the_same_library)
- `scripts/organize-audiobooks-by-metadata-v3_13.py:1966` not: `not re.search('[#\\d]', inner)` (4 tests, e.g. test_organizer_trusted_title_parenthetical_series.GenericEditionDescriptorParentheticalTests.test_book_folder_name_drops_series_completion_tag)
- `app/chaptering.py:250` ifneg: `if ms >= 1000:` (5 tests, e.g. test_chaptering_credits_check.BuildHybridLlmPromptHasNoCreditsRequestTests.test_main_review_prompt_never_mentions_credits_check)
- `app/chaptering.py:924` ifneg: `if not chapters:` (5 tests, e.g. test_chapter_forge_sos_numbers_only.DetectChaptersHybridNumbersOnlyTests.test_sos_numbers_only_kwarg_reaches_run_sound_of_silence)
- `app/enrichment_sources.py:381` not: `not str(h.get('title', '')).endswith('(Series)')` (5 tests, e.g. test_enrichment_sources.BatchReadinessTests.test_haremlit_checks_at_most_three_author_pages)
- `app/fixer/search.py:414` ifneg: `if _attempt < max(1, retries) - 1:` (5 tests, e.g. test_fixer_v5_abs_tract.AbsTractBreakerTests.test_breaker_opens_after_threshold_and_short_circuits)
- `app/fixer/search.py:507` ifneg: `if not hasattr(_thread_local, 'client'):` (5 tests, e.g. test_fixer_v5_abs_metadata_input_modes.SearchItemAbsInputModesTests.test_trust_mode_lookup_miss_does_not_short_circuit)
- `app/fixer/search.py:507` not: `not hasattr(_thread_local, 'client')` (5 tests, e.g. test_fixer_v5_abs_metadata_input_modes.SearchItemAbsInputModesTests.test_trust_mode_lookup_miss_does_not_short_circuit)
- `scripts/audible-metadata-fixer-v5.py:1355` ifneg: `while offset + 8 <= file_size:` (5 tests, e.g. test_fixer_v5_field_policy.Mp4FieldPolicyTests.test_fill_leaves_every_blank_field_untouched)
- `scripts/audible-metadata-fixer-v5.py:3835` ifneg: `if skip_due_to_pattern:` (5 tests, e.g. test_fixer_v5_abs_metadata_input_modes.SearchItemAbsInputModesTests.test_trust_mode_lookup_miss_does_not_short_circuit)
- `scripts/audible-metadata-fixer-v5.py:5096` not: `not patterns` (5 tests, e.g. test_fixer_v5_abs_metadata_input_modes.SearchItemAbsInputModesTests.test_trust_mode_lookup_miss_does_not_short_circuit)
- `scripts/audible-metadata-fixer-v5.py:3958` ifneg: `if use_abs:` (5 tests, e.g. test_fixer_v5_abs_metadata_input_modes.SearchItemAbsInputModesTests.test_trust_mode_lookup_miss_does_not_short_circuit)
- `scripts/audible-metadata-fixer-v5.py:1373` ifneg: `if atom_size < header_size:` (5 tests, e.g. test_fixer_v5_field_policy.Mp4FieldPolicyTests.test_fill_leaves_every_blank_field_untouched)
- `scripts/audible-metadata-fixer-v5.py:5072` not: `not folders` (5 tests, e.g. test_fixer_v5_abs_metadata_input_modes.SearchItemAbsInputModesTests.test_trust_mode_lookup_miss_does_not_short_circuit)
- `scripts/audible-metadata-fixer-v5.py:1378` ifneg: `if len(atoms) == 2:` (5 tests, e.g. test_fixer_v5_field_policy.Mp4FieldPolicyTests.test_fill_leaves_every_blank_field_untouched)
- `scripts/audible-metadata-fixer-v5.py:1525` ifneg: `if layout['metadata_before_media']:` (5 tests, e.g. test_fixer_v5_field_policy.Mp4FieldPolicyTests.test_fill_leaves_every_blank_field_untouched)
- `scripts/audible-metadata-fixer-v5.py:5096` ifneg: `if not patterns:` (5 tests, e.g. test_fixer_v5_abs_metadata_input_modes.SearchItemAbsInputModesTests.test_trust_mode_lookup_miss_does_not_short_circuit)
- `scripts/organize-audiobooks-by-metadata-v3_13.py:5064` not: `not title_key` (5 tests, e.g. test_organizer_dry_run_review_fixes.LeadingSequenceLabelTests.test_folder_name_is_then_just_the_sequence)
- `scripts/review-libraforge-report.py:502` ifneg: `if status == 'matched':` (5 tests, e.g. test_review_libraforge_report.ReviewMetadataItemMissingFieldsTests.test_missing_series_is_flagged)
- `scripts/review-libraforge-report.py:269` ifneg: `if not value_n.startswith(series_n + ' '):` (5 tests, e.g. test_review_libraforge_report.ReviewMetadataItemMissingFieldsTests.test_present_series_is_not_flagged)
- `scripts/review-libraforge-report.py:517` not: `not already_flagged_for_skip` (5 tests, e.g. test_review_libraforge_report.ReviewMetadataItemMissingFieldsTests.test_missing_series_is_flagged)
- `scripts/review-libraforge-report.py:603` not: `not is_folder_like_series(local_series)` (5 tests, e.g. test_review_libraforge_report.ReviewMetadataItemMissingFieldsTests.test_missing_series_is_flagged)
- `scripts/review-libraforge-report.py:553` not: `not is_gr` (5 tests, e.g. test_review_libraforge_report.ReviewMetadataItemMissingFieldsTests.test_missing_series_is_flagged)
- `scripts/audible-metadata-fixer-v5.py:1180` not: `not common` (6 tests, e.g. test_fixer_v5_leading_ordinal_grouping.LeadingOrdinalGroupMapTests.test_distinct_full_books_are_not_grouped_even_when_contiguous)
- `scripts/audible-metadata-fixer-v5.py:3771` ifneg: `if group_search.get('applied'):` (6 tests, e.g. test_fixer_v5_abs_metadata_input_modes.SearchItemAbsInputModesTests.test_trust_mode_lookup_hit_uses_abs_data_directly)
- `scripts/audible-metadata-fixer-v5.py:3701` ifneg: `if existing_marker:` (6 tests, e.g. test_fixer_v5_abs_metadata_input_modes.SearchItemAbsInputModesTests.test_trust_mode_lookup_hit_uses_abs_data_directly)
- `scripts/organize-audiobooks-by-metadata-v3_13.py:2334` not: `not common` (6 tests, e.g. test_organizer_naming_template_endpoints.ExamplePreviewEndpointTests.test_filename_cleanup_visible_on_bundled_examples)
- `scripts/review-libraforge-report.py:1149` not: `not title` (6 tests, e.g. test_review_libraforge_report.ReviewOrganizerItemInfoOnlyReasonTests.test_a_real_reason_alongside_an_informational_one_still_becomes_a_suspect)
- `scripts/review-libraforge-report.py:1155` ifneg: `if series and title and (len(series) > 10):` (6 tests, e.g. test_review_libraforge_report.ReviewOrganizerItemInfoOnlyReasonTests.test_a_real_reason_alongside_an_informational_one_still_becomes_a_suspect)

Showing 80 of 323; the full list is in the appendix file.

## B2. Lines guarded by a single test

162 of the 881 survivors sit on lines exactly one test covers; if that test is weak there is no second chance. Worst offenders by file:

- scripts/organize-audiobooks-by-metadata-v3_13.py: 31
- app/debug_trace.py: 25
- scripts/audible-metadata-fixer-v5.py: 24
- app/fixer/scoring.py: 10
- app/fixer/parsing.py: 9
- app/chaptering_runner.py: 8
- scripts/review-libraforge-report.py: 7
- app/fixer/search.py: 6
- scripts/fix-series-book-number-suffix.py: 6
- app/fixer/tagging.py: 5

## B3. Structural smells

- 9 tests assert only on mock calls, no result (test_abs_bootstrap_reconcile_loop x2, test_fix_series_book_number_suffix, test_fixer_search_chapters x2, test_library_download_activation_bytes x2, test_run_guards, test_run_script_worker_ebook_items). Plausibly fine as 'was X called' tests, but they cannot detect wrong output.
- 9 tests use only weak assertions (`assertIsNotNone`/`assertTrue(name)`): test_organizer_skip_patterns x4 (matches_*_field), test_scan_completeness x2, test_m4b_discovery_staleness, test_organizer_dry_run_review_fixes, test_organizer_naming_validation_and_wiring.
- 3 `assertEqual(x, x)`-shaped checks: test_conversion_cache.test_search_key_is_stable_and_scoped, test_folder_scan_cache.test_cache_key_is_stable_for_same_inputs, test_fixer_v5_name_noise.test_real_title_words_survive. 'Stable' tests compare a call to itself; they only prove determinism, not correctness.
- test_manual_review_apply.WritePolicyTests.test_invalid_write_policy_is_rejected uses `assertRaises(Exception)`: passes on any error, including a typo.
- 1 test swallows its subject: test_abs_bootstrap_reconcile_loop.test_exception_during_reconcile_is_swallowed has no assertion.

## A. Candidates that look unnecessary now

- Tests of functions production never calls: `_owned_asins_for_folder` (app/main.py:7749, 4 tests in test_asin_cache.py), `abs_client.remove_bootstrapped_file` (2 tests in test_abs_client.py), `looks_like_multi_file_book` (organizer script, ~11 tests in test_organizer_v3_7.py and test_fixer_v5_ogg_grouping.py). Either the code is dead (delete code and tests) or the call site was lost in a refactor (a bug). Needs a decision per function.
- Test helpers `reset_state_for_tests` and `_reset_enrichment_items_cache_for_tests` are test-only by design, not findings.
- Coverage redundancy: 274 groups (748 tests) hit the exact same production lines, but most are intentional table-style cases; I would not delete on that signal alone.

## Caveats

- Mutants are line-level and sampled, so survivor counts are a lower bound for big modules.
- Interim sections below (headline numbers, per-module table, B1-B3) are the BEFORE state as of the first run; the OUTCOME section above supersedes them.
- Survivors have NOT been hand-triaged for equivalence yet. Treat B1 as a ranked lead list, not a verified list of broken tests.

