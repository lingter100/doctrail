# 회의 분석 batch 개발 계획

2026-10-22. 부모가 선택한 다음 제품 개선 설계다. 이 파일은 구현·실제 실행 권한이나 평가 manifest가 아니다. 기존 v2는 소비된 실패로 보존하며 세 번째 공식 실행을 허용하지 않는다. 기존 frozen77·자료·문항·원래 결과는 수정하거나 재실행하지 않는다.

## 목표와 근거

자동분석이 모든 회의 단위를 다루면서 반복하는 native completion 수를 줄인다. 무료·로컬 모델과 Java→worker→native→React 경로를 재사용한다. 새 모델·서버·평가 도구 체계를 만들지 않는다.

- `MeetingRuntime.analyze`는 `partitions`의 모든 unit을 평탄화하고 `classify_bounded`를 호출한다(`meeting_worker.py:334–367`). 현재 GGUF 구현은 unit마다 completion을 호출한다(`meeting_gguf.py:276–289`). `LABEL_TOKEN_LIMIT=4`는 호출 수가 아닌 단일 라벨의 출력 토큰 상한이다.
- `partitions`·unit160·partition6·item150·metadata30 제한, 원문 보관·quote/offset·기존 증거 변환을 그대로 둔다. 긴 문서나 unit을 제거해 통과시키지 않는다.
- 현재 summary는 분류된 항목에서 규칙에 따라 최대4개 원문 구절을 고르는 **추출 요약**이다. batch 개선을 추상 요약 도입으로 설명하지 않는다. 자연어 다중문서 답변은 기존 별도 answer 정책의 역할이다.
- 이 변경은 분류 prompt/grammar/출력 형식을 바꾸는 새 분석 정책이다. 같은 모델이라는 이유로 기존 정책과 의미 결과나 자원 사용이 같다고 주장하지 않는다.

## 고정할 batch 계약

| 항목 | 개발 후보 `batch-v1` |
| --- | --- |
| 초기 묶음 | 원래 순서의 연속 unit, 최대8개 |
| ID | 해당 분석 요청의 전체 unit index, 0부터 시작; 같은 문구도 다른 ID로 유지 |
| 입력 | 완성된 chat template의 실제 토큰 수≤4096; 기존 nonthinking preamble 검증 |
| 출력 | batch당 `n_predict=128`(기존768 이내), 정확한 ID별 라벨 하나, EOS 필수 |
| 라벨 | 기존 0–9 정의·제안/결정/미해결/작업 구분과 예시의 의미 유지 |
| 시간 | 분석 전체의 기존120초 공유 deadline; batch마다 새 deadline 생성 금지 |
| native | 기존 Qwen/GGUF/revision/GPU28/greedy, `cache_prompt=False`, cache 검증 재사용 |

1. `classify_bounded(prompts, deadline)` 입구에서 모든 prompt의 기존 TARGET 형식과 ID 순서를 검증한다. 입력이 비거나 호환되지 않으면 고정 오류로 실패한다. 기존 prompt의 분류 지침·예시를 batch 형식으로 한 번 제시하고 전체 TARGET들을 JSON 데이터로 전달한다. 데이터 안 지시는 실행하지 않는다.
2. **TARGET 전체를 보존한다.** 기존 `classification_messages`가 Purpose/목적 heading에 적용하는 정규화만 유지한다. 원문 quote/offset은 그대로지만 batch payload가 원문 raw bytes와 같다고 주장하지 않는다. 새 정규화·요약·dedup·중요도 선별은 없다.
3. 각 묶음은 생성 전에 완성 prompt를 실제 토큰으로 수용한다. 초과하면 ID 순서를 유지한 절반 분할을 반복한다. 단독 unit도 초과하면 요청을 실패시킨다. 길이에 따른 사전 분할은 생성 재시도가 아니다. 이미 생성한 batch를 다시 생성하거나 실패 뒤 더 작은 묶음으로 바꾸지 않는다.
4. grammar는 해당 묶음의 ID를 원래 순서대로 literal로 고정한 `[[id,label],...]`만 허용한다. parser도 정확한 길이·ID·순서·정수형·라벨0–9·중복 없음·추가 내용 없음을 검증한다. grammar는 라벨의 의미 정확성이나 신뢰도를 보장하지 않는다.
5. 각 성공 batch를 원래 순서의 `{"label": int}` 목록으로 변환한다. 전체 ID가 정확히 한 번씩 처리됐을 때만 기존 `MeetingRuntime`으로 반환한다. timeout·길이 종료·invalid response·관측 실패는 전체 분석 실패이며 부분 분석을 반환하지 않는다. fallback·repair·자동 retry는 없다.
6. 입력 수용·template/tokenize·관측·completion 모두 같은120초 안에 포함한다. 기존 outer lock/watchdog/정리 순서를 유지한다. batch128은 고정 상한이며 실제 출력 토큰·종료 이유를 확인한다. EOS 실패를 성공으로 보정하지 않는다.

## 작은 구현 경계

- NEW `src/doctrail/meeting_analysis_batch.py`: `BatchedAnalysisGenerator(Qwen35Generator)`가 `classify_bounded`와 정책 metadata만 추가한다. `_prepare`/`_complete`의 기존 모델·template·native 응답 검증을 재사용하고 frozen 클래스는 수정하지 않는다. prompt/grammar builder·라벨·수용 규칙은 이 모듈에만 둔다.
- `meeting_service_rag.py`: 기존 `ObservedAnalysisGenerator`는 유지한다. `ObservedBatchedAnalysisGenerator(ObservedAnalysisGenerator, BatchedAnalysisGenerator)`를 얇게 추가하면 observer의 `super().classify_bounded`가 batch 구현으로 연결된다. MRO·observer 단일 기록·deadline 전달을 검사한다. 관측 코드를 복제하지 않는다.
- `load_runtime(..., analysis_policy="single")`: `single`은 기존 Qwen/ObservedAnalysisGenerator, `batch-v1`은 Batched/ObservedBatchedAnalysisGenerator를 선택한다. observer 유무가 분류 알고리즘을 바꾸지 않아야 한다. answer generator는 그대로다.
- `scripts/serve_meeting_rag_service.py`와 `scripts/serve_meeting_service_rag.py`에 `--analysis-policy {single,batch-v1}`를 추가하고 `start_services`→`start_service`→`load_runtime`에 같은 값을 전달한다. 기본은 `single`; 암묵 환경변수·자동 fallback으로 batch를 선택하지 않는다. 모르는 값은 시작 전에 거부한다.
- health의 extraction 분류 metadata에 선택 정책·batch cap·출력 cap·prompt/grammar 정책 hash를 표시한다. 조립 launcher는 요청한 정책과 metadata 일치를 검사하고 lifecycle에 선택을 남긴다. 실제 batch별 ID mapping·grammar hash는 기존 raw observer 경로에 남기며 부모용 metadata에 원문·라벨을 싣지 않는다.
- 다음 공식 실행 driver는 기존 plan에 `analysis_policy` 한 필드만 명시적으로 확장하고 등록·plan hash·코드/CI binding과 연결한다. 기존 필드가 없는 계약은 `single`로만 해석한다. `batch-v1`은 plan과 등록의 명시 일치 및 새 adapter 코드 binding이 필수다. 공식 CLI에는 정책 override를 만들지 않는다. 닫힌 manifest는 수정하지 않는다.
- 검사 파일은 NEW `tests/test_meeting_analysis_batch.py`와 기존 `test_meeting_service_rag.py`, `test_meeting_service_rag_launcher.py`, `test_serve_meeting_rag_service.py`, `test_run_meeting_rag_acceptance.py`에 필요한 회귀만 추가한다. 기존 source-first·prepare/probe/audit 도구나 registry/freeze 체계를 복제하지 않는다. 현재 별도 소유자의 driver 정리 수정이 반환된 뒤 그 위에 정책 연결만 얹는다.

## 의미 있는 합성 검사

- 1/8/9/160개 단위에서 순서·전체 처리·같은 문구의 다른 ID를 확인한다. 원문 evidence 좌표와 기존 Purpose 정규화·추출 요약 동작이 보존돼야 한다.
- token4096 경계·deterministic 분할·단독 초과를 확인한다. overflow에는 completion이 없고, 분할 후 모든 unit이 정확히 한 번 생성 요청에 들어가야 한다. 임의 trim이나 문항별 조정은 없어야 한다.
- 누락/중복/순서 변경/잘못된 ID·bool형 라벨·범위 초과·추가 필드·잘린 출력·잘못된 EOS를 거부한다. 중간 batch 실패에서 다음 batch와 부분 결과 반환이 없어야 한다.
- template/tokenize/observer/native 지연이 같은 deadline을 소비하는지, 응답 보관 실패가 다음 호출을 막는지, 요청 종료 뒤 입력 cache가 비워지는지 확인한다.
- 정상/observer 경로의 batch 선택과 `single` 기본 보존, 두 CLI 전달, 요청 정책/health 불일치, 등록 없이 batch가 켜지지 않는 경계를 검사한다. 기존 ACL·revision/deletion·answer·소유자 정리 회귀를 재사용한다.
- unit 총수·classification event 수·batch 수·native 시도/응답 수를 별도로 확인한다. 현재 unit/event 충돌과 늦은 Node 비정상 종료 수정은 별도 원본을 보존한 회귀로 다루며 batch 성공 조건을 느슨하게 하지 않는다.

## 새 합성 개발 실측

1. 기존 담당은 구현·독립 읽기 검토·CI와 병행해 **실행 전에** 새 일반 합성 자료6개(일반문서2+회의4), 고정 질문6개, 기대 의미/허용 근거를 작성할 수 있으나, 실제 native 실행은 구현·독립 읽기 검토·정확한 코드 CI 완료 후 정확한 코드 hash 고정과 부모의 명시 배정 뒤에만 허용된다. 기존 실제 평가 자료·문항·출력에서 문구나 답을 가져오지 않는다. 합성이라는 provenance를 유지하고 public 자료로 위장하지 않는다.
2. 짧은 회의와 여러 batch가 필요한 회의, 제안과 결정의 차이·상충/미해결·담당자 미정 작업·문서 간 종합·근거 없는 질문을 포함한다. 지원 한도와 운영 부담을 확인하도록 구성하되 실제 실패 자료의 길이에 맞춰 줄이지 않는다. 입력·질문·기대 의미·고정 코드 hash를 기존 개발 실행 기록에 남긴 뒤 부모가 native 개발 실행1회를 별도 배정한다. 새 역할/등록 시스템은 만들지 않는다.
3. 기존 launcher와 UI smoke 연결을 재사용해 실제 Java→CPU retrieval→worker→native→React에서 업로드6회·회의 자동분석4회·답변 요청6회를 수행한다. 분석/답변 수동 재실행은 없다. 합성 개발 실행은 공식 cal/val driver의 public/synthetic 수용 요건을 우회하거나 대체하지 않는다.
4. startup120·active1500·cleanup5, 분석별120·답변별90을 그대로 적용한다. 각 API와 native 호출, unit/batch mapping, 실제 선택 context 전체, 응답/인용, template/tokenize 수, prompt/decode 시간, 총 지연, 실패·미실행·소유 프로세스 정리를 기존 raw 증거 경로에 보존한다. 의미/개인 자료와 credentials는 일반 로그에 내보내지 않는다.
5. 독립 검토자는 합성 실제 출력의 라벨·제안/결정·근거·자연어 종합·올바른 abstain을 검토한다. 먼저 답변 판단을 고정한 뒤 성능/오류 진단을 공개하고 노출을 기록한다. 부모는 metadata만 읽는다. 테스트/mock 성공, 실제 모델 개발 출력, 독립 의미 판단, 사용자 검수는 구분한다.
6. 첫 운영·시간·증거·정리 실패에서 멈추고 원본을 보존한다. 코드 수정 뒤 추가 개발 실행이 필요하면 별도 명시 배정과 새 실행 경로를 사용한다. 자동 반복·성공한 일부만 결합·실패 unit 삭제는 없다. 이 문서는 그런 추가 실행이나 공식 세 번째 실행의 권한을 주지 않는다.

## 이후 실제 자료 수용과 중단 기준

- 합성 개발의 전체 흐름과 독립 의미 검토가 통과해야 새 실제 자료 수용으로 진행한다. 실패하면 구체적인 코드/정책 문제를 먼저 처리하며 작은 문서 선택이나 시간 상향으로 통과시키지 않는다. batch 품질이 나쁘면 이 후보를 보류한다.
- 기존 역할·서비스 driver·자료/문항 계약을 재사용한다. fresh source의 라이선스·provenance·원문 전체 보관, source 검토/문항 전 고정, cal/validation/test 분리와 최종 judge 독립성을 유지한다. 필요한 새 입력만 준비하고 닫힌 pool을 다시 실행하지 않는다.
- 각 split의 public 일반문서1+완료 회의2와 synthetic 일반문서1+회의2, calibration6→독립6/6·판단 lock·운영/정리 수용→validation8 순서를 유지한다. 이 설계에서 새 평가 manifest나 source 예약을 생성하지 않는다.
- 실제 검색 선정은 서비스에서 관측하며 oracle로 context를 넣지 않는다. 원문 전체 indexing, ACL 선적용, revision/deletion, 다중문서 종합·상충/제안/결정 구분·올바른 abstain·인용 정확성·Java/React 흐름의 기존 Phase1 요구를 유지한다. 검증되지 않은 항목은 완료로 계산하지 않는다.
- 실측은 해당 자료·장비·한 번의 실행 결과다. 다른 자료의 옛 실패와 비교해 인과적 속도 향상 배수를 주장하지 않는다. 호출 수 감소만으로 분석 의미 품질이나 자연어 답변 품질 성공을 주장하지 않는다.

작성 범위는 이 NEW 문서1개와 generic 코드 읽기다. 실제 source/question/oracle/output 의미 자료를 읽지 않았고 native·tokenizer·서버·테스트 실행 및 Git 쓰기는 하지 않았다. 기존 v2의 실패·집계 정정·정리 결과는 원래 실행 담당의 확정 기록으로 보존하며 이 설계가 이를 재판정하지 않는다.
