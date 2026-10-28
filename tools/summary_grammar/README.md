# Pinned, model-free summary grammar check

This package is preparation code, not evidence that the C++ engine builds or passes.
It preserves the 910,051-byte candidate grammar and all 106 synthetic corpus records.
The native batch has 105 UTF-8 carriers; `raw-surrogate` remains a strict encoding
rejection. Ten incomplete prefixes have complete witnesses fixed in
`prefix-witnesses.json` before any native result. The frozen parser expectations are
recorded separately and are never relabelled as grammar acceptance.

Run from the repository root with Python 3.11/3.12 and the existing `psutil` dependency.
No private inputs, hidden baseline files, Git extraction or user-specific paths are needed.

```
python -B -m scripts.prepare_summary_grammar_engine inspect
python -B -m scripts.verify_summary_grammar_engine carriers
python -B -m pytest tests/test_summary_grammar_engine.py -q
```

The following operations require separate assignment/review. Use a NEW project-local
workspace, keep its binaries out of version control, and do not overlap model work.
The illustrative `_grammar-engine-work` directory is an operator-chosen output path;
this package does not modify ignore rules or install anything globally.

```
python -B -m scripts.prepare_summary_grammar_engine acquire --workspace _grammar-engine-work
```

Acquisition runs in an owned Python worker so stalled DNS, socket reads or extraction
can be stopped by the same shared deadline. It preserves archives, a commit/tree/blob manifest, original engine sources,
expanded tool inventories and licenses. It never executes the downloads. Known
LLVM-MinGW/CMake hashes are fixed in `pins.json`. Ninja's publisher hash is unknown;
its acquired hash must be inspected and included in the separately reviewed
`acquisition.json` SHA-256. An unreviewed draft is NOT executable-ready. Review URLs,
license files, engine blobs, tool inventories and the exact acquired Ninja bytes.
No executable/version invocation is used to substitute for that review.

The opt-in v3 acquisition profile `llvm-x64-sampled-50ms-v1` selects the pinned
x64 LLVM tool files and licenses, checks all ZIP entries before extracting the
selected entries, and samples costly resource observations at 50 ms checkpoints.
Time, log, transfer and disk checks still run at every checkpoint. Short resource
peaks between samples may be missed. Legacy acquisition keeps its existing policy.

For v3, the reviewed SHA supplied to `build` is the SHA of externally reviewed
`<workspace>.external-review/acceptance.json`, **not** the SHA of `acquisition.json`.
The companion binds the actual acquisition SHA, exact attempt and source bytes,
externally observed CLI exit, complete stdout/stderr, elapsed time and process
cleanup. See the [external acceptance contract](../../docs/MEETINGS-SUMMARY-ENGINE-V3-EXTERNAL-GATE.md).
The CLI never creates or approves that external record for itself. An independent
external observation and review must establish the supplied digest; computing a
hash of self-asserted JSON is not an observation. Synthetic test fixtures do not
authorize execution. Legacy acquisition still uses the reviewed `acquisition.json`
SHA. Internal success files alone do not establish successful v3 completion.

```
python -B -m scripts.prepare_summary_grammar_engine build --workspace _grammar-engine-work --reviewed-acquisition-sha256 REVIEWED_SHA256
```

The build makes one static CPU library and one validator target, at parallelism two.
The superproject disables Git discovery, external/GPU backends and utilities.
Configure trace and observed child executables are checked; Git/network/non-target
execution fails closed. Logs and partial files remain on failure. There is no retry
or global PATH/registry installation. The portable Windows toolchain and this CMake
recipe have NOT been configured, linked or engine-tested by the preparation task.
A successful build emits `build-manifest.json`; independently inspect its source,
executable, trace, logs and cleanup evidence before supplying its reviewed hash.

For compatibility, `acquisition_sha256` in a v3 build attempt/manifest carries the
reviewed companion SHA. The actual acquisition SHA is in the companion's manifest
reference. Public execution reports must distinguish `review_artifact_sha256`
from `actual_acquisition_sha256`. Both build checks and the validator recheck the
same external record; later build files do not change the acquisition-time custody
scope. Bounded pre/post checks do not establish a new 900-second bound on the whole
build command: the existing 900-second runner budget begins after preflight.
The new external-control reads are bounded and check the bytes they return.
Existing internal inventory/reference checks reread acquisition files through the
legacy helpers. The full verification is therefore not an atomic snapshot or an
end-to-end bounded-I/O operation against concurrent mutation. Keep the reviewed
workspace exclusive; the later check does not retroactively bound an earlier read.

```
python -B -m scripts.verify_summary_grammar_engine run --workspace _grammar-engine-work --reviewed-build-sha256 REVIEWED_SHA256
```

A global workspace `native-issued.json` prevents reissuing a batch under another
result directory. The original grammar and encoded carrier bytes are hash-bound;
UTF-8 is strict, with no normalization, newline replacement or surrogate repair.
The harness initializes with null vocabulary once, clones/frees each case, and uses
the pinned engine's Unicode conversion/accept/stack API. Verdicts are `complete`,
`prefix`, or `dead`. Prefixes must also accept their prebound suffix. It prints a
strict bounded JSON-lines protocol; exit zero alone is never acceptance.

Budgets are fixed: acquisition 600 seconds/512 MiB transferred; total workspace
4 GiB; configure/build 900 seconds shared; preparation process-tree RSS 2 GiB,
host reserve 2 GiB/start 4 GiB. Validator initialization, clones, all inputs/witnesses
and cleanup share 60 seconds, with the last 5 reserved for cleanup; native tree
RSS 512 MiB, host reserve 2 GiB/start 2.5 GiB. Observations are sampled stop
thresholds, not OS guarantees against instantaneous peaks. Unknown identity or
resource observation fails closed. Cleanup acts only on observed PID/creation-time/
executable identities or the original directly created Popen handle; uncertainty
is preserved, never converted to verified absence. Cleanup failure requires parent
resolution before another workload starts.

The report separates initialization, expanded rules (max 20,000), clones, longest
case, whole time and sampled RSS. Raw/partial logs remain for failure analysis.
Finite grammar acceptance does not prove all-string equivalence, model token
filtering cost, generation within 768 tokens, meaningful Korean summaries, review
quality or service readiness. No model, vocabulary, tokenizer, Java or product
runtime is loaded by the validator.

See `LICENSE` for this project's license and `THIRD_PARTY.md` for upstream provenance.


Review repairs bind the concrete LLVM-MinGW wrapper-to-versioned-driver paths and
SHA-256 values in `acquisition.json` before its separate review. The major number
comes from that acquired inventory and its resource directory, never the host PATH
or an assumed installed version. Unknown executables remain forbidden.

The CMake 3.31.8 `Windows-GNU.cmake` optional `ld -v` trace is recognized only at
its exact source line and arguments, with its acquired module hash included in
the reviewed lock. Preflight checks the controlled Windows executable search
locations for ld executable/script aliases, before and after configure. This
allows an unavailable optional query in the trace; it grants no ld executable
permission and is not an observation of a successful or failed tool execution.
Other relative commands, changed modules/arguments, Git, downloads and try_run
remain rejected. Actual archive layout and Windows execution are still untested.

Acquisition, build and validator children receive separate fresh TEMP/TMP folders
inside their owned workspace. Host TEMP/TMP are never inherited or modified.
Temporary response files count toward the same 4 GiB budget and remain in place
with failures; shared temporary directories are never scanned or cleaned.
