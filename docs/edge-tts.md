# Edge TTS

The explicit `edge` provider uses unmodified `edge-tts==7.2.8`, the latest PyPI
release checked on 2026-10-11. It is an online option alongside OmniVoice CPU/GPU;
it does not install an AI model or warm a local inference worker. Subtitle text
is sent to Microsoft's service. The UI discloses this before generation.

Vietnamese, English and Chinese have matching male/female voice choices.
Cloning and source-speaker identification remain OmniVoice-only. Switching the
provider resets unsupported voice/speaker selections, not completed media.

Subtitle synthesis uses one event loop and two bounded workers, not one task
per subtitle. At most two network requests run across projects. A retryable
failure switches that batch to serial requests with shared cooldown; an
already-running peer can finish. There is no unbounded prefetch. Requests are
bounded by escaped UTF-8 size, use fresh single-use Communicate instances,
and allow at most three attempts for transient errors,
including `NoAudioReceived`. Each attempt has a 45-second deadline, bounded
connect/read timeouts, and cancellation polling at 100 ms. Backoff is cancellable.
Invalid voices, unreadable text, certificate failures and non-transient HTTP
errors are not blindly retried. TLS verification remains enabled.

Every chunk must have a valid header and positive probed duration. A single
chunk publishes the exact verified file without a duplicate copy/probe; a
multi-chunk narration also verifies the combined MP3. Cache hits are still
probed, using two bounded probe workers without blocking the streaming loop.
Cancellation drains probes before removing staging files to avoid Windows
file locks. Terminal batch failures cancel and drain sibling requests.
Only complete successful streams are atomically published. Failed/cancelled
requests leave previous audio intact; completed sentences are reusable through
existing Manual artifacts and Auto partial checkpoints. Edge policy/version
changes affect only Edge cache keys, not OmniVoice, OCR or subtitle caches.

Upstream still reports intermittent failures with valid requests:
https://github.com/rany2/edge-tts/issues/473
No client can guarantee Microsoft's service will always return audio. Exhausted
retries stop with an actionable message, never a successful empty voice/export.
HaizFlow does not silently switch the requested voice/provider.

## Prerecorded voice previews

All six catalog voices (Vietnamese, English and Chinese, male/female) include
verified MP3 samples under `desktop/assets/voice_samples/edge`. They use the
same public sample sentences as the OmniVoice library, listed in `samples.json`.
The existing preview player reads these assets locally: no network, TTS runtime
or project dialogue is needed when pressing the sample button. Manual, Auto
and Batch voice selectors use the same provider/voice/language lookup.

Maintainers can regenerate missing/invalid Edge samples with
`python scripts/generate-edge-voice-samples.py --live`; synthesis uses the same
bounded retry, audio validation and atomic publication as the Edge backend.
This maintenance script sends only the public sample sentences, isolates its
runtime from user projects, and preserves already verified samples.

## Source performance check (2026-10-11)

The opt-in `python scripts/test-edge-tts.py --live --batch` sends eight generic
Vietnamese subtitles, verifies each output, then repeats with those cached
clips. Observed on the development machine with the same texts/voice:

| Case | Before | After |
| --- | ---: | ---: |
| Generate eight clips | 25.924 s | 6.533 s |
| Verify/reuse eight cached clips | 5.916 s | 3.252 s |

These are single live observations including client/probe overhead, not a
controlled service benchmark or a promised speedup. Network latency, service
throttling and hardware affect results. Synthesis voice, prosody, audio format
and cache identity were not changed. Successful upstream streams are still
required; parallelism does not mask missing audio or substitute another voice.

Run deterministic tests with `tests/test_edge_tts_backend.py`. Live checks are
optional (`python scripts/test-edge-tts.py --live`) and must not be required by
the repository gate. No release binary is
built by these tests. Before a frozen release, retain the LGPL client source and
license alongside the generated dependency inventory and verify replacement;
the packaging hook collects the unmodified client as readable `.py` modules,
the LGPL client license does not grant rights to Microsoft's remote service.
