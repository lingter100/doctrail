# Third-party provenance and license retention

The grammar and corpus are public synthetic project artifacts, distributed under
this repository's existing LICENSE (copied here without changing its terms).
The new harness is original glue around the official internal API; it does not
vendor engine implementation code or model/lexicon payloads.

Engine: ggml-org/llama.cpp, commit d81235049384534c167caea52b85a694f6103d14.
Read-only API references:
- https://github.com/ggml-org/llama.cpp/blob/d81235049384534c167caea52b85a694f6103d14/tests/test-gbnf-validator.cpp
- https://github.com/ggml-org/llama.cpp/blob/d81235049384534c167caea52b85a694f6103d14/src/llama-grammar.h
- https://github.com/ggml-org/llama.cpp/blob/d81235049384534c167caea52b85a694f6103d14/LICENSE

Portable tools and published archive hashes are recorded in pins.json. Actual
archives/toolchain binaries are NOT included. Future acquisition must retain:
- LLVM-MinGW 20250709 bundled LLVM and mingw-w64 license files;
- CMake 3.31.8 Copyright.txt and bundled license notices;
- Ninja 1.12.1 COPYING (pinned upstream source if omitted from the zip);
- engine LICENSE and all selected subtree license files, unchanged.

The acquired manifest records exact URL, Git blob ID and SHA-256 for each engine
file and hashes the complete expanded tool inventories and discovered licenses.
Review the actual acquired license texts before redistributing build/tool artifacts.
No source/tool download, version probe, configure, build or native verification is
claimed by this preparation-only package.
