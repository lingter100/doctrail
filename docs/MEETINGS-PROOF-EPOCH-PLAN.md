# Proof epoch 설계 수정: 64KiB bounded snapshot reader

2026-10-20. 등록 ID와 NEW2 경로 `meetings-proof-epoch-v1`은 유지하지만 구현 범위를 **읽기 요청 크기 하나를 바꾸는 후보**로 수정한다. Epoch cache/hash·parse 재사용은 채택하지 않는다. 이번에는 이 문서와 [protocol](../data/evaluation/meetings-proof-epoch-protocol-v1.json)만 수정하며 구현·공식 비교·Git·tokenizer/native/HTTP/품질 실행은0이다.

## 근거와 보존한 초안

C5 실패 [metadata](../experiments/results/meetings-c5-quality-failure-metadata-v1.json) SHA `21fcf3da665c82d9d3fc4a8b1d9727389046ee891f1b708b2cc159f3e15650b4`와 [replay](../experiments/results/meetings-c5-quality-failure-replay-v1.json) SHA `97bd85ddd4c515673381afe4aedc66a9bb7ad762d2f000e192dfc7cc129f025c`를 확인했다. 원본 report/trace/source/item/oracle는 열지 않았다. 첫 요청89.859초 중 초기 proof19.687초, native51.395077초와 나머지 원인 미확정18.776923초를 구분한다. 둘째 초기 proof23.094초만으로 native 진행이나 실패 원인을 추정하지 않는다. 원래 C5 실패·미실행cal4/val8·의미 판정0·false flag는 불변이다.

수정 전 hash/parse 재사용 초안2개를 ignored `.local/meetings-proof-epoch-abandoned-hash-cache-v1/`에 정확히 복사하고 hash를 대조했다.

- `MEETINGS-PROOF-EPOCH-PLAN.md`: 14092bytes, SHA `7c92e9ca29a5a9f2d037ce4cce2a1a42f7e65a810312ee6c0aaa9b9b71af4689`.
- `meetings-proof-epoch-protocol-v1.json`: 12237bytes, SHA `589f8f8f5cf65d6f0520efa72c9d62dc63043efd3cc5068076fff45760fb26e2`.

그 안은 ABA 검출을 지키면 재읽기를 줄이지 못하고 hash/parse만 재사용한다. 별도 제한 검토가 보고한 기존 합성 profile의 전체 SHA8.19..16.41ms·AST0.41..0.99ms 범위도 큰 효과의 근거가 약하다. 이번 새 측정값은 아니다. 캐시 구조를 만들기보다 구체적인 reader 할당 가설 하나를 비교한다.

현재 frozen `scripts/prepare_meeting_budget_inputs.py:snapshot`은 `BYTE_LIMIT=16*1024*1024`에서 `stream.read(BYTE_LIMIT+1)`를 호출한다. CPython3.11.15의 일반 BufferedReader read 경로는 요청한 n 크기의 bytes를 먼저 만들고 EOF에서 실제 길이로 줄이는 코드가 있다. [공식 일반 read 구현](https://github.com/python/cpython/blob/v3.11.15/Modules/_io/bufferedio.c#L1541-L1588), [read 진입 경로](https://github.com/python/cpython/blob/v3.11.15/Modules/_io/bufferedio.c#L819-L836). 작은 파일에서 큰 임시 요청을 줄일 이점은 **가설**이다. 실제 allocator 비용·RSS·C5 비용 기여율은 측정하지 않았고 OS cache/allocator 동작에 따라 이득이 없을 수 있다.

## 유일한 후보 변경과 동등성

Reference는 변경하지 않은 기존 snapshot을 명시적 계측 path/stream adapter로 호출한다. 순서는 stat stamp → 일반 blocking binary file open → `read(16777217)` → close → overflow 검사 → 최종 stamp 검사 → raw/stamp 반환이다. Adapter는 실제 stat/open/read를 그대로 전달하고 기존 module/global을 바꾸지 않는다. Stamp는 dev/inode/size/mtime_ns/ctime_ns이며 overflow 오류가 stamp 변경보다 먼저인 원래 우선순위를 보존한다.

Candidate는 **같은 open과 검사에서 read 부분만** 다음과 같이 바꾼다. 남은 `BYTE_LIMIT+1`까지 매번 `min(65536, remaining)`을 요청하고 반환 bytes를 순서대로 모은다. 비어 있지 않은 short read는 EOF로 간주하지 않고 계속 읽는다. 빈 bytes의 EOF 또는 누적16777217bytes에서 멈춘다. 그 뒤 원래와 같은 overflow/stamp 검사와 bytes 반환을 수행한다. None·잘못된 타입·요청보다 큰 반환은 정상 EOF로 처리하지 않는다. Stream/read/close 오류를 감추거나 부분 bytes를 성공으로 반환하지 않는다.

파일 크기를 믿고 조기 성공하거나 잘라 수용하지 않는다. 최종 bytes·hash·parse 결과와 모든 fresh read를 보존하며 어느 경계 안팎에서도 cache를 추가하지 않는다. Chunk 목록과 최종 join은 실제 파일 크기에 비례하는 메모리를 사용하므로 전체 작업 메모리가64KiB라고 주장하지 않는다. 큰 파일에서 복사 비용·메모리가 늘 수 있다. Python read 요청 상한은 OS prefetch/실제 disk I/O 상한이 아니다.

정상 regular blocking file에 대해 bytes/stamp/오류 의미를 비교한다. 회귀 크기는0,1,65535,65536,65537, BYTE_LIMIT-1, BYTE_LIMIT, BYTE_LIMIT+1 및 그보다 큰 파일이다. Short raw read는 양쪽에 독립적인 `io.BufferedReader`를 씌워 비교하고, 소켓·interactive·nonblocking stream으로 계약을 넓히지 않는다. I/O 오류 위치는 가능한 공통 raw byte 위치로 지정한다. 여러 chunk를 이미 반환받은 후보와 단일 read가 예외로 끝난 reference의 partial returned-byte 계수는 다를 수 있으며0으로 맞추지 않는다.

HEAD 이동·committed bytes 불일치·same-size/same-mtime 변조·path/reparse point/hardlink alias·negative import 출현·중간 변경·마지막 재읽기 직전 변경·경계 사이 변경·읽기/저장/subprocess/시간 실패를 검사한다. ABA는 변조가 reference의 관측 read까지 유지되고 나중에 복원되는 schedule을 포함한다. **Reference가 잡은 변경을 candidate가 놓치면 성능과 관계없이 실패**다. 두 구현의 모든 관측 사이에 변경/복원이 끝나는 경우 및 임의 동시 interleaving의 원자적 snapshot 동등성을 보장하지 않는다. Chunking은 관측 시간창을 바꿀 수 있으므로 마지막 상태 일치만으로 변조 부재를 주장하지 않는다.

Fault hook은 테스트의 명시적 dependency injection이며 기존 함수/global/builtins monkeypatch는 없다. 공식 CLI에는 mutation 옵션이 없다. OS 미지원 link 검사는 skip 사유와 검증 공백으로 남긴다. 정확한 bytes·first safe failure 범주·새로운 금지 후보 본문 읽기 부재를 비교하고 반례를 보존한다.

## 같은 검증 조합과 새 fixture

Reference와 candidate는 reader 외에 같은 검증 코드를 사용한다. 이미 검토한 frozen `prepare_meeting_c5_inputs.py` SHA `6ebf1a991e25c52f38b2a0bb7ab8fdceef8e6a880305f69e423ef73df067b04a`의 `source_manifest → code_contract` core에서 다음 순서를 가져온다.

1. 내부 snapshot으로 bound bytes/hash를 확인하고 허용 코드 AST/import 후보를 검사한다.
2. `source_manifest.unchanged`의 전체 fresh read/hash.
3. 호출자 bound snapshot의 fresh read/hash.
4. `GitProof(bound, revision=CI_HEAD)`의 현재 bytes/committed bytes 비교.
5. `GitProof(bound, revision=HEAD)`의 현재 bytes/committed bytes 비교.
6. 호출자 `snapshots.unchanged`의 마지막 전체 fresh read/hash.

공통 payload의 논리적 소비6단계이며 cache miss의 committed-helper 추가 읽기·manifest/HEAD 검사는 별도로 실제 계수한다. 각 경계의 현재 HEAD·committed bytes·path/alias·negative import 존재·마지막 HEAD 확인을 양쪽 동일하게 유지한다. CI_HEAD와 HEAD 소비를 합치거나 reference에 반복·sleep·parse를 더하지 않는다. 기존 Git blob cache 의미도 양쪽 같게 유지하며 새 reader/hash/parse cache는 없다. 이전 경계의 성공으로 다음 검사를 대신하지 않는다. C5 orchestration을 실행하지 않으며 전체 metadata/role/108snapshot/실제 payload/HTTP를 재현한다고 주장하지 않는다.

실측은 NEW remote0 synthetic Git repository 하나에만 수행한다. Payload40개 총393216bytes와 별도 manifest1개를 커밋한다: Python8×4096, JSON24×4096, JSON8×32768bytes. JSON은 schema_version/ordinal/padding만 포함한다. Python은 `scripts/epoch_fixture/__init__.py`, `entry.py`, helper_00..05.py이며 실행하지 않고 AST만 읽는다. Entry에는 helper6개와 absent_00..31의 고정 import32개를 둔다. 실제 resolver가 만드는 모든 positive/negative 후보를 봉인한다.

정확한 generator/파일 순서/UTF8 LF/직렬화/bytes·hash/manifest hash/후보 경로/고정 Git identity·date·config는 구현 동결 전에 정한다. 임시 repo init/add/단일 commit은 setup에만 허용하며 remote/network/hooks/signing0, 프로젝트 HEAD/index/config 불변이다. 과거 profiler fixture나 실제 C5 code/data graph를 복사하지 않는다. 실제 프로젝트의 명시적 code allowlist 확인은 구현 무결성 setup이며 측정 workload와 분리한다.

공식 순서는 **reference/request_start → reference/before_dispatch → candidate/request_start → candidate/before_dispatch**, 각1표본/최대4경계다. 공식 fixture는 중간에 바꾸지 않으며 fault 회귀는 소스 동결 전 테스트에서만 수행한다. Warmup/반복 평균/역순/옛 profile 재실행0이다. OS cache·배경 부하·순서 효과가 통제되지 않은 n=1 관측이며 안정적 speedup 또는 C5 절약 시간으로 일반화하지 않는다.

## 계수·한도·실패 보존

공통 명시적 I/O 계측으로 snapshot/open/read 호출·Python read 요청 길이·실제로 반환한 bytes를 구분한다. 반환 즉시 bytes를 한 번만 더해 후속 오류에도 보존한다. 요청 길이 합계는 실제 할당·RSS·disk bytes가 아니다. Hashlib에 전달한 실제 bytes/호출, AST/JSON parse, HEAD/path/alias/negative 후보 검사의 논리적 호출도 기록한다. 성공 workload의 snapshot/hash/parse/검증 소비 수와 raw bytes는 같아야 하며 reader 호출 수·요청 길이·시간만 달라질 수 있다.

Git command별 시작 시도/생성/완료/return code/timeout/stdout·stderr 반환 bytes를 기록한다. Git 내부·OS cache·실패 syscall 내부 전달량은 unknown이다. 중첩 반환값을 이중 합산하지 않으며 통제 대상의 누락된 계측을0으로 채우지 않는다. Setup·각 경계·결과 저장 계수를 분리한다. Allocator tracing/RSS sampler/새 profiling framework는 추가하지 않는다.

Monotonic 경계 시간은 최초 검증부터 마지막 검증까지이며 receipt 쓰기 비용과 포함 총시간을 함께 보고한다. CLI300초는 setup·최대4경계·최종 persistence를 포함하는 도구 한도이며 서비스90초 변경이 아니다. 남은 시간으로 subprocess timeout을 제한하고 마지막 쓰기 뒤도 검사한다. Blocking I/O hard preemption은 보장하지 않고 늦은 반환은 실패로 보존한다.

`.local/meetings-proof-epoch-v1/`를 exclusive 예약하는 공식 CLI1회만 허용한다. 기존 output/partial failure가 있으면 삭제·덮어쓰기·재개·retry하지 않는다. 첫 실패와 후속 cleanup/persistence 실패, partial counters와 미실행 경계를 보존한다. Unique owned temp와 원래 실패 보존을 사용하고 disk passed만 믿지 않는다. Terminal summary·exit0·완전한4측정·무결성·최종 persistence/deadline이 맞아야 completed comparison이다. Raw exception/credentials/실제 품질 본문을 출력하지 않는다.

동등성/범위/무결성/계수 누락/저장/시간 실패는 즉시 종료한다. 정확하지만 같거나 느리면 observed improvement=false이며 재비교하지 않는다. 작은 요청 길이만으로 allocator 개선이나 전체 지연 감소를 선언하지 않는다. 개선돼도 후속 품질 후보 별도 등록 전 서비스 채택0이며 C5를 재개하지 않는다.

## NEW4 소유권과 실행 전 순서

- `src/doctrail/meeting_bounded_snapshot.py`: 원래 one-read와 bounded-reader, 같은 stamp/limit/오류 의미 및 명시적 계수.
- `scripts/probe_meeting_bounded_snapshot.py`: 고정 synthetic core 조합/fixture·무결성·단발 비교 CLI·safe receipts.
- `tests/test_meeting_bounded_snapshot.py`: bytes/limit/short read/error/변경 및 ABA 회귀.
- `tests/test_probe_meeting_bounded_snapshot.py`: 동일 소비 순서·계수·단발/partial/deadline/저장/HEAD 보호.

기존 코드 수정·monkeypatch·C5/옛 profiler/resource orchestration·closed default path 호출은0이다. 기존 순수 path/AST primitive를 명시적으로 재사용할 수 있지만 실제 read/hash/subprocess 계수 범위를 숨기지 않는다. 새 cache/proof 플랫폼을 만들지 않는다.

설계 커밋 → NEW4 합성 검증·원래 실패 보존 → 구현/dependency allowlist/fixture spec/roster/후보 상태/설계 동결 → 해당 커밋 필수 CI → 공식 CLI1회 순서다. 부모가 후속 source-freeze/fixture-spec/구현·CI receipt를 작성하며 현재 생성됐다고 주장하지 않는다. 별도 승인 파일이나 모델 실행계획 없이 CLI가 실행 SHA/protocol/freeze/spec hash를 기록한다. 구현은 설계 커밋 전0을 유지한다.

무료·로컬 일반 문서/복수 회의/혼합 근거/KO·EN/완전성/인용/보류/ACL/revision, Q&A90초와928/requested512/final384/input5120/context6144, freshcal6/6→isolatedval8/8은 불변이다. 평가 runner 비용과 실제 서비스 지연을 혼동하지 않는다. 기존 accepted Astra xhigh 설계 역할은 새 설정 주장을 하지 않으며 독립 output judge 제외를 유지한다. 이번 추가 접근은 허용 metadata hash·frozen snapshot 코드·공식 CPython 소스와 소유 초안뿐이고 닫힌 의미자료 접근0이다.
