> Ported after CP20/CP21 were verified in origin/main at 85bfebe. This is the preparation design; implementation evidence and changes are tracked in CHECKPOINTS.md.

# CP22 preparation: announcement authoring in a shop bot

Prepared 2026-10-11 (Asia/Tashkent). Scope: design and standalone text-processing code only. CP20/CP21 are being implemented in another session. Start repository integration only after the user reports that CP21 is pushed to main, then verify the commit and re-read the resulting contracts. All artifacts here belong in `D:\Coding projects\gulbot-cp22-prep`; neither project is modified.

## 1. Evidence from editor pro (read-only)

Exact project: `D:\Coding projects\editor pro`. Inspected AGENTS.md, requirements.txt/requirements.lock.txt, style/style.json, scripts/transcribe.py, scripts/bench_whisper.py, scripts/hardware.py, docs/AGENT_MEMORY.md, style/notes.md, and existing comparison/benchmark reports. No scripts from that project were executed or imported. No media was copied or transcribed.

- Engine: faster-whisper **1.2.1**, CTranslate2 **4.8.2**, PyAV **18.1.0** in its lock file. Default model is multilingual `small`; configured language `uz`, beam 5, VAD enabled, 4 CPU threads. Actual current device/compute settings are `auto`; hardware.py resolves these to CPU/int8 when CUDA is unavailable. Do not misreport `auto` as a hardcoded CPU setting.
- Audio conversion: FFmpeg argv, `-hide_banner -nostdin -loglevel error -y -i INPUT -vn -ac 1 -ar 16000 -c:a pcm_s16le OUTPUT.wav`; optional duration cap. This is appropriate for Telegram OGG/Opus as well as video. Use a new private temporary directory and local input files in CP22.
- Transcription: language forced, word timestamps, VAD minimum silence 300 ms, condition_on_previous_text=False, optional initial prompt/hotwords. Consume the returned segments generator: model.transcribe alone does not perform the whole job. Word probabilities and timing checks support review; neither establishes field correctness.
- Operational ideas: cached/local model loading, metadata-only download sizing, disk/RAM/commit headroom checks, CPU fallback, low-confidence word reporting, glossary corrections and owner approval. CP22 needs explicit CPU/int8 and two threads initially so STT does not monopolize the server.
- No root code licence was found in this project. Reuse the architecture and operational lessons; the preparation modules are newly written, without copying its source. A future source-code reuse needs explicit licence provenance.
- The video pipeline retains WAV/word JSON/SRT for editing; CP22 must instead delete both original OGG and converted WAV in finally, on failures and successful transcription. Adopt neither long-lived voice files nor the video pipeline's retention policy.

Existing local evidence (not rerun; settings/hardware at recording time are not fully captured):

| Recording/report | Model | Audio | Load | Inference | Audio/inference | What it establishes |
|---|---|---:|---:|---:|---:|---|
| temp/whisper_bench.json, English speed test | small | 25.8 s | 3.1 s | 5.68 s | 4.54x | The engine works on English; no Uzbek accuracy conclusion |
| temp/compare/first_video_for_editor_pro/compare.json, Uzbek clip | small | 61.372 s | 5.06 s | 79.38 s | 0.77x | Real Uzbek run with 0 timing issues; text in comparison is visibly poor |
| Same Uzbek clip | yuldashev222/whisper-small-uz-v1-ct2 | 61.372 s | 5.9 s | 127.24 s | 0.48x | Real fine-tune run with 0 timing issues; slower |

The 2026-10-07 AGENT_MEMORY entry reports that the fine-tune transcribed the Uzbek clip much better and generic small garbled it. This is a recorded human/project judgement, not an independently measured WER. `different_words` is disagreement between hypotheses, NOT accuracy. No labelled bouquet/price recordings were found in the inspected evidence. Existing Uzbek video evidence is useful; a CP22 domain benchmark still requires the owner's 10 recordings. Do not repurpose private video recordings without asking.

The existing cached CT2 snapshot `2a14636265bdb33c58cbb7c5b16447882c6676f4` has a 967,072,097-byte model.bin and ~5.0 MB supporting files (~972 MB total). Only directory/file metadata was read. No weights were loaded, copied, hashed or downloaded.

## 2. STT shortlist, licences and resource budget

All sizes below are decimal MB/GB of weights plus small tokenizer/config files, not installed runtime dependencies. Runtime RAM is separate. Metadata/licences checked on 2026-10-11. Verify and pin exact revisions, LICENSE/NOTICE and checksums when downloads are authorized. No downloads or fresh model benchmarks were performed during preparation.

| Engine + model | Commercial-use licence evidence | Planned download | CPU worker RAM | Accuracy / latency evidence | Role |
|---|---|---:|---|---|---|
| faster-whisper + Systran/faster-whisper-small (multilingual) | MIT engine and MIT model card | ~486 MB total | upstream benchmark 1,477 MB, int8, unbatched, beam 5; reserve 2-2.5 GiB | Uzbek local clip above; not a flower benchmark | Mandatory baseline |
| faster-whisper + Systran/faster-whisper-base (multilingual) | MIT model card | ~148 MB | estimate 0.5-1 GiB; measure | Domain accuracy unknown; expected faster from smaller size, not measured | Low-memory comparator |
| faster-whisper + Systran/faster-whisper-tiny (multilingual) | MIT model card | ~78.2 MB | estimate 0.3-0.7 GiB; measure | Domain accuracy unknown | Emergency resource comparator |
| faster-whisper + yuldashev222/whisper-small-uz-v1-ct2, converted from OvozifyLabs/whisper-small-uz-v1 | Both model cards Apache-2.0; original cards allow commercial use under that licence | ~972 MB, verified from existing cache metadata; full-precision CT2 on disk | estimate 1.5-2.5 GiB at CPU/int8, allow extra cold-load peak; measure | Project's Uzbek clip much better, ~2.1x audio duration; no field accuracy score | Provisional primary candidate |
| faster-whisper + OvozifyLabs/whisper-small-uz-v1 converted ourselves to CT2 int8 | Apache-2.0 source card | ~967 MB safetensors + tokenizer; quantized output estimate 250-350 MB | estimate 1.5-2.5 GiB runtime, substantially more memory for conversion; convert on a separate capable host later | Same underlying fine-tune, NOT an independent second model | Reproducible smaller deployment build |
| faster-whisper + navai-uz/whisper-small-uzbek converted to CT2 int8 | Apache-2.0 stated explicitly in its model card | raw FP32 estimate ~0.98 GB (244M parameters x 4 bytes); exact file total pending metadata; converted estimate 250-350 MB | estimate 1.5-2.5 GiB runtime; conversion needs separate headroom | Publisher reports CV22 WER 9.58%, FLEURS 16.96%; these do not predict bouquet fields | Independent Uzbek fine-tune comparator |
| Vosk + vosk-model-small-uz-0.22 | Official model list: Apache-2.0 | 49 MB ZIP; expanded disk size pending | Vosk's generic small-model guidance ~300 MB; budget 0.3-0.6 GiB worker | Official CV WER 13.54%, USC 12.92%; no local timings or domain result | Mandatory low-memory competitor |

Sources: [faster-whisper CPU benchmark and MIT](https://github.com/SYSTRAN/faster-whisper), [small files/MIT](https://huggingface.co/Systran/faster-whisper-small/tree/main), [base files/MIT](https://huggingface.co/Systran/faster-whisper-base/tree/main), [tiny files/MIT](https://huggingface.co/Systran/faster-whisper-tiny/tree/main), [CT2 card and conversion provenance](https://huggingface.co/yuldashev222/whisper-small-uz-v1-ct2), [Ovozify card](https://huggingface.co/OvozifyLabs/whisper-small-uz-v1), [Ovozify files](https://huggingface.co/OvozifyLabs/whisper-small-uz-v1/tree/main), [NavAI card/licence](https://huggingface.co/navai-uz/whisper-small-uzbek), [Vosk models](https://alphacephei.com/vosk/models).

Decision: use the local **faster-whisper interface**, with the existing Uzbek CT2 fine-tune as the first candidate to benchmark, generic multilingual small as a baseline and Vosk Uzbek as the resource competitor. This is a shortlist/provisional choice, not a claim that accuracy evaluation is complete. Prefer the model with the best EXACT integer-price accuracy first, flower and count accuracy second, then p95 latency/peak RAM. Do not compare WER figures across different corpora as a ranking. Fine-tune names alone confer no quality guarantee.

Capacity planning (estimates pending representative server measurement): 2 vCPU / **4 GiB total RAM minimum planning target** for one int8 small worker plus lightly used bot/web/Postgres/Redis; **8 GiB preferred** for headroom and cold starts. The existing 2 GiB deployment recommendation must be revised if small Whisper is selected. Isolate STT or choose Vosk if the host cannot leave at least 2.5 GiB of free RAM for an int8 small run. One job at a time, one model resident, no batched inference. Measure cold load and warmed inference separately. Reserve conversion for a different host with >=8 GiB genuinely available, and check first; this is a planning budget, not a measured guarantee.

Windows GlobalMemoryStatusEx read during preparation: 15.71 GiB total, **2.23 GiB free**, 2026-10-11. Consequently only stdlib unit checks are run here. No other project's processes or cache are changed.

### Worker contract and operational details (future integration)

`SpeechEngine.transcribe(audio_path, language="uz") -> Transcript(text, optional words/confidence, engine_id, model_revision)`. Provide FakeEngine in tests, FasterWhisperEngine and VoskEngine adapters. Local engine/model path in config; deployment installs approved/pinned weights once. Workers never auto-download missing models. Optional Gemini adapter is OFF by default and requires both a flag and an administrator-provided key. Recheck its free-tier terms/rate limits then; they can change. Text entry always works if STT is unavailable.

A dedicated Celery queue `stt`, prefork concurrency=1, worker_prefetch_multiplier=1, initial cpu_threads=2 and OMP_NUM_THREADS=2. Initial voice bounds: <=120 seconds, <=10 MB; soft limit 150 s, hard limit 180 s are provisional and must be calibrated from p95. The existing fine-tune's slow clip could exceed these limits on a two-core VPS; show a retry/text prompt on timeout rather than silently publishing. Only this worker consumes stt; the general worker must have an explicit queue list excluding it. A synchronous resident model per worker process is fine; asyncio Telegram/DB/Redis clients must be task-owned and closed, following CONTRIBUTING.

Bot immediately acknowledges “Ovoz qayta ishlanmoqda...”. Enqueue an opaque draft/job id and Telegram file_id, not bytes or bot tokens. Worker resolves the shop's token, downloads into a private task directory, converts and transcribes, closes task clients, deletes audio, stores transient text/field candidates and edits the acknowledgement. Temporary files are deleted in finally on success/errors/soft timeout. Hard kill bypasses finally: a supervised parent-side cleanup/janitor must remove killed-task directories immediately after worker death, with a TTL sweep for crash/reboot leftovers; test this explicitly. Telegram itself retains the original chat voice; local deletion cannot delete Telegram storage. Never log raw audio, transcripts, Telegram download URLs or tokens.

Late worker results must compare draft generation/revision: cancellation, replacement text or new audio invalidates previous jobs. No overwrite of a newer owner edit. Short TTL drafts; STT results are never publication permission. Model object can stay resident, but bot/database network clients cannot outlive one Celery task.

Future benchmark command to implement in CP22 (not available yet): `python -m gulbot.cli.benchmark_stt --manifest samples/uz-bouquets.json --engines faster-whisper,vosk --offline --output artifacts/stt.json`. It must run engines sequentially in fresh child processes, reuse pinned local weights, refuse implicit downloads and record CPU model/threads, RAM available, model revision, decode settings, cold-load time, p50/p95 latency, peak RSS, exact price/count/flower/colour accuracy and WER. Save expected text/fields in a manifest; keep recordings outside Git and delete temporary conversions after each run. The proposed sample prompts in samples/uz_bouquets.json are TEXT ONLY; user recordings and human reference transcripts are pending.

## 3. Number parser and field extraction rules

Implemented now: `cp22_prep/numbers.py`, pure standard library, deterministic. `parse_number(text) -> int` accepts a whole numeral phrase or raises ValueError. `find_numbers(text) -> list[NumberMatch]` returns integer candidates and untouched source offsets, without selecting an authoritative price/count. Maximum scan 4096 characters; numeral phrase 256 characters; integer bound 10^12. The bouquet-candidate scanner masks phone/date shapes and omits >=10^9; price plausibility remains the later catalog contract (10,000..50,000,000 UZS).

- Explicit Latin and Uzbek Cyrillic number tables; no blind transliteration of owner descriptions. Normalize NFKC and the exact CP7 apostrophe variants (`' ’ ‘ ʼ ʻ ` ´ ′ ＇`) in matching keys. Owner-facing spelling should retain ordinary o'/g'; hashtag keys remove apostrophes as CP7 does.
- Units 0..9; tens 10..90; optional unit after tens; one hundred multiplier 1..9 plus a <100 remainder. Strict order prevents `bir ikki` or `ellik yigirma` becoming invented amounts.
- Scales `ming`, `million/milyon/mln`, `milliard/mlrd` strictly descend. No repeated/ascending scales. Missing multiplier means one (`yuz`, `ming`, `million`). Digits and words can mix: `4 yuz 50 ming` = 450000.
- Counters `bitta/birta`, `ikkita`, `to'rtta`, other `-ta` forms and terminal `dona/ta`; examples `ellik bitta` = 51, `эллик битта` = 51.
- Decimal comma/dot before scales: `1,5 million` = 1500000; `1.25 mln` = 1250000. `yarim million` = 500000; `bir yarim million` = 1500000. Use Decimal, never binary floats. Final fractional UZS/count is rejected, not rounded.
- Grouping: `450 000`, `450.000`, `450,000`, `1,500,000`; three digits after separator mean a thousands group. Mixed separator conventions are rejected. Decimal `1,500 million` consequently means 1500 million; show the raw source in confirmation rather than guessing locale. Unsupported fractions (`1/2`), negative/signed values, scientific notation, ranges, unknown words and malformed numeric order are rejected by the strict parser.
- Scanner does not salvage a failed contiguous numeric run into a plausible suffix. It returns multiple distinct candidates if speech mentions multiple numbers; do not choose the first as the price. Phone/date masking and identifier-boundary checks protect e.g. `+998...`, national phones, dates, `8mart`, `1e6`.

Future field assignment: prefer amount immediately following `narx/narxi/нархи/цена` or preceding `so'm/sўm/сўм/сум/UZS`; prefer stem count preceding `dona/-ta` or anchored to a flower. One candidate per labelled field can be high confidence; conflicting/ambiguous candidates are low confidence and require editing. Apply catalog price bounds and a separately documented positive count limit. Never fuzzy-correct numeric words or infer missing zeros. `450` without `ming` stays 450 and is invalid as a bouquet price. `narxi kelishiladi` stays unknown. Multiple flower species do not justify inventing per-species counts. Owner must confirm every required field.

## 4. Flower/colour lexicon and general spelling

Implemented now: `cp22_prep/lexicon.py`, stdlib-only. `LexiconMatcher(shop_aliases=..., extra_flowers=...)` builds a fresh isolated matcher; no global mutable tenant cache. `match` returns kind, canonical key, method, confidence and alternatives; `find` adds original text offsets. Original text is never rewritten.

The curated list covers all FLOWER aliases in the inspected CP19 fixture, plus eustoma, gortenziya, orxideya, gipsofila, alstromeriya, frezia, ranunkulyus, lavanda and nargis. Colours: qizil, oq, pushti, sariq, kok, binafsha, yashil, qora, toqqizil, ochpushti, krem, shaftoli, aralash, with Uzbek Cyrillic/Russian aliases. Resolve `lola gul` and `och pushti` as longest multiword matches. Fuzzy matching cannot create an occasion as a flower: tag fixture entries for birthday/wedding/8mart are excluded by target taxonomy. Future integration loads aliases through the existing service with shop_id and incorporates newly approved flower types explicitly.

Known numeric/counter/scale tokens are excluded first, even if a shop alias conflicts. This prevents to'qqizta (nine) being fuzzily suggested as toqqizil (dark red). Matching order for other words: exact alias -> explicit Uzbek inflection suffix -> bounded Levenshtein. Short words (<4 letters) have no fuzzy matching; max edit distance 1 for lengths 4..6, 2 for >=7, normalized similarity >=0.75. `atrgul` becomes a LOW-confidence atirgul suggestion; `atirgullar`/`роза` have exact/known-morphology mappings. Equal best candidates or conflicting shop aliases return no canonical choice and alternatives for review. Returned confidence describes lexical matching only; it does not validate the STT acoustics, negation or field role. `qizil emas` must not be accepted as qizil automatically. Conservative integration must handle negation/conflicts as low confidence. The small stdlib matcher keeps preparation portable; rapidfuzz can replace its distance kernel later with acceptance tests proving the same decisions.

General spell correction is DESIGNED here, not implemented. Proposed word list: **u2b3k/uz-hunspell**, Uzbek Latin `uz_UZ.dic/.aff` plus Cyrillic `uz_UZ_Cyrl.dic/.aff`, >90,000 headwords, **GPL-3.0** as declared upstream. This permits commercial use with the licence's conditions. Use the upstream dictionary directly; preserve its full licence, copyright, exact revision and the corresponding sources for distributed derived dictionaries. A transformed list remains licensed dictionary data; a new filename or top-level MIT notice does not erase its licence. Resolve packaging compliance before redistribution and do not assume it becomes permissive just because it is loaded as data. [Dictionary upstream](https://github.com/u2b3k/uz-hunspell), [actual licence](https://github.com/u2b3k/uz-hunspell/blob/master/LICENSE).

Reject the tempting “one-million” MIT-labelled derivative as the default: its README says it derives from this GPL dictionary/UzWordNet, and its frequencies are all zero. Its MIT label does not establish permission to relicense the underlying word list or genuine frequency evidence. `kodchi/uzbek-words` is GPL-2.0; `tahrirchi/uzlib` (MIT) is a small question/answer spelling dataset, not a complete frequency dictionary. [Derivative provenance](https://github.com/HumoyunRustamov/one-million-uzbek-word-dataset), [kodchi licence](https://github.com/kodchi/uzbek-words), [uzlib structure](https://huggingface.co/datasets/tahrirchi/uzlib).

Future implementation: a bounded SymSpell-style deletion index (max distance 1 initially; distance 2 only as owner suggestions) built offline from licensed words, with separate Latin/Cyrillic lookup and Hunspell suffix expansion capped to approved forms. No fabricated word frequencies. Protect domain-match spans, numeral/currency spans, known shop names, URLs, handles, telephone numbers and unrecognized proper names. Preserve punctuation and the free description verbatim by default. Display proposed edits alongside the original and apply only explicitly accepted changes; this provides word-processor assistance without erasing the owner's wording. Missing dictionary must disable general suggestions cleanly, not voice/text input or the domain matcher. Pin licences in a future THIRD_PARTY_NOTICES and test that domain matches never enter the general corrector.

## 5. Caption and image styles (planned inventory)

Twenty UZ Latin caption styles, independent of image style. Optional Uzbek Cyrillic/Russian copies later share the same canonical tag and integer-price footer. Variables are escaped text, not HTML fragments; optional fields disappear cleanly. No style introduces a discount, stock claim, delivery promise or contact information the owner has not confirmed.

For price-parser safety, the canonical labelled integer-price block must precede EVERY owner-provided string, including shop names and manually edited flower names. Only fixed template copy may precede it. The styled body can vary line order, tone and emoji after that block.

All styles reserve these mandatory semantic fields: confirmed display name/colour, count when known, stable canonical flower hashtag(s), and exactly one price line `Narxi: 450 000 so'm`. Hashtags are rendered from canonical keys, never the free description. Example footer `#atirgul\nNarxi: 450 000 so'm`; arbitrary numbers in description are not allowed to override it. Description hashtags/currency can interfere with CP7's first-price heuristic: put the canonical footer/price before free description and strip/escape markup, but require ALL styles to pass hostile-description parsing tests as well. Recheck CP21 parser behaviour before settling final layouts.

| ID | Owner-facing name | Layout / tone / example heading |
|---|---|---|
| classic | Klassik | 🌹 Qizil atirgul; labelled lines, shop signature |
| minimal | Minimal | Flower name, count, canonical footer; no emoji |
| premium | Nafis | ✨ Nafis guldasta; generous whitespace, restrained wording |
| festive | Bayramona | 🎉 Bayram uchun guldasta; cheerful dividers |
| playful | Quvnoq | 🌸 Kayfiyatga rang qo'shing; bright emoji set |
| compact | Qisqa | Flower/count on one line, price/tag beneath |
| sale | Taklif | 📢 Bugungi taklif; price first, no invented discount |
| romantic | Romantik | 💗 Mehr bilan tanlangan gullar |
| elegant | Elegant | Name and slim rules; small restrained signature |
| friendly | Samimiy | 🌷 Yaqinlaringiz uchun; warm concise text |
| modern | Zamonaviy | Clean label blocks, name in title |
| checklist | Ro'yxat | ✓ Flower, ✓ colour, ✓ count; footer |
| catalogue | Katalog | Field-value product card; predictable order |
| gift | Sovg'a | 🎁 Sovg'a uchun guldasta |
| spotlight | Diqqat markazida | 🔎 Guldasta bilan tanishing; title-first |
| poetic | She'riy | 🌼 Gullarda ifodalangan mehr; one fixed poetic line |
| geometric | Geometrik | ▪ Name/count/colour; crisp typographic blocks |
| pastel | Pastel | Soft tone with 🌿 and light separators |
| monochrome | Oq-qora | Text-only strong title and compact labels |
| signature | Do'kon imzosi | Shop display name as heading, product details beneath |

Each template must be tested with CP7/CP8's real caption parser, not a replica, across every populated/missing optional field and hostile text. Rendered Telegram captions are <=1024 UTF-16 code units after entity parsing; count emoji as two where appropriate. Budget required fields before shortening description; never truncate a hashtag, integer price or HTML entity. The product name and owner text are HTML-escaped once at render. If mandatory fields cannot fit, prompt editing rather than cut them. Preview and publish use the SAME immutable rendered caption/media artifact, bound to a draft revision/hash; editing invalidates confirmation/preview.

Ten original Pillow image overlays PLUS `none` (always available):

| ID | Style | Original geometry/theme |
|---|---|---|
| price-pill | Narx belgisi | Bottom-right rounded dark pill, high-contrast price |
| ivory-frame | Fil suyagi | Thin ivory frame + small shop signature |
| gold-corners | Oltin burchaklar | Four original double-line corner ornaments, warm gold |
| rose-ribbon | Pushti lenta | Lower soft pink band with price and shop name |
| emerald-card | Zumrad | Compact emerald inset card, white typography |
| midnight | Tungi | Charcoal lower gradient and subtle gold rules |
| pastel-label | Pastel yorliq | Cream/lilac card and simple line motif |
| festive-dots | Bayram nuqtalari | Original sparse corner dots, bounded price badge |
| minimal-line | Minimal chiziq | Thin bottom rule, small left name/right price |
| geometric-badge | Geometrik nishon | Asymmetric original polygon price badge |
| none | Ustamasiz | Original first photo; no overlay |

Render only the first photo, preserve later album photos and original file_ids. Correct EXIF orientation, convert to RGB/sRGB, cap dimensions/decoded pixels and output JPEG quality; reject decompression bombs. Work on a copy, bound overlay area to avoid hiding the flowers, wrap or ellipsize the shop name separately from the price. Font plan: Noto Sans Regular/Semibold from google/fonts (OFL-1.1); commit original OFL.txt with exact fonts at integration. Verify cmap and render Uzbek glyphs ў ғ қ ҳ and Cyrillic plus chosen apostrophes; Pillow needs TTF/OTF, so existing web WOFF2 alone is insufficient. Avoid emoji in overlays unless a separately licensed glyph asset is added. [OFL source](https://github.com/google/fonts/blob/main/ofl/notosans/OFL.txt), [font metadata](https://github.com/google/fonts/blob/main/ofl/notosans/METADATA.pb).

Saved favourite is a shop-scoped pair (caption style, image style). Pickers allow per-post override and explicit “Standart qilish” action. Unknown/deleted style ids fall back to `classic`/`none`; configuration never skips confirmation.

## 6. Integration design to revisit after CP21

Main-menu entry “📢 E'lon joylash” exists only in the shop's bot and only for the same CP19 owner/staff predicate. Use a server-side check at every message/callback/service mutation and worker result. Check shop bot identity + private chat + user ownership/staff membership + current shop status; never trust callback shop/user ids. Customer and other-shop owner crafted callbacks get a refusal and no draft/channel/catalog mutation. Staff revocation between preview and publish must take effect immediately.

FSM: photos (1..10, single or album) -> voice/text -> parsing -> field review/edit -> explicit confirmation -> caption/image pickers -> exact preview -> Joylash -> published link. Album collection must debounce without accepting >10 and without merging two albums; user identity, bot identity and shop identity partition storage. Each edit returns to field confirmation. Low confidence is visible even when a field has a plausible value. Restart/cancel must invalidate pending jobs and stale callbacks.

Persist a shop-scoped draft/publication receipt and shop-scoped style preference only if CP21 has no reusable storage contract. Draft records include owner/staff actor, revision, confirmed revision, media ids, parsed fields, chosen styles, preview hash, publish status and resulting channel message ids. Every new table has shop_id and proper composite foreign keys; enforce tenancy at query/write boundaries. Additive Alembic upgrade/downgrade/upgrade on a fresh throwaway DB. Do not prescribe a migration revision before CP21 lands.

Acquire durable single-flight publication state before sending. Telegram sendPhoto/sendMediaGroup has no transactional idempotency key: a worker death after a successful send but before a saved receipt is an ambiguous send, not permission to blindly retry. Surface reconciliation instead of duplicate posting. Use returned Message objects to index through the SAME CP8 upsert/finalize service; no second product parser. Revalidate channel belongs to the shop and service-level tenancy. On catalog-write failure after send, retain receipt and retry indexing, never resend the channel post. An eventual channel_post duplicate must converge to the same product; albums finalize once using CP8's existing semantics. The bot's own channel_post delivery is an empirical question, not assumed here; test both delivery/no-delivery paths and gather real dev-bot evidence later. Links must support public username channels and private /c links with the correct anchor message.

## 7. Acceptance, evidence and handoff

This folder contains standalone modules/tests only; no bot, database, Celery integration, actual template renderer or STT benchmark is claimed complete. Tests were written first: initial run 153 assertion failures, 0 errors; implementation first passed 156 tests; final verification passes 167 tests, including an exhaustive 81-case two-digit sweep within one test. Further edge-case/mutation verification is recorded in VERIFY.json. Python 3.12.14 bundled runtime was used with `-B` (no bytecode writes); source syntax is checked for Python 3.11 compatibility.

Before proper CP22 starts: re-read CP21's updated CHECKPOINTS/CONTRIBUTING/DEPLOY/AUDIT, confirm upstream/main includes its pushed commits and identify routes/state storage changed there. Then port these modules with the established testing/i18n conventions. Full gates, per-bot shadow 0, all new table/route tenancy checks, mutation proofs with assertion failures only, migration round trips, secrets scan and atomic green commits/pushes remain integration requirements. Do not run the repository gate from this preparation session.

Later live evidence: text fallback announcement first if no bouquet recording exists, all confirmation/style screens, channel link and catalog row; own-post delivery observation; 20 caption screenshots and 10 overlays + no-overlay gallery; real STT on the owner's ten recordings. Record hardware/model settings and distinguish measured accuracy from estimates. Audio files are excluded from version control and purged after testing according to the owner's agreed policy.

The only requested next user action is the already agreed signal that CP21 has been pushed. Bouquet sample recordings are needed later for the final model decision. No publication, model installation or repo changes take place in preparation.