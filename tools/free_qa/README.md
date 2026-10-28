# Free QA asset preparation

This package prepares the two pinned official Qwen2.5-7B-Instruct Q4_K_M shards.
It does not run a model, tokenizer, QA adapter, quality comparison or service.
The public profile fixes URLs, raw SHA-256, bytes, Apache-2.0 source/license
references and the existing b11429/d8123504 runtime 55-file references.
The GGUF conversion's base commit is unknown. The separately observed base
revision and repository templates are not asserted to be the shards' metadata.
No runtime binary is copied, downloaded, upgraded or currently reverified here.

From the repository root, use an explicitly verified Python 3.11 or 3.12
environment with psutil. This checkout currently uses the separate asset-only
Python described in [runtime recovery](../../docs/MEETINGS-ASSET-RUNTIME-RECOVERY.md);
the original uv Python junction is blocked and remains unchanged:

```powershell
python -B scripts/prepare_meeting_free_qa.py inspect
# Only after separate review and an explicit acquisition assignment:
python -B scripts/prepare_meeting_free_qa.py acquire --root models/meetings-qwen25-7b-q4km-new-run --download
# Separate offline verification; no network fallback and no automatic retry:
python -B scripts/prepare_meeting_free_qa.py verify-only --root models/meetings-qwen25-7b-q4km-new-run
```

The example root must be a fresh, separately assigned name; never reuse it for a
second acquisition. In this checkout the failed `v1` root is preserved, and the
successful `v2` root is consumed and immutable. [The v2 result](../../experiments/results/meetings-free-qa-acquisition-v2.json)
records two full pinned shards, CLI/wrapper exit 0 and parent custody acceptance.
It is not permission to repeat acquisition or proof of model loading or quality.
The [separate metadata review](../../docs/MEETINGS-FREE-QA-METADATA-REVIEW.md)
and fixed-source environment checks have completed; current runtime admission,
exact code bindings and actual model protocol/quality checks remain required.

`inspect` reads only the pinned public profile. Acquire requires a nonexistent
workspace whose parent exists and the explicit `--download` flag. Publication
uses same-directory Windows rename without overwrite; actual acquisition on
other operating systems is rejected rather than emulated with replacing rename.
No credentials, caller proxy configuration or runtime/model flags are inherited.
HTTPS redirects are limited to the explicit Hugging Face/CDN host allowlist;
an unknown redirect fails and preserves the partial bytes. Redirect responses
are closed without reading their bodies. Each hop checks the same byte/disk/time
budget; repeated destinations and more than ten hops fail without retry.

The two shards remain separate and only the first filename is the prospective
model entry. The transfer cap is 5 GiB, the whole owned workspace cap is 6 GiB,
and acquisition shares one 30-minute deadline across download, disk SHA checks,
metadata binding, receipts and cleanup. The last five seconds are reserved for
owned worker cleanup. A later explicitly requested verify-only operation has
its own 30-minute offline verification deadline. Verification
uses no transfer allowance and cannot repair or redownload either file. Hashing,
metadata reads and receipts share its deadline. Model RSS/request budgets are
unchanged and are not exercised by this package.

`assets/` must contain exactly the two approved filenames on success. Other
workspace files and directories are restricted to the named receipts, logs and
empty owned temporary directories. Ancestor reparse points, symlinks, hardlinks,
extra files, wrong sizes/hashes and observed file identity changes fail closed.
`*.part`, stage receipts, logs, failure records and prior successes are retained;
there is no delete, resume, automatic retry, shard merge or global installation.
A failed or already used workspace is not silently reused. A separate assignment
must decide any subsequent attempt.

A supervised Python worker makes blocked network or disk reads interruptible
at the outer deadline. The existing generic `OwnedTree` records PID, create time
and executable identity and only cleans up that owned tree. If initial identity
capture fails, the original returned Popen handle receives bounded cleanup, but
unknown descendant absence remains a failure. Unknown observation or cleanup
failure never becomes success. TEMP/TMP point inside the new workspace and are
included in disk accounting. These are sampled stop thresholds, not OS hard
peak guarantees; no unrelated process or shared temporary directory is touched.

The offline reader accepts little-endian GGUF v3 and reads at most 32 MiB of
header/KV bytes across both shards. Key, type, UTF-8, length, count, duplicate,
bool/finite-number and array bounds are checked before unbounded allocation or
iteration. It stops before tensor descriptors and does not interpret tensor
payload; full SHA verification separately streams file bytes in bounded chunks.
Known architecture and split indices/counts/header totals must match. Template
bytes retain literal line endings and Unicode. Receipts include the template raw
UTF-8 SHA-256 and each tokenizer KV's type plus SHA-256 of its exact GGUF-encoded
value bytes (including string lengths/array descriptors). The overall binding
hash uses sorted compact JSON of those observations, not replacement model bytes.

`acquisition.json` means downloaded bytes were checked against the publisher
pins again on disk and metadata observations were bound within the same deadline.
`verify/metadata.json` records a separately requested offline re-verification.
Both contain unreviewed metadata observations. Its `execution_approved` remains false.
Both also require their supervisor's terminal-clean receipt with no appended
`supervisor-invalidation.json`. Final result reads, receipt writes and the final
inventory scan are followed by a deadline check. A late or failed finalization
appends invalidation without rewriting earlier records; subsequent verification
rejects that workspace, even if a preliminary terminal-clean receipt exists. Actual split loading,
tokenization, GPU/RSS fit, latency and quality remain unverified. A separately
reviewed metadata binding and future runtime revalidation/registration are
required; repository templates are never substituted and no thinking suffix is
added. The new six cases, adapter, registration and actual QA runs are separate work.

Synthetic checks (no network, large assets, native/model/helper processes or live
resource sampling):

```powershell
python -B -m pytest tests/test_prepare_meeting_free_qa.py -q -p no:cacheprovider
python -B -m ruff check scripts/prepare_meeting_free_qa.py tools/free_qa/assets.py tests/test_prepare_meeting_free_qa.py
```

The implementation and mocked checks do not establish actual asset or runtime
compatibility. Original failures are preserved in the implementation evidence.

## Mandatory outer-success gate

Before accepting an actual acquisition, running verify-only on its root, or
registering model preparation, follow the
[external success and custody gate](../../docs/MEETINGS-FREE-QA-ACQUISITION-GATE.md).
The same root/attempt/profile/source must have an observed actual CLI exit 0,
the final successful stdout JSON, and complete termination/custody evidence.
A wrapper exit, a preliminary TERMINAL_CLEAN file, or absence of invalidation
alone is insufficient. If storage prevents invalidation itself, nonzero,
interrupted or unobserved runs remain failed/unknown and that root cannot be
recovered through verify-only. The current CLI does not automatically validate
these external observer records; the assigned operator must enforce this gate.
No new download, model execution, or human approval is implied by this document.
