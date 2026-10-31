# 회의 추출 요약 범위·제목 투영 개발 후보

2026-10-22. 이번 작업은 이 NEW 설계 문서1개다. 구현·offline 비교·모델 실행을 배정하지 않는다. 기존 single/batch-v1/batch-v2, frozen77, 소비된 공식/개발 실행과 원래 의미 판단을 보존한다.

## 읽은 근거와 원인 확정의 한계

- 허용된 `independent-extraction-v2/safe-model-review.json` SHA는 `d4edfac263954b1b8508e2126f3d1ac1c19404197059c20f5c316f126c9c5e62`다. 분류159건은 preferred138·허용11·명확한 범위 밖10이며 고정 gold 정확도가 아니다. 메타데이터 label16개가 모두 preferred이고, 그중 **제목은4개**다. Java 최초 ready 결과에서는 제목2개가 누락됐다.
- 안전 집계상 요약4건 모두 원문에 근거하지만 첫4 action 인용만 포함해 핵심 범위가 부족하다. item141개는 실제 content label을 빠짐없이 반영했다. 이 집계는 사용자 검수나 운영 수용이 아니다.
- frozen `meeting_worker.py:334–368`은 전체 분류 뒤 action→decision→unresolved→proposal→topic으로 정렬하고 첫4개를 요약으로 고른다. action이4개 이상이면 다른 유형이 밀리는 **코드 메커니즘**은 확인했다. 실제 변환 trace는 읽지 않았으므로 각 문서의 실행 원인을 확정한 것은 아니다.
- frozen `meeting_contract.py:114–148,293–308`은 title prefix 또는 H1 형식만 제목 값으로 투영하고, 미지원 형식은 빈 목록이어서 값과 근거를 함께 생략한다. 올바른 title label 뒤에도 누락될 수 있는 가장 이른 코드 경로다. 실제 누락2건의 원문 형식·중간값은 읽지 않아 이 경로가 실제 원인인지는 미확정이다.
- `MeetingAnalysis.java:15–30`은 지원된 제목/근거를 검증한 뒤 deepCopy하며, `MeetingService.java:49–52`도 정상 제목을 null로 바꾸지 않는다. `MeetingViews.tsx:36,87,98`의 문서 제목 fallback은 구조화 제목을 복구하지 않으며 요약은 발췌로 표시된다.
- generic 코드/검사, `MEETINGS-ANALYSIS-SCOPE-PLAN.md`, frozen77의 경로 목록만 추가로 읽었다. 실제 원문·label·oracle·private judgment·raw 출력은 읽지 않았다. 디자이너의 과거 합성 인용 상수 노출과 최종 judge 제외를 유지한다.

## 선택: 분류와 분리된 명시적 assembly 후보

새 `extraction_assembly=coverage-v1`을 선택한 **batch-v2**에서만 결정적 후처리를 바꾼다. 기본은 `legacy`이며, 기존 세 분류 정책의 이름·prompt bytes/SHA·grammar·모델 동작을 재해석하지 않는다. 기존 생성기를 그대로 사용하고 분류 결과를 한 번만 조립한다.

1. NEW `meeting_extraction_coverage.py`의 얇은 `CoverageMeetingRuntime(MeetingRuntime)`가 analyze 조립 부분만 교체한다. frozen `_run`, `partitions`, `classification_messages`, 실제 generator, `extraction_analysis`, `merge_analyses`를 재사용한다. frozen 파일 수정·전역 monkeypatch·분류 재호출·별도 전체 worker 복제는 하지 않는다.
2. 순수 `assemble_coverage(units, labels)`를 live 요청과 후속 offline 비교가 공통으로 쓴다. 원래 문서별 unit ID/순서/전체 quote/offset과 label을 그대로 받아 길이·정수 범위·ID 대응을 확인한다. 모델 의미를 regex로 다시 분류하거나 skip/item을 바꾸지 않는다.
3. unit160·item150·metadata30·summary4 한도를 유지한다. 제목을 별도 투영하기 **전** 전체 metadata 수를 검사한다. 원래 전처리/Purpose 정규화 범위 외의 축약·truncation은 없고 원문 quote/offset은 바꾸지 않는다. inference payload와 raw 파일 bytes가 같다는 주장은 하지 않는다.

## 요약 선택 규칙과 남는 한계

- 후보 순서는 **decision→unresolved→topic→action→proposal**이다. 결정·열린 문제·논의 맥락·다음 작업을 함께 보여주려는 일반 제품 선택이며, 개발 문구/문항별 점수가 아니다. 각 유형 안에서는 원래 unit 순서를 쓴다.
- 각 비어 있지 않은 유형에서1개씩 순환해 최대4개의 서로 다른 unit ID를 고른다. 빈 유형은 건너뛰고, 자리가 남으면 같은 순서를 반복한다. 최종 인용 표시 순서는 원문 순서다. 기존 topic 전용 `summary_boilerplate` 제외 규칙만 유지하고 새 문구 필터는 추가하지 않는다.
- 요약에 선택되지 않아도 전체 content items와 그 근거는 보존한다. 요약 후보가 없으면 기존 empty-summary 실패를 유지한다. 추출 인용을 연결한 요약이며 새 추상적 요약/중요도 추론/문장 생성은 없다.
- 이는 action 독점을 완화하는 **검증할 가설**이다. 유형5개와 슬롯4개가 모두 차면 뒤 유형은 빠지고, 유형 안에서도 앞 문장이 핵심이라는 보장은 없다. 잘못된 label·논의 관계·다른 unit에 걸친 핵심 내용을 해결하지 않는다. 동일4개 cap의 유형 분산만으로 핵심 요약 충분성을 주장하지 않는다.

## 제목 투영 규칙

- model label1인 unit만 제목 후보가 된다. 우선 기존 `metadata_values("meeting_title", quote)`의 지원 형식/값을 그대로 사용한다. 그다음 일반 Markdown ATX heading1–6의 본문, 그 외에는 한 줄 unit의 전체 literal quote를 사용한다. heading/prefix 제거는 값 투영이며 evidence quote/offset은 원래 unit 그대로다.
- 값은 비어 있지 않고 원문 quote의 연속된 부분이어야 하며 기존 Java 제목 한도200 codepoint 안이어야 한다. 빈 prefix/heading·여러 줄·한도 초과·투영 불가를 자르거나 조용히 null로 만들지 않고 `generation_unsupported_field`로 실패한다. label1이 아예 없는 경우의 null은 유지한다. 요청 제목/파일명/다른 문서로 값을 보충하지 않는다.
- 같은 값의 반복은 모든 근거를 유지하고, 서로 다른 값은 기존 `generation_conflicting_metadata`로 실패한다. 첫 값·다수결·가장 짧은 값 선택은 없다. 잘못된 title label의 의미 정확성을 literal 검증으로 인증하지 않는다.
- 기존 `extraction_analysis`는 summary/items와 **제목 외 metadata**에 그대로 적용하고, 제목만 위 규칙으로 조립한다. metadata evidence는 원래 unit 순서를 복원한다. 날짜/참석자/목적, item 종류·담당자·마감·상태, 정확한 source-span 검증은 바꾸지 않는다.

## 작은 구현 경계

| 범위 | 필요한 변경 |
| --- | --- |
| NEW module/test2 | 위 순수 조립 함수·얇은 runtime 및 독립 generic 회귀. frozen `meeting_worker.py`, `meeting_contract.py`는 수정0. |
| 기존 service/test2 | `ServiceRuntime`에서 legacy/candidate runtime 명시 선택. normal/observer가 같은 실제 generator와 outer lock/deadline을 쓰며 health에 실제 assembly를 별도로 표시. |
| 기존 worker launcher/test2 + combined launcher/test2 | `--extraction-assembly legacy\|coverage-v1`을 start_services→start_service→load_runtime까지 전달. 기본legacy, unknown/비호환 정책 거부, 실제 health/lifecycle과 선택 일치. |
| 기존 acceptance driver/test2 | manifest/registration/validation gate의 effective assembly가 정확히 같아야 한다. 생략은legacy만 의미하며 CLI override는 없다. 로드되는 새 module도 legacy를 포함해 항상 code binding에 추가. |

대략 NEW2+기존8 파일 안에서 필요한 diff만 낸다. Java/UI/DB/schema, 기존 분류 adapter와 공식 closed manifest는 변경하지 않는다. 기존 observer에는 assembly 이름·선택 summary ID/유형·제목 후보/투영 여부와 고정 실패 이유를 별도 진단으로 남기되 native 호출 수에 섞지 않는다. analysis 본문 계약에 진단 필드를 넣거나 문구/비밀값을 운영 로그에 출력하지 않는다.

batch8/입력4096/출력128/EOS, GPU28, 분석 공유120초·답변90초, startup120/active1500/cleanup5·전체1625초와 소유 정리/첫 실패/최종 seal·exit gate는 그대로다. 새 조립·관측 비용도 같은 deadline에 포함한다. 환경변수 우회·자동 채택·retry/fallback은 없다.

## 한정된 generic 회귀

- action4개 초과와 다른 유형의 공존, 유형 일부 부재/단일 유형/4개 미만, 모든5유형의 cap 한계, 같은 문구의 별도 ID에서 선택 규칙·순서·전체 item 보존을 확인한다. topic boilerplate만 기존대로 제외하며 empty-summary와 기존 수 한도 실패를 유지한다.
- 기존 title prefix/H1, 일반 H2–H6/평문 제목, Unicode offset/200 경계, label1 없는 제목 모양, 빈/다중 줄/초과 값, 같은 값의 반복 근거와 서로 다른 값의 충돌을 대조한다. 원문 내 지시문은 데이터로 남고 label/내용을 조작하지 않는다.
- legacy의 고정 기대 결과와 single/v1/v2 prompt bytes/SHA를 보존한다. normal/observer의 명시 선택·기본값·불일치 거부·deadline 내 조립·분류1회·추가 native0을 확인한다. Java의 현재 strict schema/source-span 계약을 충족하는 generic 결과도 확인한다.
- 현재 개발 자료 문구나 label 배열을 unit test에 복사하지 않는다. mock label은 결정적 조립 계약만 증명하며 실제 의미 개선/사용자 수용은 증명하지 않는다. 구현 후 독립 코드 검토와 정확한 source commit의 기존 CI를 먼저 완료한다.

## 모델 재호출 전 NEW offline assembly 비교

1. 위 코드 검증 뒤 부모가 별도로 명시 dispatch한 경우에만 기존 custody 담당이 새 결과 경로에서 실행한다. 이 문서는 replay 권한이 아니다. 원래16 개발 입력, 저장된159 label, 문서별 unit mapping, 최초 Java 결과, source-only annotation/기대 의미와 기존 판단·실패·seal은 bytes/hash 그대로 유지한다.
2. 원래 문서별 **실제 분류 unit ID/quote/offset과 저장된 label의 정확한 대응**을 확인해 순수 조립 함수에 입력한다. 새 tokenizer/분할/모델/Java/browser/답변 호출은0이다. mapping을 입증할 수 없으면 중단하고 현재 원문으로 비슷한 unit을 재구성하지 않는다. source/label custody와 실행은 디자이너·metadata-only 부모와 분리한다.
3. 새 code·assembly 정책·입력 binding과 결과만 기존 방식으로 보존한다. 원래 최초 ready 결과와 비교할 때 Java가 부여한 item UUID 등 기존 wrapper를 명시적으로 대응시키고, summary/title/해당 evidence 외의 item·metadata·원문 좌표가 같아야 한다. 원래 결과를 덮어쓰거나 성공 상태로 재발행하지 않는다.
4. 독립 의미 검토자는 이미 잠긴 전체159 source annotation(`b233c5cf…`, 기존37 lock 포함)과 기대 의미를 바꾸지 않고 새4개 summary/title을 재검토한다. literal 근거, 핵심 범위, 잘못 추가/누락된 제목을 판단하고 기존 결과와 비교한다. 결과를 본 뒤 기준/문항/label을 고치지 않는다. 부모에게는 안전 집계만 반환한다.
5. 이 비교는 **같은 실제 label을 조건으로 한 후처리 효과**다. 원래 실행 trace가 없던 제목 누락의 실제 경로를 소급 확정하거나 분류 개선·새 native 성능·Java/React 통합·소유 정리 통과로 주장하지 않는다. 기존 개발/공식 실패의 상태와 소비 여부는 바뀌지 않는다.

## 진행·중단과 남은 범위

- literal/충돌/span/전체 item 보존이 깨지면 후보를 중단한다. 독립 검토에서 제목 누락 해소와 요약의 핵심 충분성을 각각 판단한다. 타입이 늘었어도 핵심 범위가 계속 부족하면 미해결로 보존하며 cap 확대·자료 축약·특정 문구 선택·첫 값 fallback으로 통과시키지 않는다.
- 분류 오류10개, 그중 확약/action 누락3개, 집단 담당자 추출 한계와 질문-답변 관계 경고는 이번 조립/replay로 해결됐다고 하지 않는다. 추출 요약이며 추상 요약 또는 전체 회의 의미 완전성도 보장하지 않는다.
- offline 효과가 확인된 뒤에만 별도 prospective native 서비스 검증을 검토한다. 실제 사용자 경로의 정확한 코드/assembly/JAR/UI binding, 명시 once dispatch, 기존 시간·실패·cleanup 기준과 독립 의미 검토가 필요하다. 추가 호출은 이 설계로 승인되지 않는다.
- 이후 fresh 실제 자료의 라이선스/provenance·전체 원문/indexing·ACL·revision/deletion·cal6→독립6/6 판단 lock→val8·test 격리는 그대로다. 노출된 합성 개발 비교는 held-out 품질 증거가 아니며 공식 closed 자료의 재실행이나 새 준비/registry/framework를 만들지 않는다.

이 문서 작성 중 새 원문/label/실제 출력 읽기, 구현·검사·offline replay·모델/tokenizer·Java/browser·Git 실행은0이다. 실제 사용자 검수·배포·최종 품질 수용을 주장하지 않는다.
