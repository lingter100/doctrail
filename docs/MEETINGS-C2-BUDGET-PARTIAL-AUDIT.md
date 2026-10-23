# C2-5120 중단 실행의 사후 부분 의미 진단

2026-10-14 · 설계 역할 `c2_budget_followup` (부모가 실제 Astra xhigh로 확인). 목적은 다음 무료/로컬 후보의 설계 근거를 얻는 것이다. **기존 full16 선택 게이트는 실패로 확정됐으며 이 진단으로 복구하지 않는다.** 새 추론·자료 작성/조사·코드 변경·테스트 실행은 없다. 설계자는 실제14응답과 validation 의미 자료를 읽지 않았다.

부모 전달 상태: source `bc03326`, plan `67490fd`; 준비40/40·새 자원4 통과 뒤 calibration16계획 중 native15, 구조 통과14, `C2-CAL-08/C2`의 영어 요청→한국어 claim에 따른 `generation_language_mismatch` 1, 남은L0 1미실행, validation0. 아래 숫자는 원본 재생으로 대조해야 하며14개의 의미 품질은 아직 모른다.

부모가 보존한 report는 `experiments/results/meetings-c2-input-budget-calibration-v1.json`,788,359bytes, SHA256 `c4acac4ce4c3af9c6a77988e86400ed6f31d7b4b0c7dd59e9d251b8041ab3486`이다. Plan SHA256은 `845554b865d6b3fbf362b6834e98b5323cf5c366cc01ea8cf01f3c870bd251db`다. 좁은 새 도구는 이 닫힌 두 원본을 정확히 바인딩하며 임의 partial report를 받는 일반 프레임워크로 넓히지 않는다.

## 1. 사후 범위 고정

부모/custodian이 새 `.local/c2-budget-partial-audit-v1/`에만 산출물을 독점 생성한다. 기존 plan/report/seed/source/input/oracle/audit 경로와 파일은 그대로 둔다. `purpose=post_hoc_partial_diagnostic`, `selected=false`, `eligible_for_selection=false`, `original_full_gate=failed`, `validation_eligible=false`를 모든 진단 영수증/요약에 적는다. `selection.json`이나 기존 gate 형식은 만들지 않는다.

포함 규칙은 **실행 순서상 이미 존재하는 구조 통과14개 전부**이며 의미 내용을 보고 고르지 않는다. 원본에서14개가 첫7문항의L0/C2 완전쌍인지 ID/arm/dispatch sequence로 확인한다.15번째 실패는 별도 오류 기록,16번째는 미실행이다. 누락·중복·추가 응답이 발견되면 진단 준비를 중단하고 임의로14개를 맞추지 않는다.

작은 산출물7개로 충분하다: `review-input.json`, `mapping.json`, `receipt.json`, `failure-replay.json`, `judgments.json`, `judgments-lock.json`, `diagnostic-summary.json`. 후속 구현은 좁은 새 도구/검사 두 파일 범위로 충분하며 새 공용 평가 프레임워크나 full16 audit 변경은 필요 없다. 기존 `JudgmentFile`, `score_sample`과 mapping을 읽지 않는 순수 `lock`을 재사용할 수 있다. 완전한8쌍을 요구하고 `passed`를 계산하는 `summarize`, 공식 `prepare/finalize/verify_validation_gate`는 호출하지 않는다.

## 2. 원본 재생 후 익명 pack

Custodian은 원본 report, 봉인 plan, calibration input/oracle/preparation receipt, 관련 동결 mapper/score schema의 hash를 연결한다. 단일 bounded snapshot의 같은 bytes를 hash와 parse에 사용한다. 원본 report의 실패 상태·15dispatch·중단 원인·미실행1과 기존 source 무결성 기록을 그대로 인용한다. 메타데이터를 읽는 것을 새로운 resource/quality 실행으로 계산하지 않는다.

구조 통과14개 각각에 대해 원래 payload·prompt·grammar·unit count·공식/native token·greedy/nonthinking/cache·EOS·90초·raw response 연결을 기존5120 계약과 대조한다. **실제 raw content를 원래 arm의 frozen catalog/mapper와 실제 요청 언어로 다시 처리**한 결과가 저장된 `status/reason/claims/citations`와 정확히 같아야 한다. 원문·인용 좌표·언어 또는 출력 내용을 고치지 않는다. 한 건이라도 재생 불일치면 pack 작성/판정을 멈춘다. 이 과정은 모델 호출이 아니다.

기존 plan에 사전등록되고 아직 사용하지 않은 calibration shuffle seed를 그대로 가져와 hash를 새 receipt에 묶는다. 새 seed를 뽑거나 여러 shuffle 중 고르지 않는다. Seed 원본은 custodian 전용 기존 경로에 보존하고 심사자에게 주지 않는다. Pack sample은 기존 구조인 `sample_id/question/contexts/oracle/answer`를 사용한다. 모든 제공 context와 고정 oracle는 그대로 포함하고 oracle의 ID만 익명 sample ID로 치환한다. Case ID/arm 연결은 mapping에만 둔다. Review pack에서는 모델·arm·시간·집계·실패 raw/설명·기존 판단·선택 gate·seed를 제외한다. 부가 원문 metadata가 arm을 암시하는 정도와 중복 질문/인용 폭으로 arm을 추측할 수 있는 한계는 남는다.

Receipt에는 original plan/report/input/oracle/preparation/source freeze hash,14개 raw/row 연결과 재생 통과, review/mapping/seed hash, 정확한 포함/제외 규칙, reviewer/excluded 역할을 묶는다. 의미 결론은 아직 적지 않는다. 부모/custodian은 원래 arm과 mapping을 알고 있으므로 독립 scorer로 간주하지 않는다.

## 3. 15번째 언어 실패의 별도 기록

`failure-replay.json`에는 case/arm/dispatch 번호, 요청 언어, 원본 raw·payload·prompt·grammar hash, native 종료/토큰/시간의 관측값, 실제 `generation_language_mismatch`, 같은 mapper 재생 시 같은 오류 발생 여부를 적는다. 원본 응답 text는 원본 report에 보존하고 복구한 정상 answer로 저장하지 않는다. Native 지표를 확인하지 않은 항목은 미확인으로 남기며 language failure가 다른 무결성 조건의 성공을 뜻하지 않는다.

동일 오류가 재현되지 않으면 그대로 불일치로 기록하고 전체 진단 잠금을 보류한다. 언어 인자를 한국어로 바꾸기, guard 생략, 번역, claim 수리, `answered`로 강제 변환, 정상 보류로 치환은 금지한다. 이 건은 `score_sample` 대상이 아니며 **관측된 언어/운영 실패1, 의미 채점 미실시**다. 나머지 사실·인용이 옳다는 뜻도, 틀렸다는 뜻도 아니다. 미실행16번째에는 raw 응답이나 가상 점수를 만들지 않는다.

## 4. 독립 판정과 잠금 순서

실행 전 예약한 calibration judge `/root/c2_calibration_judge`는 부모에 따르면 schema만 읽고 pack/실패 상세 없이 대기 중이다. 여전히 아무 원본/arm 대응/집계도 보지 않았고 모든 설계·구현·source/문항/oracle 작성·사전검토 역할에서 독립임을 확인하여 그 역할을 그대로 쓴다. 그렇지 않으면 노출 사실을 남기고 새로운 독립 judge를 배정한다. 부모, custodian, 이 설계 역할은 제외한다. Validation judge/자료에는 접근하지 않는다. 실제 모델/effort와 AI 검토·인간0를 기록한다.

Judge에게는14개 `review-input.json`과 기존 Judgment schema만 전달한다. 선택 인용만으로 각 주장의 필수·부가 사실 모두가 지지되는지, 질문 필수 사실의 포함 여부, 인용 관련성, 언어/시점/대상/조건/상태를 각각 판정한다. 모든 주장/인용/필수사실을 빠짐없이 대응시키고 최소 지지 offset과 masking guess를 적는다. 구조 통과를 의미 성공으로 추정하지 않는다.

판정14개 완료 → `JudgmentFile`의 역할/coverage 선언 및 각 `score_sample` 일관성 확인 → review/receipt/judgments hash와 reviewer·시각을 담은 lock 독점 생성 → 그 뒤에만 집계자가 mapping을 결합한다. **Lock 이전 judge에게 mapping·집계·다른 판정을 보여주지 않는다.** Custodian이 pack을 만들 때 mapping을 이미 안다는 사실은 숨기지 않는다. 기계적 schema 오류 수정이 필요하면 잠금 전에 해당 오류만 judge에게 전달하고 판정 초안/version을 보존한다. 부모가 대신 의미 판정을 채우거나 집계에 맞춰 바꾸지 않는다. 잠금 뒤 의미 변경은 이번 결과를 덮어쓰는 방식으로 처리하지 않는다.

## 5. 분모와 결과 한계

요약은 다음 분모를 별도로 쓴다.

- 실행: 계획16, dispatch15, 구조 통과14, 언어 오류1, 미실행1, validation0.
- 사후 의미 진단: **재생·판정이 완료된14응답 중 완전 적합 n/14**. 오류/미실행을 보류·정답으로 더하지 않는다.14개 판정이 완성되지 않으면 미완료 진단이다.
- Arm별/쌍별: 확인된7쌍의L0 n/7·C2 n/7, 개선/퇴보는 **사후의 완전쌍7개에만** 기술한다.8문항 결과나 선택 근거로 승격하지 않는다. C2의8번째 시도는 실패, L0의8번째는 미실행이라는 운영 상태를 붙인다.
- 인용 exact/관련성, 원자 사실 지지, 필수 사실 누락, 부가 사실 오류, 인용 폭은 각 실제 분모와 함께 별도 표시한다. 정상 보류의 빈 인용 rate는 `null`, 오류/미실행도 빈 인용100%로 계산하지 않는다.

최종 표시값은 항상 `selected=false`, `original_full_gate=failed`, `validation_eligible=false`다. 모든14개가 맞더라도 full16 완결성과 무오류 기준은 회복되지 않는다. 일부가 틀리면 근거와 추상 결함 범주를 잠긴 판정에서 보고하되 동일 pool의 prompt/guard 튜닝·재생성을 허용하지 않는다. 다음 무료 후보 설계의 근거로만 사용한다. 이 진단은 자원/언어 guard 완화, 새 추론, validation 실행 또는 서비스 채택의 승인이 아니다.

## 완료 기준

원본15/14/1/1 연결 및14개 무수정 재생, 실패1의 같은 오류 재생, 독립14개 판정·잠금·mapping 이후 집계가 모두 확인되면 **사후 진단 완료**다. 실제 의미 결함/개수는 그때 처음 보고한다. 이 설계 작성에서는 generic schema/pack 코드만 확인했고 결과 평가·artifact 생성·코드 변경·추론·테스트·validation 의미 접근은 모두0이다.
