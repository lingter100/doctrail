# 무료 QA 비교 adapter 구현 배정
2026-10-27 · 설계만. [수용 결정](MEETINGS-FREE-QA-NEXT-DECISION.md)·[준비 계약](MEETINGS-FREE-QA-PREPARATION-PLAN.md)·[취득 gate](MEETINGS-FREE-QA-ACQUISITION-GATE.md)의 목표·자료·예산·판정은 그대로다.

## 파일 소유와 현재 구조
구현자 한 명에게 아래 **새 5파일만** 배정한다. 기존 candidate/test source2(bb24dc62/cb7c249b), src 공통 모듈, 자산 준비 코드·프로필, schema1–5·v7·서비스 기본값은 수정하지 않는다.
| 새 파일 | 책임과 인터페이스 |
| --- | --- |
| `tools/free_qa/policy.py` | 깊게 불변인 `ModelPolicy`, `EpochPolicy`, `ComparisonContract`; `bind_policy(profile_bytes, reviewed_binding, runtime_refs)`와 `validate_contract(contract, trusted_locks)`의 순수 검증 |
| `tools/free_qa/adapter.py` | `PairedQAAdapter(GGUFGenerator)`; `load(prepared)`·`complete_qa(case_id, messages, deadline)`; 모델 정책·epoch·필수 resource callback·clock·evidence sink를 명시 주입 |
| `tools/free_qa/runner.py` | `verify_contract(...)`, `prepare_model(...)`, `launch_model(prepared, deadline, metrics)`, `run_epoch(registration, expected_sha, once_sha)`; 경로/자산·6개 QA·once·terminal/custody 연결 |
| `scripts/probe_meeting_free_qa.py` | `verify`와 명시적 `run --registration ... --sha256 ... --once ...`만. 모델/cap/template/env override·다운로드·자료 생성 옵션 없음 |
| `tests/test_meeting_free_qa.py` | 공개 합성 transport/clock/process/filesystem 이중체로 아래 경계 검증; private 사례·모델·native·live RAM 없이 실행 |
비교 schema1은 policy의 exact-key 계약으로 정의한다. 빈 해시를 채운 실행 등록을 미리 만들지 않는다. 실제 등록·6개 자료·기준·판정 packet은 별도 역할/후속 배정이다.
현재 `CandidateAdapter.load/_request`, `command/checked_assets/launch`, `validate_input/diagnose/execute`는 단일 profile/model과 자료4개·QA4회에 결합돼 있다. 이들을 호출하거나 상한을 전역 교체해6개로 만들지 않는다.

## 명시적 정책과 자산 연결
`ModelPolicy`는 허용 model_id, 원본 profile 경로/SHA, 순서 있는 전체 shard(이름/바이트/SHA), 첫 진입 파일, template 원문 SHA·tokenizer KV binding, runtime55/서버/tag/commit, 검토 receipt SHA를 갖는다. dict/list까지 복사·동결한다.
3B는 기존 Ministral3 Q5_K_M profile(2b4d19c1…)의 단일 파일, 7B는 이미 구현된 Qwen2.5 Q4_K_M 준비 profile(6cb34ab5…)의 두 shard만 허용한다. 프로필 형식은 명시적으로 각각 변환하며 추측/fallback은 없다.
7B 두 shard는 기존 준비 계약의 4,683,073,632B·정확 이름/SHA를 그대로 사용하고 첫 shard만 `--model`에 준다. 병합·양자화·runtime 교체는 없다. runtime은 기존 b11429/d8123504의 별도 root와 정확55개 참조를 재사용한다.
alias는 순서 있는 전체 자산 binding의 canonical SHA로 계산하고 명령·props·응답에 동일 적용한다. 단일 shard SHA로 나머지를 대신하지 않는다. 3B도 같은 정책 식별 방식을 쓰되 기존 QA HTTP 요청 바이트에는 alias 필드가 없으므로 요청 동등성을 별도로 검사한다.
`PreparedModel`은 이번 실행의 정책과 full SHA/크기/경로/파일 신원 대조 결과만 연결하는 임시 객체다. 등록자가 직렬화한 prepared/verified 플래그나 props의 파일명만으로 승인하지 않는다.
`bound_path/check_ref`·`safe_member/linked`를 재사용하고 `assets.regular/identity/small_bytes`로 hardlink·reparse·동시 변경을 보완한다. runtime은 `runtime_path_set`의 정확55개 목록, 모델 root는 모델별 허용 목록으로 추가/누락/혼합을 거부한다.
기존 `assets.KVReader`를 그대로 재사용할 수 있으나 Qwen 전용 `validate_metadata/inspect_assets/acquisition_complete`를 3B에 적용하지 않는다. 3B의 기존 자산 영수증과 모델별 내장 metadata 검토 결속이 없으면 그 정책도 미완성이다.
새7B 실물 취득·내장 metadata 검토는 아직0이다. 준비 profile의 base/API template와 원본 관측 revision은 내장 값/변환 commit을 채우는 대체값이 아니다. 실제 관측→별도 검토→잠긴 binding 순서를 요구한다.
취득은 기존5GiB/6GiB/30분/metadata32MiB/cleanup5초 그대로 별도 배정한다. 같은 attempt/root/profile/소스의 실제 CLI exit0·최종 stdout·종료/custody가 모두 확인돼야 다음 단계로 넘어가며 실패 root를 verify-only로 복구하지 않는다.
현재 준비 CLI가 외부 증거를 자동 검사한다고 주장하지 않는다. 비교 등록에는 담당자가 수용한 외부 gate/custody와 metadata 검토의 정확 참조를 요구하며 둘 중 하나라도 없으면 run 거부다.

## transport와 QA 의미 보존
`GGUFGenerator.__init__/_request/_complete/begin_request/end_request/close`의 loopback·token·trust_env=false·redirect 금지·bounded HTTP·GREEDY·응답 설정 echo를 직접 재사용한다. transport를 새로 쓰거나 mock/native 경로를 자동 선택하지 않는다.
`load`만 명시적 정책 seam으로 구현한다. 양쪽 전체 shard hash/검토된 metadata·실제 canonical 첫 경로·alias·build·ctx=6144·slot=1·awake를 대조한 뒤 `_alias/_metadata`를 설정하고 startup 마감을 다시 검사한다.
`_prepare`는 기존 CandidateAdapter와 같은 messages-only `/apply-template`, add_special=false/parse_special=true/with_pieces=false `/tokenize` 경로다. 상위 GGUF의 enable_thinking kwargs/캐시 경로를 무심코 상속하지 않고 template 덮어쓰기·suffix·추가 사고 호출을 넣지 않는다.
`_request`는 super 전후에 같은 deadline/resource callback을 검사하고 completion 직전 cap을 차감한다. tokens 배열/정수 count/timings.predicted_n 일치·echo·EOS를 기존 후보 수준으로 확인하며 실패 latch를 보존한다.
`complete_qa`는 QA 전용으로 중복 case를 거부하고 `QA_GRAMMAR`,256,`QA_COVERAGE_CONTROL.system()`을 고정한다. 요청 마감 없이 호출할 수 없으며 begin/end_request를 finally로 짝짓는다. summary/review stage는 제공하지 않는다.
원문은 `meeting_units`·`source_payload`, 메시지는 `qa_request_messages(..., QA_COVERAGE_CONTROL)`·`source_wire_messages(..., COMPACT_WIRE)`, 파서는 `grounded_answer_refs`를 그대로 재사용한다. prompt의256 안내와 parser/grammar 사이 기존 범위 차이도 임의 정렬하지 않는다.
복수 문서는 사전 봉인한 손실 없는 bundle/경계/제목/순서와 원문 좌표 sidecar를 검증한다. 각 문서의 units를 bundle 좌표로만 이동해 경계를 넘는 병합을 막고, 봉인된 ID0–159와 원 document/revision/좌표 mapping을 보존한다.
양쪽에 같은 원문·질의·compact 메시지 바이트·grammar를 전달하고 template/tokenizer 이후의 토큰 차이는 기록한다. 입력4096 초과는 원문을 줄이지 않고 고정 분모에 거부로 남긴다. 단위/ID/좌표 계약 부적합은 실행 전 등록 거부이며 삭제/요약/재번호로 고치지 않는다.

## runner의 등록·수명주기
새 contract는 exact key/type/중복key 거부와 두 정책·runtime55·명시적 import code closure·prompt/grammar/parser·입력/sidecar·고정 제외index·허용6개·criteria/packet hash·순서·예산을 결속한다. legacy CODE_FILES를 변경하지 않고 새 closure를 별도 고정한다.
`verify`/import/help는 metadata/schema 검증만 하며 모델 body·tokenizer·native·네트워크·live 자원·once 소비0이다. 실행 시의 full 자산 재검증은 `prepare_model`에서 별도로 수행하고 startup/whole 마감 안에 포함한다.
자료 작성·사전 기준 검토는 지정된 source-only 역할이 필요한 원문·질의를 읽되 모델 출력은 보지 않는다. 실행자는 승인된 원문·질의만 읽고 비공개 기준 의미·채점은 읽지 않는다. 판정자는 사전 기준과 필요한 원문·질의·익명 출력을 읽는다. 부모/구현자는 opaque ID·hash·lineage·안전 집계만 읽는다. 사전·자동 문맥 노출을 기록하고 완전 맹검을 주장하지 않는다. 누락 exclusion catalog·중복/조상 중첩·임의 denylist·추가 파일을 거부한다.
neutral1·baseline6·candidate6는 공통 비교계약에 결속된 별도 등록/output/once다. 중립 성공과 terminal/custody를 선행조건으로 두고 고정 모델 블록/질문 순서를 바꾸지 않는다. 한번에 한 모델만 적재한다.
`worker_lease`의 기존 GPU/worker/llama 3개 경로, `unused_port/wait_ready`, `DiscardDrain`, `owned_create_time`, `cleanup_owner`, `Evidence`를 직접 재사용한다. 새 launcher는 정책 인자 연결만 담당하며 기존 candidate launch를 복제해 다른 정리 구현을 만들지 않는다.
환경의 LLAMA_ARG_* 제거·offline·임의 token·localhost·명시 argv를 유지한다. ctx6144/parallel1/GPU99/f16KV/fit off/reasoning off/cache off/no-context-shift/greedy seed0를 실제 명령과 응답에 검사한다.
각 등록에서 Popen 직전 fresh RAM gate1회(available8GiB), 실패면 native0/반복 관측0이다. 시작과 활성 양 지점에 **기존 singleton RSS6_RESOURCES**를 넣어 `make_resource_guard`를 사용하고 callback·arm·실패 latch를 우회하지 않는다.
품질 epoch startup120/active900/cleanup5/whole1025초, 중립120/60/5/185초다. source 준비·tokenization·전송·생성·파싱·필수 저장은 요청60초를 공유하고 전체 잔여 마감보다 길어지지 않는다. 상위 기본120초로 fallback하지 않는다.
완료 dispatch 전 품질6회/epoch(1536토큰), 중립1회(256)를 차감하며 응답 유실에도 환급하지 않는다. 총13생성/요청상한합3328을 공통계약과 선행 영수증으로 제한하고 process 재시작·같은 case 재호출을 막는다.
내용/형식 거부는 분모6에 남기고 계속한다. 자산/protocol/자원/시간/정리 오류는 비교 전체 STOP, 나머지는 미실행이다. 중립 실패면 품질0이며 임의 예열·자동 retry·prompt 변형·모델 교체가 없다.
소유 Popen handle/PID+ctime만 정리하고 identity 취득·drain 생성 실패도 기존 cleanup_owner를 호출한다. first failure와 cleanup secondary failure·부재·전후 자산/입력/code hash를 함께 보존한다.
Evidence의 xb 저장·seal은 재사용하되 읽기/쓰기/최종 검사 뒤 마감을 재확인하고 늦은 성공은 무효로 남긴다. 실제 CLI 종료0·최종 stdout·정확 once·custody가 없는 기록은 완료로 수용하지 않는다. 저장 장애/무응답 I/O/OS hardcap 보장은 주장하지 않는다.

## 구현자가 제출할 의미 있는 검사
1. 기존 source2 hash/AST 불변; 공개 합성 사례에서 3B의 apply-template/tokenize/completion 요청 바이트·QA system/grammar·기본 설정이 기존 CandidateAdapter와 동일. 변경되는 정책 alias/관측 metadata는 명시 분리.
2. 정책 deep-freeze·exact schema·두 모델 교차 오염·불완전/미검토 binding·전체 shard alias·누락/추가/교체/혼합·첫 경로 위조·template/tokenizer/runtime55 mismatch·hardlink/reparse/동시 변경 거부.
3. 복수 문서 경계·빈 간격·한글/영문/이모지/CRLF·ID/원문 좌표와 byte 보존, 제외index/lineage/허용목록 우회,4096 초과 때 completion0·원문 불변. 실제 private 자료 대신 기존 공개 합성 fixture/가짜 metadata만 사용.
4. 실제 상속 HTTP 경로에서 bounded body/redirect/timeout·echo/cache/tokens/EOS 불일치,6/1 cap·중복 case·응답 유실·한쪽 STOP·순서/선행 custody/once 변경을 주입해 후속 dispatch0을 확인.
5. 가짜 clock/process/RAM으로 시작8/활성2/RSS6 양 지점과 latch, tokenization·parser·증거/terminal 지연, PID 재사용·초기 신원/drain 실패·cleanup5·기록 실패를 확인. 기존 합성 회귀는 별도 실행 결과로 남기고 실제 적합성으로 세지 않는다.
6. pure import/help/verify의 model/network/native/resource/once 부작용0, CLI override 거부, 유효/거부/실패/미실행 분모·13/3328 상한·안전 집계에서 private 본문 제외를 확인한다.

## 배정 순서와 변하지 않는 판정
부모 공개·수용 후 새5파일 구현→독립 소스 검토→정확 CI를 진행한다. 실제 취득/metadata 검토/runtime 재검증과 새6개 봉인·새 등록·fresh gate/실행은 각각 별도 배정이며 컴파일·Java·브라우저·취득과 QA 실행/정리를 겹치지 않는다.
새6개는 답변 가능4/보류2와 일반 문서·복수 회의·혼합 문서/한국어·영어·혼합 원문을 그대로 요구한다. 기존 C1–C5/M5/v4–v7·validation/finaltest·예약/제외 가족은 재사용하지 않고256에 맞춰 요구를 줄이지 않는다.
새7B만6/6이면 후속 독립 격리 평가 후보, 둘 다6/6이면3B 유지,3B만6/6이면7B 탈락, 둘 다미달이면 비교 종료다. 같은6개 재튜닝·자동 다음 모델 탐색·7B 우위 가정은 없다.
이 진입시험은 일반 정확도·서비스 채택·영어 응답 검증·사람 검수·요약/review 성공이 아니다. 별도 새 가족의 격리 평가, 실제 검색/ACL·revision·UI·사용자 검수와 충분한 요약 목표를 유지한다.
이번 설계는 일반 코드/공개 안전자료의 읽기와 새 문서/receipt만 작성했다. 가중치·내장 metadata 실물·출력·비공개 질문/criteria/finaltest/validation 내용·runtime import·모델·토크나이저·테스트·다운로드·live RAM·Java·Git 실행은0이다.
