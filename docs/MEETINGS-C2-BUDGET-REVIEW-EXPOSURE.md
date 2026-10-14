# 부분 진단 심사자의 사전 메타데이터 노출 기록과 방법 수정

2026-10-14 · 설계만. 기존 전체 게이트 실패·선택 불가를 유지한다. 기존 design/helper/pack/receipt/schema는 수정하지 않는다. 새 서비스 추론·실제 의미 판정·임계값 변경·코드 변경은0이다.

## 결정

같은 `/root/c2_calibration_judge`가 **`metadata-exposed, label-masked posthoc diagnostic`** 조건으로14응답의 진단을 계속할 수 있다. 원래 의도한 모델/가설/과거 결과의 정보 격리는 실패했다. 이를 독립성 회복이나 완전 맹검으로 표현하지 않는다. 이번 변경은 닫힌 실패 실행의 오류 분석 방법을 좁히는 것이며 원래 비교/선택 프로토콜을 충족시키는 변경이 아니다.

부모가 전달한 심사자 자기보고에 따르면, fork-none의 Astra xhigh 역할도 pack 열기 직전에 앱/도구가 주입한 `AGENTS.md`를 통해 모델명·arm·과거 C0/C1/M5 결과·C2-CAL-08 언어 실패를 알게 됐다. 아직 pack·mapping·원문·seed·판정은 열지 않았고, 설계/구현/출처·문항/oracle 작성/사전검토에는 참여하지 않았다. 이 상태는 점수 작성 전 심사자가 다시 사실대로 확인하여 기록한다. 해시나 fork-none 설정만으로 과거 노출이 없었다고 증명하지 않는다.

계속할 근거는 **저자·설계자와 다른 판정자라는 역할 분리**와 **표본별 case/arm 대응표의 미열람**이 남아 있기 때문이다. 이미 full16 게이트는 실패했고 이번14개는 진단 자료뿐이다. 새로운 역할에서도 같은 지침 주입이 반복될 수 있으므로 끝없는 교체로 맹검을 주장하지 않는다. 유료 대안이나 새 모델 생성은 필요 없다.

## 판정 전에 별도 영수증 등록

부모/custodian은 기존 산출물 밖의 새 exposure receipt를 독점 생성하고 그 SHA를 **pack 열람·첫 판정 전에** 고정한다. 기존 receipt를 고쳐 과거 사실처럼 만들지 않는다. 최소 필드는 다음과 같다.

- 심사자 ID, 실제 모델/effort 확인 근거, 노출/자기보고/등록 시각과 시각의 출처. 알 수 없는 시각은 추정하지 않는다.
- `exposure_source=automatic_AGENTS_injection`, 노출된 정보 범주와 위 상태의 자기보고 원문 또는 hash/메시지 참조. 새 원문·정답·대응표는 추가로 노출하지 않는다.
- `original_information_isolation_met=false`, `review_mode=metadata_exposed_label_masked_posthoc_diagnostic`, `model_hypothesis_blind=false`, `prior_outcome_exposure=true`.
- `pack_seen_before_registration=false`, `mapping_seen=false`, `seed_seen=false`, `judgments_started=false`의 실제 상태와 저자/설계/구현/사전검토 비참여 확인. 어느 값이 이미 참이라면 허위로 false를 쓰지 말고 그 추가 노출을 별도 기록한다.
- 기존 partial design/helper/receipt/review pack의 hash 연결. 부모 전달 pack SHA는 `766fff31c98be0ac5e9f53f83ae766c7a129b8a800f29a010e43599ee6c367aa`; 실제 파일과 대조한다. 기존 full report/plan의 연결은 유지한다.
- `selected=false`, `validation_eligible=false`, `original_full_gate=failed`, `human_review_count=0` 및 이번 방법 수정 문서 SHA.

영수증 등록 뒤에만 기존14개 pack을 전달한다. 이미 생성된 pack·mapping·shuffle·포함14개·실패1·미실행1은 바꾸지 않는다.

## 판정과 해석의 한계

기존 Judgment schema의 `mapping_not_seen=true`는 **대응표 파일/동등한 항목별 연결을 아직 받거나 읽지 않았다는 사실**에만 사용한다. 스타일·반복 질문으로 arm을 추측할 수 있으므로 완전 익명성을 뜻하지 않는다. `independent_of_authors_and_designers=true`는 **해당 작성·설계 역할에 참여하지 않았다는 사실**에만 사용한다. 모델 정보나 과거 결과를 모른다는 뜻으로 확장하지 않는다. 해당 두 사실이 실제로 유지되지 않으면 true를 쓰지 않고 중단하여 추가 노출을 기록한다.

심사자는 기존 기준대로14개 전부의 원자 사실·선택 인용 지지·필수 사실 누락·언어/시점/대상/조건/상태를 판정한다. 기존 masking guess 필드에는 표본별 단위 스타일 추측/확신/근거를 사실대로 적는다. 노출된 과거 실패를 현재 표본의 오류 증거로 대신 쓰거나, 오류를 찾으려는 기대에 맞춰 임계값을 높이지 않는다. 이런 지시는 편향 제거를 보장하지 않는다. 표본 text에서 model/arm/case를 알아보았다는 추가 노출이 있으면 즉시 기록하고 최종 한계에 포함한다.

판정14개 완료 → 기존 schema/`score_sample` 일관성 확인 → 판정 SHA 잠금 → mapping 결합 순서는 그대로다. 점수·원문·인용을 수정하거나 모델 응답을 다시 생성하지 않는다. 잠금 뒤에 노출을 숨기기 위한 심사자 교체/좋은 점수 선택을 하지 않는다.

최종 diagnostic summary를 만들 때 새 exposure receipt hash를 필수로 연결한다. 기존 도구가 그 필드를 지원하지 않으면 원본 summary는 그대로 보존하고 **summary SHA와 exposure receipt SHA를 함께 묶는 별도 reporting receipt/보충 보고**를 만들며, 두 파일을 항상 같이 전달한다. 본문 첫 결과 설명에 “모델·과거 결과 메타데이터에 노출된, 표본 라벨만 가린 AI 사후 진단”임을 명시한다. 노출 사실을 내부 부록에만 남기지 않는다. 앞으로의 공개 보고/포트폴리오에도 같은 한계를 강조한다.

분모는 의미 진단14·완전쌍7·계획16·실행15·언어 실패1·미실행1로 유지한다. 결과는 유용한 결함 사례와 후속 무료 후보 가설의 근거일 수 있지만, 맹검 비교·후보 우열의 확증·서비스 채택·validation 진행 근거는 아니다. 전체 게이트 실패와 `selected=false/validation_eligible=false`는 어떤14개 판정 결과에도 변하지 않는다.

이 설계자는 실제14응답/validation 의미 내용을 읽거나 심사하지 않았다. 이번 작업은 이 문서 한 파일만 작성했다.
