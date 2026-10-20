# C6: bounded reader를 연결한 새 근거 답변 후보

2026-10-20. `meeting-answer-single-thinking-c6-v1`(`c6`)의 설계만 등록한다. [protocol](../data/evaluation/meetings-c6-protocol-v1.json)이 기계 판독 계약이다. 현재 허용된 쓰기는 이 두 설계 파일뿐이며 C6 구현·자료·문항·tokenizer·native·의미 판정은 모두 0이다. 실제 구현자·자료 역할·최종 judge는 아직 배정하지 않았다. 부모는 결과 보존·root 문서·Git·CI를 맡는다.

## 근거와 변경 경계

[reader 공개 집계](../experiments/results/meetings-proof-epoch-results-metadata-v1.json)의 단발 합성 비교는 request_start 12.531→10.969초, before_dispatch 3.141→2.047초였다. 비읽기 guard, hash bytes, 반환 bytes, Git 이벤트가 같았다. 고정 reference-first 순서 n=1이고 OS cache·배경 부하를 통제하지 않았으며 전체 C5 runner가 아닌 합성 core다. 읽기 요청 크기는 실제 allocation/RSS/물리 I/O 측정이 아니다. 이 결과는 새 후보에 작은 통합을 시험할 근거이며 안정적 절감률·C5 성공 반사실·서비스 성능 증거가 아니다.

C5는 두 번째 요청의 deadline으로 닫혔다. 첫 요청 89.859초 중 native prompt+prediction 51.395077초와 initial proof 19.687초가 기록됐지만 나머지 시간을 Git 비용으로 단정하지 않는다. 두 번째 요청의 native timing은 없다. C5 원본·미실행분·실패·false flag와 모든 옛 pool은 불변이며 재개하지 않는다.

**C5 대비 실행 동작의 변경은 파일 snapshot의 64KiB bounded read 연결뿐이다.** 새 후보 ID·경로·역할·fresh 자료는 독립 실행을 위한 등록 차이다. GPU28, cached Qwen3.5-9B Q5_K_M, build `d81235049384534c167caea52b85a694f6103d14`, 답변 policy/schema/transport를 유지한다. 실행 ID C6와 재사용 policy ID `meeting-answer-single-thinking-c4-v1`를 분리한다. 새 prompt·모델·설정·resource/profiling loop를 추가하지 않는다.

## 최소 NEW8과 reader 연결

설계 커밋 뒤 별도 구현 지시를 받은 역할이 다음 NEW8만 소유한다. 지금은 구현 승인이 아니다.

- `src/doctrail/meeting_c6_review.py`, `tests/test_meeting_c6_review.py`
- `scripts/prepare_meeting_c6_inputs.py`, `tests/test_prepare_meeting_c6_inputs.py`
- `scripts/probe_meeting_c6_quality.py`, `tests/test_probe_meeting_c6_quality.py`
- `scripts/audit_meeting_c6_quality.py`, `tests/test_audit_meeting_c6_quality.py`

Review는 C6 family/ID 타입과 동일 판정 규칙, prepare는 경로·source/item·proof·offline 준비, probe는 단발 실행과 deadline/ledger/실패 보존, audit는 익명 pack·lock·gate replay를 담당한다. C5의 candidate 상수·Literal·기본 경로가 고정되어 있어 새 namespace가 필요하다. 별도 adapter·policy·launcher·범용 평가 core는 만들지 않는다. 새 probe의 고정 연결 함수가 기존 GPU launcher를 `gpu_layers=28`로 호출하며 CLI 설정 선택을 제공하지 않는다.

새 prepare 내부에 작은 명시적 read 연결을 둔다. 동결된 `doctrail.meeting_bounded_snapshot.read_snapshot(target, meter, candidate=True)`를 사용하며 reader 선택은 production CLI 옵션이 아니다. 필요한 의존성 인자는 새 코드 안에서만 전달하고 frozen module/global/builtins를 monkeypatch하지 않는다. 동일 입력의 prompt/schema/request bytes는 기존 정책과 같아야 한다.

연결 범위는 (1) `source_manifest` 내부 `Snapshots.get`, (2) 그 `unchanged`의 새 instance, (3) caller `Snapshots.get`와 `unchanged`, (4) `GitProof`의 매 호출 fresh worktree read/hash, (5) cache miss 시 committed helper의 별도 fresh read, (6) 준비·전송 직전·감사에서 사용하는 같은 새 snapshot 경로다. 바깥 Snapshots만 바꾸고 내부가 원래 read에 남는 구현은 수용하지 않는다. Meter는 safe count만 수집하며 원문/추가 파일 쓰기·profiling CLI를 연결하지 않는다.

기존 consumer 순서와 횟수를 보존한다. `source_manifest`의 내부 read→내부 unchanged→caller read→CI_HEAD Git proof→HEAD Git proof→caller unchanged를 합치거나 반복해서 이득을 만들지 않는다. 전체 C6 proof에는 기존 role/plan/source/item guard도 남는다. 현재 HEAD, committed bytes, path containment/reparse-point/alias, negative import 상태, 입력 메모리 일치, 마지막 fresh read/hash를 유지한다. 기존 `(revision,name)` Git blob proof cache의 의미만 유지하며 새 raw/hash/parse/epoch cache나 경계 간 freshness 생략은 없다.

Reader는 동일 16MiB+1 sentinel까지 `min(65536, remaining)`으로 읽는다. nonempty short read는 계속하고 EOF 또는 sentinel에서 멈춘다. 전체 bytes/stamp를 반환하며 overflow 거부가 마지막 stamp 검사보다 앞선다. read/close/invalid-return 오류는 부분 성공으로 바꾸지 않는다. 청크와 결합 bytes는 O(file size) 메모리이며 전체 메모리64KiB를 주장하지 않는다. 동시 수정에 대한 atomic snapshot 보장은 없다. reference가 관측한 중간 변경이나 ABA를 candidate가 놓치는 합성 회귀는 성능과 무관하게 실패다. 모든 관측 사이에서 발생·복원된 변경은 양쪽 모두 놓칠 수 있다.

기존 C5/C4/reader 비교/host profiler의 `prepare/check/run/replay/finalize/source_manifest` orchestration과 closed 기본 경로를 호출하지 않는다. 새 C6 orchestration에 코드로 검토한 순수 검증 primitive만 명시적 인자로 재사용한다. imports의 실행 부작용과 전체 연결 경로를 합성 검사에서 확인한다.

## 답변·시간·실패 계약

일반 문서·복수 회의·문서+회의에 대한 KO/EN 근거 자연어 답변을 유지한다. task lookup/인용 나열로 축소하지 않는다. 기존 `prepare_answer`와 `QualityThinkingGenerator.answer`, block catalog의 evidence ID enum, `{status, claims:[{evidence_ids,text}]}` 및 원문 quote/offset 확장을 그대로 사용한다. claims≤6, claim당 evidence1..4, native text minLength1, host text maxLength2000, 명시 언어·상태·완전성·인용·identity/config/cache/framing/reasoning-content 분리를 보존한다. 필요한 정보가 없으면 보류하고 기술 실패를 의미 보류로 위장하지 않는다. 정확 인용만으로 의미 지원·완전성을 인정하지 않는다.

입력5120/context6144/전체 출력928/requested thinking512/최종 JSON native 재토큰384, 자연 EOS, 요청90초/cleanup5초/요청 시작부터 cleanup 종료120초/phase1200초를 유지한다. Thinking512와 final384는 독립 native hardcap이 아니다. GPU28 요청·실효 offload/FA unknown, parallel1/batch512/ubatch128/fit off/seed0/greedy/cache off/FA AUTO/log-disable을 유지한다.

요청 t0는 첫 요청별 proof와 semantic parse 전이다. initial proof, 준비/template/tokenization, 전송 직전 reproof·durable 기록·callback, HTTP, 최종 검증/retokenization/mapping, 필수 persistence 모두 같은90초를 쓴다. Callback 뒤·마지막 필수 저장 뒤 remaining을 재검사하고 HTTP timeout도 외부 deadline에 묶는다. 늦은 반환은 실패이며 proof를 밖으로 옮기지 않는다. Startup/최초 phase preflight와 독립 심사는 별도 보고하되 blocking I/O hard preemption은 주장하지 않는다.

Cal≤6, 조건부 val≤8, 합계≤14 generation 시도다. Retry/warmup/repair/translation/self-review/fallback/추가 neutral/profile/resource/config ladder는0이다. 첫 structural/resource/deadline/language-guard/citation/config/무결성/persistence 실패에 phase를 즉시 닫는다. 부분 완료·미실행분·최초 원인·후속 cleanup/save 오류와 원본 flags를 별도로 보존하며 원인을 덮어쓰지 않는다. 구조를 통과한 의미 실패는 등록된 phase를 마친 뒤 독립 판정하되 재실행하지 않는다.

전송 예약, send-hook 시도, 파싱 응답, archival된 응답, 계약 수용을 구분한다. Send-hook은 wire 전달/생성 완료 증명이 아니며 archive 실패 뒤 모든 wire 수신을 알 수 있다고 주장하지 않는다. 원본 request/response/reasoning/token IDs는 제한된 local evidence에만 보존하고 운영 로그/public metadata에는 safe allowlist count/hash/time/code만 쓴다. Owned watchdog/cleanup, bounded discard drain의 emitted0·EOF·read/join 오류0을 유지한다. 저장 실패가 남긴 이전 passed receipt만으로 성공을 선언하지 않는다. CLI exit0·terminal summary·최종 receipt/replay·무결성의 일치가 필요하다.

## 구현 검증과 source 전 동결

합성 통합 검사는 C6 전체 read 연결과 동일 consumer sequence/count/hash/bytes, short read/overflow/error 우선순위, reference-detected mutation/ABA, HEAD/committed mismatch, alias/reparse point, negative candidate의 새 positive 전환을 다룬다. 예상하지 않은 새 positive/allowlist 밖 경로는 본문 읽기 전에 거부한다. Allowlist에 있는 기존 파일은 SHA 계산에 raw bytes 읽기가 필요하며, hash 불일치는 그 읽기 후 AST/semantic parse 전에 거부한다. Bytes를 읽지 않고 hash 변경을 알아낸다는 주장은 하지 않는다. Callback/저장 지연, late-send0, partial/final-save 실패 보존, phase gate와 익명화/lock 회귀도 fake clock/tokenizer/HTTP 및 새 합성 자료로만 확인한다. 원래 C5/reader 공식 실행은 재현하지 않는다. OS에서 지원하지 않은 검사와 최종 수정 전 검사 영수증은 구분한다.

모든 NEW8, reader/정책/adapter/transport/launcher와 전이 dependency, tests, 모델 manifest, 환경 lock, 설계2, 내용 없는 고정 family registry 및 negative import candidate 존재 상태를 새 toolchain freeze에 묶는다. Freeze 파일의 HEAD committed bytes를 먼저 증명한 뒤 봉인된 code allowlist/hash/존재 상태에 따라 discovery를 진행한다. 비허용 새 Python body를 읽고 나서 거부하는 순서는 금지한다.

정확한 frozen source commit의 push/PR 필수 backend/web/java-service CI를 확인하고 별도 CI receipt를 보존한 뒤 source 작업을 시작한다. 기록된 CI JSON/Git bytes 검증만으로 GitHub의 진위를 자동 인증하지 않으므로 부모의 실제 CI 관측 출처와 exact SHA를 구분한다. Reader 결과 b08cd76의 push39354041667/PR39354047589는 부모가 실제 관측한 영수증에서 모두3개 job 성공이며 protocol에 그 영수증 hash를 묶는다. 이는 아직 없는 C6 구현 CI가 아니다. 향후 toolchain freeze는 immutable이다. 실제 role/judge/자료 등록은 이후 실행 plan에 hash binding하며 toolchain을 소급 수정하지 않는다.

## Fresh source-first와 역할

자료 규모·의미 관문은 C5와 같다. Cal은 새 공개 family `c6-f01`와 새 합성 조직 `c6-f02`, val은 별도 `c6-f03`/`c6-f04`다. 각 family에 날짜가 다른 회의2+일반 문서1을 두어 split당6문서, 전체12문서다. 현재 family ID는 구성뿐이며 실제 repository/조직/원문/문항은 선택하지 않는다.

| Split/family | KO 답변 | EN 답변 | KO 보류 | EN 보류 |
| --- | ---: | ---: | ---: | ---: |
| cal 공개 | 1 | 1 | 1 | 0 |
| cal 합성 | 1 | 1 | 0 | 1 |
| val 공개 | 1 | 1 | 1 | 1 |
| val 합성 | 1 | 1 | 1 | 1 |

Cal6=KO3/EN3·답변4/보류2, val8=KO4/EN4·답변4/보류4. 각 split 답변4에 일반 단독≥1/복수 회의≥1/문서+회의≥1/필수 복수문서≥2/KO질문-EN근거≥1/EN질문-KO근거≥1, 항목당 필수사실3~6을 유지한다. 모든 충분한 근거 대안에 최소2문서가 필요할 때만 필수 복수문서로 센다. 보류는 family 전체에 필수정보가 없는지 검토하며 답이 있는 청크를 제외해 만들지 않는다. 전체 청크·좌표를 보존하고 token 피드백으로 자르거나 재선택하지 않는다.

도구 freeze+CI→실제 split 역할 등록→fresh source 채택/작성→독립 coherence/신선도 및 실제 Java/Python 처리 parity→source freeze/commit→그 이후 item/oracle/context 작성→독립 item prereview→item freeze/commit→각 split 공식 offline 준비1회 순서다. 계수 상한 실패는 종료이며 payload 수정·재계수로 살리지 않는다. 계수 전 거부된 draft는 보존하고 제한된 피드백으로 NEW version을 등록할 수 있지만 native 결과 기반 수정은 금지한다.

과거 자료 비교는 family/URL/revision/raw/normalized fingerprint metadata만 이용한다. 전체 NFC+줄바꿈 통일+whitespace collapse hash, 원본 blank-line paragraph 정규화≥200 codepoint hash, whole-document/cross-family/cross-split 중복 거부를 유지한다. 같은 family 긴 문단 반복은 item 전 독립 source reviewer가 이유를 남겨 수용/거부한다. Validation은 cal fingerprint에 결합하고 지정 isolated reviewer가 source 근접중복을 검토한다. 과거 coverage 누락과 의미 중복 검사 한계를 공개하며 닫힌 본문을 dedup 목적으로 다시 열지 않는다.

부모·설계·구현자는 validation 의미자료를 열지 않는다. 지정 isolated author/reviewer/custodian의 source/item/공식 offline 준비 접근과 validation 실행/audit 접근을 구분한다. 후자는 C6 원본 cal6/6+운영 무결성 gate를 metadata/body 전에 replay해야 한다. 같은 split source/item 역할 재사용은 공개하고 자신이 쓴 artifact를 검토하지 않는다. Cross-split 작성/검토 겸임은 금지한다. 도구 소스 코드의 toolchain freeze/commit·정확한 CI 확인을 먼저 마친 뒤 자료 역할을 등록하고 실제 호출 순서를 기록한다. Fresh 자료 자체의 commit을 그 자료 작성자 등록보다 앞에 요구하지 않는다. 별도로 item 작성은 검토된 자료 source freeze/commit 뒤에 시작한다. Git proof를 실제 작성 시각/과거 부재 증명으로 과장하지 않는다.

## 최종 답변 lock과 후속 artifact

첫 C6 품질 출력 전에 실제 수락한 별도 final judge2명을 등록한다. 부모·설계·구현·source/item 작성/검토·mapping-aware 실행/audit 역할은 제외한다. 실제 model/effort·역할 ID·이전 노출·64byte 독립 seed binding·pack 열람 전 attestation을 기록한다. 현재 배정/수락/seed는0이다. 자동 AGENTS와 공개 집계 노출도 기록하며 완전 맹검이라고 하지 않는다.

Pack에는 익명 sample ID, 질문/언어/context/oracle와 변경 불가한 최종 답변·인용만 포함한다. 중첩 case/family/candidate/author ID를 일관되게 가리고 mapping/model/time/native trace/reasoning을 제외한다. 자연어에 남은 식별자를 임의 rewriting하지 말고 pack을 거부한다. 필수·추가 사실의 지원/완전성, 주체·시점·조건·상태·언어·보류를 판정한다. **최종 judgment SHA를 잠그기 전 mapping/집계/진단 reasoning을 공개하지 않는다.** 새 audit는 reasoning 공개 단계를 제공하지 않으며 별도 사후 진단이 허용돼도 locked score를 고치지 않는다.

후속 artifact는 아직 생성되지 않았다. 부모/지정 custodian이 `meetings-c6-family-registry-v1.json`(내용 없는 구성, toolchain에 포함), `-toolchain-freeze-v1.json`/`-toolchain-ci-v1.json`, `-prior-source-fingerprints-v1.json`, `-role-registration-v1.json`(실제 역할 시작 전), split source/item freeze와 offline receipt, `-review-registration-v1.json`(첫 출력 전), `-execution-plan-v1.json`(양 split·judge·closure·출력/횟수 binding, 실제 cal 전 commit)을 순서대로 만든다. 경로는 모두 `data/evaluation/meetings-c6-*`이고 역할별 제한 local 경로는 후속 실행 plan이 고정한다. 새 승인 파일이나 별도 profiling plan은 없다.

원래 C6 cal6/6 완전정답+운영 무결성만 val을 연다. Val8/8, 미지원 사실/부적절 보류/언어/운영 실패0이 필요하다. 통과해도 자동 서비스 채택은 없다. Fixed-context 관문은 retrieval/ACL end-to-end나 Java 전체 지연/실사용자 만족을 입증하지 않는다. ACL 선적용·revision 일치·출처 접근·취소/실패 복구와 실제 서비스/사용자 검수는 별도 완료 조건이며 Phase1은 아직 미완료다.

설계자는 기존 승인된 Astra xhigh `/root/free_qa_candidate_review`다. 공개 C2 case-ID 요약, C3/C4 집계/코드, host/GPU scalar, C5 실패 metadata/replay, reader 집계/구현/동결/CI metadata와 허용 코드를 읽었다. 이 설계 작업에서 닫힌 raw report/trace/input/answer/reasoning/token IDs/source/question/oracle/isolated validation 의미자료는 읽지 않았다. 독립 output judge 제외를 유지한다. 설계 JSON/LF/hash 검사만 수행하며 구현·Git·테스트·tokenizer/native 실행은0이다.
