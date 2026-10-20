# C7 원문 수용 단계 결과

2026-10-20. **자료 단계 미완료 / 채택한 완전한 corpus 없음.** 제한된 탐색에서 적절한 공개 문서 묶음을 확보하지 못했다. 적절한 자료가 어디에도 없다는 뜻도, 모델 답변 품질이 나쁘다는 결과도 아니다. 전체 Phase1 목표는 계속 진행한다.

## 실제 수행과 결과

| 구분 | Calibration | 격리 validation |
| --- | --- | --- |
| 원문 전 실제 코드·역할·과거 metadata 증명 | 통과 | 통과 |
| 실제 기계적 admission | 1회 | 1회 |
| 공개 family 결과 | `c7_block_bounds` 거부 | `c7_block_bounds` 거부 |
| 합성 family 결과 | 기계 조건 통과, 독립 의미 검토 전 | 기계 조건 통과, 독립 의미 검토 전 |
| 추가 작성자 적합성 거부 | 2개 묶음 | 2개 묶음 |
| 채택한 완전한 corpus | 0 | 0 |
| Java parity / 문항 / tokenizer / native | 모두 0 | 모두 0 |

각 실제 admission은 공개 회의2개·일반 문서1개와 명시적 합성3문서를 입력으로 사용했다. 공개와 합성을 함께 충족해야 하므로 합성 family만 통과한 상태를 자료 채택으로 처리하지 않았다. 다른 탐색 후보에는 완료된 회의 결과가 아닌 안건이나 미작성 양식, 의미적으로 충분하지 않은 묶음이 있었다. 이런 자료를 완료 회의록으로 다시 분류하지 않았다.

작성자는 최초 실패 뒤 해당 원문을 자르거나 요약·재분할·제목 축약해 재제출하지 않았다. 실제 admission은 split별1회이며, 추가 적합성 검토는 새 원문 후보에 대한 작성자 판단이다. 독립 source prereview·accepted freeze는 수행하지 않았다.

## 보존과 확인 범위

수정 전 역할 경로 오류와 새 사전 증명은 [등록 수선 기록](../experiments/results/meetings-c7-role-path-repair-v1.json), [실제 사전 증명 metadata](../experiments/results/meetings-c7-source-preauthorization-v2.json)에 남겼다. 경로 수선d906614의 push39372004605와 PR39372010020 필수 backend/web/java-service는 모두 성공했다.

최종 자료 상태는 각 [calibration 기록](../data/evaluation/meetings-c7-calibration-v1/source-adoption-receipt.json)과 [validation 기록](../data/evaluation/meetings-c7-validation-v1/source-adoption-receipt.json)에 `incomplete/no_adopted_corpus`로 명시했다. 파일명에 adoption이 있어도 수용 증명은 아니다.

Calibration은 실제 제출 raw6와 다른 후보 원문·license·탐색 metadata를 포함한95파일, validation은 실제 제출 raw6·license·prospective manifest·안전한 결과 metadata의9파일을 공개 보존한다. 격리 validation의 상세 선정 판단과 추가 탐색 원본91경로는 local에 유지하며 부모는 본문 대신 path/hash/count만 확인한다. 서로 다른 공개 범위를 같은 규모로 합산해 해석하지 않는다.

두 실제 실패 영수증의 원본 SHA256은 각각 `5100bb987d71b3a98c3132f3c25a0e9e2e3535dbc62cee304428628a8f856f73`, `d69a42735911ee26019a736004c86932470ef2bd496e3794d319260d306c9cac`다. 동결 도구77파일·과거 닫힌 실험은 바뀌지 않았다.

원본 metadata14개의 CRLF는 경로별 Git 속성으로 보존한다. 최초 기본 공백 검사와 CRLF 허용 뒤 남은 원문5파일의 trailing whitespace/EOF 지적도 local에 남겼다. 원문 bytes를 고치는 대신 해당 원본에 한해서만 예외를 적용하고 새 설명 문서에는 기본 검사를 적용한다.

## 해석과 다음 작업

입력 크기 규칙을 코드로 검사할 수 있어도, 실제 문서가 의미적 충분성과 형식 제약을 함께 충족하는 것은 별도 문제다. `c7_block_bounds`라는 거부 코드만으로 어느 규칙이 주원인인지 또는 적절한 상한이 무엇인지 추측하지 않는다.

다음 작업은 코드·일반 합성 예시를 통한 제한된 처리 규칙 진단이나 별도 자료 가능성 검토를 먼저 결정하는 것이다. 거부 자료를 살리기 위해 동결 규칙을 바꾸거나 곧바로 새 도구 체계를 복제하지 않는다. 새 모델 품질·응답 지연·서비스 채택·사용자 검수 결과는 아직 없다. UI의 실제 Java 회귀 개선은 독립적으로 계속한다.
