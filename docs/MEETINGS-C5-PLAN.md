# C5: GPU28 고정 단일 사고 근거 답변 계획

2026-10-16. 후보 `meeting-answer-single-thinking-c5-v1`(short ID `c5`)의 설계 사전등록이다. [protocol](../data/evaluation/meetings-c5-protocol-v1.json)과 이 문서만 새로 작성한다. C5 source·질문·oracle·tokenizer·native·의미 판정·사용자 검수는 모두0이며 작성자·검토자·최종 judge는 아직 배정하지 않았다. C4 및 모든 옛 pool, GPU source59와 원본 observation20은 불변이다.

## 선택 근거와 변경 범위

[GPU pair](MEETINGS-GPU-PLACEMENT-RESULTS.md)는 같은5064입력/521출력에서 전체71.485→63.453초, native prompt+prediction59.010206→38.068836초를 관측했다. 검증·전송 전 증명은12.172→25.094초로 늘었다. GPU28의 새 품질 관문을 시도할 근거로 사용하며 proof 최적화를 동시에 도입하지 않는다. Pair는 fixed order n=1, 배경 부하 미통제이며 실제 offload/Flash Attention은 unknown이다. GPU28 종료 시 장치 여유686MiB는 peak·process VRAM·동시 실행 적합성의 증명이 아니다. 짧은 marker 성공은928 decode나 일반 Q&A 성공을 입증하지 않는다.

**추론 설정의 유일한 변경은 GPU layers 요청24→28이다.** 같은 캐시 Qwen3.5-9B Q5_K_M, manifest/build/alias/tokenizer, prompt·schema 생성 정책, 단일 thinking transport, seed0/greedy, cache off, batch512/ubatch128/parallel1/fit off, FA AUTO 기본값, log-disable을 유지한다. 새 자료는 폐쇄 pool 재사용을 피하기 위한 필수 변경이므로 C4와 C5 품질 점수 차이를 GPU의 인과 효과라고 해석하지 않는다.

실행 후보 ID는 C5다. 재사용하는 `meeting_answer_thinking.ANSWER_POLICY`와 adapter 내부 policy ID `meeting-answer-single-thinking-c4-v1`는 그대로 기록한다. 외부 manifest/receipt는 `candidate_id`와 `reused_policy_id`를 구분하고, C5를 C4로 위장하거나 frozen 상수를 monkeypatch하지 않는다. 같은 입력에 대한 prompt/schema bytes는 기존 정책과 같아야 한다. 입력에 따른 evidence ID enum 차이는 허용된 동적 schema 값이다.

## 답변과 시간 계약

일반 문서·복수 회의·문서+회의의 근거를 이용한 완전한 자연어 Q&A와 명시적 KO/EN 응답을 유지한다. 담당자 조회나 인용문 나열로 대체하지 않는다. 기존 `prepare_answer`, block catalog, `QualityThinkingGenerator.answer`를 수정 없이 사용한다. `{status, claims:[{evidence_ids,text}]}`를 받고 서버가 원문 quote/chunk/절대 offset으로 확장한다. 필수정보가 빠지면 전체 보류하되, 질문에 없는 조건을 만들어 보류하거나 기술 실패를 보류로 바꾸지 않는다.

기존 schema/guard를 그대로 보존한다: claims≤6, evidence1..4, nonblank ID enum, native text minLength1, host text maxLength2000, 상태/빈claims 대응, 명시 언어·정확 인용·공통 identity/config/cache/framing/reasoning-content split 검사. 새 큰 반복·pattern·minLength·prompt rewrite·marker validator·stress=True는 추가하지 않는다. 정확 인용만으로 의미 지원·완전성을 통과시키지 않는다.

전체출력928 / requested thinking512 / 최종 JSON native 재토큰384 / 입력5120 / context6144 / 요청90초 / cleanup5초 / 요청 시작부터 cleanup 종료120초 / phase1200초를 유지한다. 512와384는 서로 독립된 native hardcap이 아니며 품질 종료는 자연 EOS만 허용한다. 잘라내기·length 종료 수용·예산 확대는 없다.

요청 `t0`는 **해당 요청의 첫 proof와 semantic parse 전**이다. 요청별 HEAD/bytes/path/metadata proof, 준비·template·input tokenize, dispatch 직전 재증명·durable 기록·callback, HTTP, 최종 검증·retokenize·mapping·필수 결과 persistence가 같은90초를 소비한다. Callback 뒤 남은 시간을 다시 검사하고 HTTP timeout은 외부 deadline을 넘지 못한다. 마지막 필수 쓰기 반환 후에도 deadline을 확인하며 늦은 완료는 실패다. 모델 startup과 최초 phase preflight, phase 요약·독립 심사는 별도 구간으로 보고하되 요청별 proof를 밖으로 옮겨 성공시키지 않는다. 일반 blocking I/O의 hard preemption 보장은 주장하지 않는다.

기존 owned cleanup/drain/watchdog를 유지하며 native emitted0/EOF/read·join오류0을 요구한다. 요청·응답·reasoning·token IDs는 별도 원본 artifact에만 보존하고 운영 로그는 safe code/count/hash/시간만 기록한다. GPU pair를 재실행하거나 resource sampler를 품질용으로 확대하지 않는다. 전송 예약, send-hook 시도, 파싱/archival된 응답, 계약 수용은 별도 계수하며 wire 전달·생성 완료를 추측하지 않는다.

## 최소 구현 소유권

설계 커밋 뒤 실제 구현 역할이 맡을 NEW8은 다음과 같다.

- `src/doctrail/meeting_c5_review.py`, `tests/test_meeting_c5_review.py`
- `scripts/prepare_meeting_c5_inputs.py`, `tests/test_prepare_meeting_c5_inputs.py`
- `scripts/probe_meeting_c5_quality.py`, `tests/test_probe_meeting_c5_quality.py`
- `scripts/audit_meeting_c5_quality.py`, `tests/test_audit_meeting_c5_quality.py`

기존 C4 review의 family Literal/oracle 타입과 phase 경로가 C4에 묶여 있으므로 새 C5 review 계약만 namespace에 맞게 만든다. 판정 기준·coverage·scoring은 유지한다. 별도 policy/adapter/server/launcher 파일은 만들지 않는다. 새 probe 내부의 고정 연결 함수가 `serve_meeting_gpu_placement.start_llama(gpu_layers=28, ...)`를 호출한다. C5 CLI에 GPU 선택 옵션을 노출하지 않는다.

새 prepare는 C5 경로·freeze·source/item 계약·once-only offline 준비, probe는 C5 실행계획·ledger·90초·첫 실패 보존, audit는 익명화·판정 lock·gate replay를 소유한다. 기존 순수 snapshot/hash/path/Git proof, catalog/schema, 판정 primitive는 검토한 명시적 인자와 함께 재사용한다. C4/옛 실험의 `code_contract/load_material/prepare/check/run/replay/finalize` orchestration이나 기본 closed path를 호출하지 않는다. 옛 `source_files()`의 고정 seed를 C5 closure로 쓰지 않는다. 재사용 import의 body 접근 부작용도 검사한다. 범용 평가 프레임워크로 확장하지 않는다.

새 계약의 최소 검증은 C5 ID/경로와 기존 policy ID 구분, GPU28 고정 및 나머지 argv 동일, frozen policy/schema/guard parity, 전후 callback 지연·마지막 저장 지연의90초 실패, late-send0, HEAD/bytes/alias/negative import 후보 drift의 본문 읽기 전 거부, 단발 예약·원래 실패 보존, 원문 없는 telemetry, 익명 pack의 중첩 ID masking, 판단 lock 전 mapping 차단, cal 미통과 시 validation body 이전 거부다. Fake tokenizer/HTTP/clock/합성 자료로만 검사하며 실제 tokenizer/native로 테스트하지 않는다.

전체 dependency closure·테스트·prompt/schema 생성 코드·manifest·환경 lock·설계·내용 없는 고정 family 구성 registry를 새 동결에 결합한다. 여기서 registry는 실제 역할 배정이나 judge 등록을 포함하지 않는다. Toolchain freeze/CI 뒤 각 역할 시작 전에 생성하는 실제 role 등록과 첫 출력 전 judge 등록은 후속 실행계획의 별도 hash binding으로 증명하며 toolchain freeze를 소급 변경하지 않는다. 동결 JSON의 committed bytes/HEAD를 먼저 증명한 뒤 봉인된 allowlist와 import 후보 존재 상태를 검사하고 새 후보 본문을 읽기 전에 거부한다. 이 검사는 filesystem 전체 잠금이 아니라 관측 경계의 증명이다. 해당 커밋의 필수 CI를 확인하기 전 새 source를 채택하거나 작성하지 않는다.

## 자료 규모와 source-first 순서

내용 없는 후속 family registry를 먼저 등록한다. 각 split은 서로 다른 새 공개 family1개와 새 합성 조직1개, family당 날짜가 다른 회의2개+관련 일반 문서1개로 **calibration6문서 / isolated validation6문서, 총12문서**를 고정한다. 검토 범위를 더 늘리거나 source 수를 토큰 피드백으로 조정하지 않는다. 공개/합성 provenance와 이용 조건·revision은 별도 표기한다.

| Split / family 역할 | KO 답변 | EN 답변 | KO 보류 | EN 보류 |
| --- | ---: | ---: | ---: | ---: |
| cal / 새 공개 | 1 | 1 | 1 | 0 |
| cal / 새 합성 | 1 | 1 | 0 | 1 |
| val / 별도 새 공개 | 1 | 1 | 1 | 1 |
| val / 별도 새 합성 | 1 | 1 | 1 | 1 |
| 합계 | 4 | 4 | 3 | 3 |

Cal6은 KO3/EN3·answered4/abstained2, val8은 KO4/EN4·answered4/abstained4다. 각 split 답변가능4개에 일반 문서 단독≥1, 복수 회의≥1, 문서+회의≥1, 필수 복수 문서≥2, KO질문/EN근거≥1과 EN질문/KO근거≥1을 둔다. 항목당 필수 사실3~6개다. 모든 충분한 근거 대안에 최소2문서가 필요한 경우만 필수 복수 문서로 센다. 보류는 family 전체를 검토해 필수정보 부재를 확인하고 답이 있는 청크를 제외해 만들지 않는다. Context는 비어 있지 않은 전체 청크이며 자르기·요약·token 기반 재선택은 없다.

순서는 (1) 이용 조건/revision/처리 규칙 → source 채택/작성 → 독립 coherence/신선도 검토와 실제 Java/Python 전체 청크·좌표 parity → source freeze/commit, (2) 그 이후 질문/oracle/context 작성 → 독립 item prereview → item freeze/commit, (3) 그 뒤 split별 공식 offline 계수1회다. 상한 초과는 종료이며 수정·재계수로 이 등록을 살리지 않는다. 독립 검토가 거부한 draft는 보존하고 피드백 범위의 NEW version과 재검토를 계수 전 완료할 수 있으나 native 피드백을 이용한 수정은 금지한다.

신선도는 과거 family/URL/revision/raw/normalized fingerprint metadata만 사용한다. 닫힌 본문·질문을 dedup용으로 열지 않는다. Unicode NFC, CRLF/CR→LF, whitespace collapse 전체 SHA와 원본 blank-line paragraph의 정규화 길이≥200 codepoint SHA를 사용한다. 전체 문서 중복 및 cross-family/cross-split 긴 문단 중복은 거부한다. 같은 family의 긴 문단 반복은 회의 이력일 수 있으므로 item 작성 전에 독립 source reviewer가 근거를 붙여 수용/거부한다. 원문은 유지하며 질문에 맞춰 source를 편집하지 않는다. Validation 신선도는 cal fingerprint에 결합하고 독립 격리 역할이 split 간 의미 근접중복도 검토한다. 누락된 과거 fingerprint 범위를 공개하며 근접중복0을 보장하지 않는다.

## 역할 등록·독립 판정·실행 관문

다음 artifact는 **아직 생성·배정되지 않았으며** 부모/지정 custodian이 조건에 맞춰 후속 생성한다.

- `meetings-c5-family-registry-v1.json`: source 작업 전 구성/IDs/노출만 등록.
- `meetings-c5-role-registration-v1.json`: source/item 역할 시작 전 실제 role ID·모델/effort·split·허용 경로·이전 노출·시작 순서 등록. Source/item author와 자신의 prereviewer는 분리하고 split 사이 작성/검토 겸임은 금지한다. 같은 split의 source와 item 역할 겸임은 명시하며 자신이 작성·수정한 artifact를 검토하지 않는다.
- `meetings-c5-review-registration-v1.json`: 첫 품질 출력 전 서로 다른 final judge2명의 실제 수락·설정·제외역할 검사·attestation·독립 seed를 등록. 현재 judge ID나 수락을 만들어 넣지 않는다.
- `meetings-c5-toolchain-freeze-v1.json` 및 CI receipt: 구현·합성 검증 뒤, source 작업 전. Prior fingerprint index도 source adoption 전에 내용 없는 metadata 범위로 등록한다.
- Split source/item freeze·offline receipt와 `meetings-c5-execution-plan-v1.json`: 위 순서에 따라 생성하고, 실제 cal 실행 전에 양 split binding·judge attestation/seed·전체 closure·횟수와 출력 경로를 커밋한다.

부모·설계·구현 역할은 validation source/question/oracle/의미 검토를 열지 않는다. 지정 isolated author/reviewer/custodian만 source/item/offline 준비를 위해 접근할 수 있다. 실제 validation 실행/audit의 semantic read는 C5 원본 calibration gate replay를 먼저 통과해야 한다. Source commit/CI 뒤 실제 역할 호출 순서를 receipt에 남기며 Git 증명을 실제 작성 시각이나 이전 파일 부재의 자동 증명으로 과장하지 않는다.

부모·설계·구현·source/item 작성/검토자·mapping을 아는 실행/audit 담당은 final judge에서 제외한다. Pack 열람 전에 자동 AGENTS를 포함한 기존 결과/후보 가설 metadata, raw/reasoning/mapping/이전 판정 노출을 attestation에 기록한다. Metadata 노출이 있으므로 완전 맹검이라 부르지 않는다.

Judge pack은 익명 sample ID, 질문·언어·context·oracle, 최종 claims/citations만 포함한다. 중첩 원래 family/case/candidate ID와 author ID를 일관되게 가리고 mapping·시간·모델명·native trace·reasoning은 제외한다. 최종 답변의 모든 필수/추가 사실, 인용의 의미 지원, 주체·시점·조건·상태·언어·보류를 판정한다. 모든 judgment SHA를 잠근 뒤 mapping/집계를 열며 reasoning으로 점수를 보정하지 않는다.

C5 cal≤6, 조건부 val≤8, 합계≤14 native 생성 시도다. Retry/warmup/repair/번역 재호출/self-review/fallback/추가 neutral/설정 사다리는0이다. 첫 structural/native/deadline/language-guard/citation/config/무결성/저장 실패에 phase를 즉시 닫고 미실행분·첫 원인·뒤의 cleanup 오류를 보존한다. 구조를 통과한 의미 실패는 등록된 phase 전체를 모아 독립 판정하되 재실행하지 않는다. Cal의 원래6/6 완전정답+운영 무결성만 val을 연다. Val8/8과 미지원 사실·부적절 보류·언어·운영 오류0을 요구하며 자동 서비스 채택은 없다.

이번 설계 역할은 실제 Astra xhigh `/root/free_qa_candidate_review`다. 공개 C2 case-ID 실패 요약, C3/C4 집계와 구현, host profile metadata, GPU pair report의 허용 timing/count/RSS/GPU metadata 및 공개 결과를 읽었다. GPU 입력/응답/reasoning/token IDs나 observation 원문, 닫힌 품질 본문·oracle·validation 의미자료는 읽지 않았다. 새 자료 작성/계수/모델 실행도0이며 독립 output judge 제외를 유지한다.

이 fixed-context 관문은 검색 품질·Java 전체 지연·사용자 만족을 입증하지 않는다. 통과 뒤 서비스 연결과 실제 Java/React 권한·revision·실패/취소·출처 열기 및 사용자 검수는 별도 완료 조건이다. 무료·로컬만 사용하며 Phase1/전체 goal은 아직 미완료다.
