# 회의 분석 scope·intent 개발 후보

2026-10-22. 부모가 선택한 `batch-v2`의 설계다. 작성 범위는 이 NEW 문서1개이며 구현·검사·실행 권한을 부여하지 않는다. 기존 계획·frozen77·공식 closed v1/v2·validation/test 절차와 자료는 변경하지 않는다.

## 선택 근거와 주장 범위

- 부모가 확인한 개발 v1 안전 집계는 첫 회의37unit·5completion HTTP200/EOS·비잘림 뒤 `generation_conflicting_metadata`, 답변0이다. 이 실패와 미실행을 그대로 보존한다.
- 독립 source-only annotation을 먼저 잠근 뒤 비교한37건은 preferred32·허용 대안1·명확한 범위 밖3·조건부1이다. 최초 충돌은 서로 다른 회의의 날짜를 현재 회의 단일값으로 합친 scope 혼동으로 보고됐다. taxonomy 자체의 모호함도 포함하므로 고정 gold 정확도나 전체 제품 품질 수치가 아니다.
- 이번 후보는 현재 회의 메타데이터의 범위와 확약·제안·범위/한계 설명의 intent를 명확히 하는 **분류 prompt 변경**이다. 자원 확대·자료 축소·값 선택 규칙 변경으로 실패를 없애지 않는다.
- 디자이너는 generic 코드와 안전 집계만 사용했다. 과거 허용된 개발 browser 코드 읽기에서 합성 인용 상수에 노출된 사실을 유지하고 최종 judge에서 제외한다. 이번 설계에서 실제 source/annotation/label/output/comparison 의미 자료는 읽지 않았다.

## 보존 계약

- `single`과 `batch-v1`의 prompt·예시·직렬화된 messages bytes·기존 prompt SHA·grammar·동작을 보존한다. `CLASSIFY_PROMPT`, `CLASSIFY_EXAMPLES`, `classification_messages`와 frozen 추출/검증 함수는 수정하지 않는다.
- 새 `batch-v2`만 명시 선택한다. CLI/start API 기본 `single`, 기존 명시 `batch-v1`은 그대로이며 이름 재해석·자동 승격·환경변수 우회·fallback은 없다. 필드가 없는 실행 계획은 계속 `single`이다.
- 전체 TARGET·ID·순서·중복 문구의 별도 ID를 유지한다. 기존 Purpose heading 정규화와 원문 quote/offset 보존 범위도 같다. 새 문맥 첨부·요약·regex 의미 분류·원문 trimming·문항별 조정은 없다.
- batch≤8, 완성 template 실제 입력≤4096, 기존 deterministic 사전 분할, 출력128/EOS, 정확한 literal ID grammar와 정수 label0–9를 유지한다. 단독 입력 초과·응답 오류·관측 오류는 전체 요청 실패이며 retry/repair/부분 반환은 없다.
- 기존 모델·revision·GPU28·nonthinking·greedy·`cache_prompt=False`·분석 전체120초·답변90초·startup120/active1500/cleanup5와 전체1625초를 유지한다. prompt 길이 차이로 사전 분할/실제 호출 수가 달라질 가능성은 측정하며 한도를 올리지 않는다.
- `metadata_values`의 literal 추출, 서로 다른 단일 메타데이터 값의 충돌 검사, Java의 source-span 검증은 그대로다. first/earliest/majority 값 선택·충돌 무시·모델 응답 사후 재분류를 금지한다. summary는 기존 추출 요약이다.

## 새 prompt의 의미 지침

기존 batch 형식·예시를 재사용하고 아래 일반 지침만 별도 상수로 추가한다. 개발 원문 인용·문항별 답·기존37unit의 문구나 ID·진단 결과별 예시는 넣지 않는다.

1. `meeting_title`, `meeting_date`, `purpose`는 기록 대상인 **현재 회의 자체**의 제목·개최일·명시적 목적이다. 다른 회의의 인용·과거/향후 일정·작업 마감·자료 제목·프로젝트 목적은 그 단어/날짜가 있다는 이유만으로 현재 회의 메타데이터가 되지 않는다. 첫 등장이나 가장 이른 날짜를 선택 근거로 쓰지 않는다.
2. 제공된 TARGET와 함께 제공된 문맥에서 문장의 역할·적용 대상을 확인한다. 다른 TARGET의 label을 복사하지 않고 각 ID를 분류한다. 제목/date 모양만으로 scope를 확정하거나 문서에 없는 현재 회의 정보를 추론하지 않는다. 다른 회의의 내용도 그 문장의 실제 역할에 따라 topic/proposal/decision/unresolved/action/skip으로 판단한다.
3. proposal은 검토·채택 전 제안/선택지다. action은 수행 의무·구체적인 실행 약속/작업이며 담당자·마감 미상만으로 proposal이나 unresolved로 바꾸지 않는다. 이미 정해진 결정과 그 결정의 실행 작업은 문장의 주된 역할로 구분한다. 가정·희망·조건부 제안은 확약으로 올리지 않는다.
4. 범위·적용 대상·제약/한계를 설명하는 진술은 그 자체로 제안이 아니다. 설명/현황이면 topic, 아직 해결해야 할 질문이면 unresolved, 명시적으로 채택한 변경/합의이면 decision, 구체적인 실행 약속이면 action이다. 부정문·제외 범위라는 표면 형식만으로 label을 결정하지 않는다.
5. skip은 기존 구조/무관한 boilerplate 용도를 유지한다. 충돌을 피하려고 정당한 복수 메타데이터를 skip으로 바꾸라는 지시는 넣지 않는다. 실제로 서로 다른 현재 회의 단일값이 둘 이상 추출되면 기존 충돌 실패가 유지돼야 한다.

이 지침은 없는 문맥을 만들지 않는다. 현재 payload에는 전체 문서의 전역 scope 지도가 없으며 batch 경계 밖의 제목/관계가 필요한 unit은 여전히 모호할 수 있다. 그 경우 prompt-only 후보의 한계로 기록하고 통과를 주장하지 않는다.

## 작은 구현 경계

기존 batch 구현10파일 범위 안에서 정책 선택과 필요한 검사만 확장한다. 실제 diff가 불필요한 파일은 바꾸지 않는다. 별도 adapter 복제·설정 framework·registry·freeze 체계를 만들지 않는다.

| 파일 | 최소 변경 |
| --- | --- |
| `src/doctrail/meeting_analysis_batch.py` | `POLICIES`에 `batch-v2`; 기존 v1 상수 불변, 별도 v2 prompt 상수. `batch_messages(rows, policy="batch-v1")`는 v1 기본 bytes 유지. 기존 생성 루프는 그대로 재사용하고 얇은 v2 subclass의 정책 속성으로 prompt/metadata만 선택한다. |
| `src/doctrail/meeting_service_rag.py` | single/v1/v2 명시 factory 매핑, v2의 normal/observer 얇은 MRO 연결. 실제 generator에서 정책을 확인하고 health와 요청 선택을 일치시킨다. 현재 `isinstance→batch-v1` 및 `=="batch-v1"` deadline 분기를 v2도 정확히 처리하도록 고친다. |
| `scripts/serve_meeting_service_rag.py`, `scripts/serve_meeting_rag_service.py` | 기존 enum 전달·CLI choices·health 검사를 재사용해 v2를 노출한다. 요청 policy가 `start_services→start_service→load_runtime`와 lifecycle까지 같아야 한다. |
| `scripts/run_meeting_rag_acceptance.py` | 기존 명시 plan/registration policy·CI/code binding·validation gate 동일 정책 검사에 v2를 포함한다. adapter는 모든 정책에서 필수 binding이다. CLI override나 소비된 manifest 변경은 없다. |
| 기존5검사 파일 | `test_meeting_analysis_batch`, `test_meeting_service_rag`, `test_meeting_service_rag_launcher`, `test_serve_meeting_rag_service`, `test_run_meeting_rag_acceptance`에 아래 회귀만 추가한다. |

v2 health의 classification에는 정책 이름과 실제 v2 prompt SHA를 남긴다. 같은 grammar-policy SHA/caps는 유지하며 실제 batch grammar hash·IDs·토큰·종료 이유는 기존 observer에 기록한다. v1/v2 metadata를 혼동하거나 선택하지 않은 prompt가 native에 전달되면 시작/요청을 거부한다.

## 개발 검사와 독립 검토

- 구현 전 현재 single/v1의 system prompt·예시·전체 messages bytes와 prompt/grammar SHA를 고정 기대값으로 기록해 회귀 검사한다. 구현에서 새로 계산한 값을 자기 자신과 비교하는 검사는 보존 증명이 아니다.
- v2의 일반 지침이 실제 native payload에 들어가고 single/v1에는 들어가지 않는지 확인한다. normal/observer, 두 CLI, health/lifecycle, unknown policy, v1↔v2 gate 불일치와 생략된 정책의 single 해석을 검사한다.
- 새 generic 긍정/부정 사례는 현재 회의 날짜와 참조 회의/일정/마감, 현재 목적과 프로젝트/인용 목적, 확약과 조건부 제안, 범위 설명과 채택 결정/미해결을 대조한다. 기존 개발 자료 문구·37unit·문항을 복사하지 않는다.
- MockTransport는 지침/전체 TARGET 보존과 응답 처리 계약만 검증한다. 정당한 동일값 반복은 근거를 보존하고 서로 다른 현재 메타데이터 값은 계속 실패하는지, mock 라벨을 사후 수정하지 않는지 확인한다. mock에 넣은 정답은 모델 의미 개선의 증거가 아니다.
- 기존 순서·전체 처리·4096/128/EOS·중간 실패·단일 공유 deadline·cache·관측 실패·소유 정리·late Node exit·최종 증거 시간/판정 gate 회귀를 유지한다. 독립 코드 검토 뒤 정확한 구현 commit의 기존 CI를 확인한다.

## 동일 합성 입력의 새 개발 실행1회

1. 개발 v1은 소비된 실패로 봉인한다. 원래16개 합성 입력과 질문/기대 자료는 bytes·hash 그대로 유지하고, source-only37 annotation lock(`2ecd8cd5…`)과 원래 비교/실패 기록도 수정하지 않는다. 이것은 노출된 개발 집합의 정책 비교이며 fresh held-out 평가가 아니다.
2. 구현·독립 읽기 검토·정확한 코드 CI 완료 후, 기존 개발 harness에 `batch-v2` 및 **NEW `run-v2` 경로**만 필요한 범위로 연결한다. v1에 결속된 harness 원본/입력 binding/결과는 보존한다. 해당 harness 변경도 읽기 검토와 좁은 합성 경계 검사 뒤 정확한 hash를 고정한다.
3. 부모가 기존 기록 방식으로 최종 code10·harness2·JAR/UI·원래16입력·policy·CI를 새 binding에 고정하고, 별도로 명시적인 once dispatch를 해야 실행할 수 있다. 이 문서만으로 실행하지 않는다. 새 역할/준비·평가 체계를 만들지 않는다.
4. 실제 factory·batch-v2 health를 확인하고 같은 Java→CPU retrieval→worker→native→React 경로로 업로드6회·자동분석4회 후 원래6질문을 원래 순서대로 한 번씩 제출한다. 문항별 native answer≤1, 재분석/재검색 예행/자동 retry0. 전체 인용 확인 후 기존 소유자 편집·연결 흐름을 수행한다.
5. 실제 추출 결정이 없어 편집/연결 전제가 충족되지 않으면 의미 전제 실패와 미실행을 기록한다. 항목을 만들어 넣거나 분류를 바꿔 UI를 통과시키지 않는다. 모델 context는 실제 ACL 적용 검색 결과만 쓰며 기대 자료/annotation은 모델·검색에 주입하지 않는다.
6. 원래 시간·호출·full unit mapping·전체 선택 context·응답/인용·실패·미실행·owned cleanup 증거를 기존 경로에 보존한다. 첫 운영/시간/증거 실패에서 정지하고 자동 다음 실행은 없다. 마지막 증거 저장까지의 시간과 실제 exit·seal/hash·실패 marker 조건을 유지한다.
7. 기존 독립 검토자가 새 실제 추출 전체와 실행된6질문의 자연어 종합·근거·제안/결정·올바른 abstain을 판단한다. 원래37 annotation은 그대로 비교 기준으로 쓰고 모호한 허용 대안/조건부 판정을 숨기지 않는다. 새 부분의 의미 판단을 잠근 뒤 성능/진단을 공개한다. 부모는 metadata만 읽으며 사용자 검수로 표시하지 않는다.

## 진행과 중단

- v2도 scope 충돌·의미 불일치·단위 누락·운영 실패가 있으면 해당 결과를 보존하고 후보의 한계를 보고한다. 의미/자원 기준을 낮추거나 v1/v2의 성공 부분을 합쳐 전체 성공으로 만들지 않는다.
- v1이 멈춘 첫 회의는 같은 고정 annotation과 원본에 한해 paired 개발 비교가 가능하다. v1에서 실행되지 않은 나머지 분석/답변은 v2 신규 관측이며 개선 전후 비교라고 주장하지 않는다. 단일 순서·장비 실측으로 인과적 성능 배수를 주장하지 않는다.
- 합성 개발 전체 흐름과 독립 의미 검토가 충족돼야 별도 fresh 실제 자료 수용을 검토한다. 기존 라이선스/provenance·전체 원문/indexing·ACL·revision/deletion·cal6→독립6/6 lock→val8·test 격리 조건은 그대로다. 이번 설계는 공식 closed 자료의 세 번째 실행이나 validation/test 재사용을 허용하지 않는다.

근거는 현재 generic `meeting_worker.py:39,195,334`, `meeting_contract.py:114,245`, `meeting_analysis_batch.py`, 서비스/launcher/driver와 검사 계약 및 부모가 전달한 안전 집계다. 이 문서 작성 중 구현·실제 자료/출력 읽기·검사·native/tokenizer/서버·Git 쓰기는0이다.
