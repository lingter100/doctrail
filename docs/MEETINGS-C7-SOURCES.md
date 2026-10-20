# C7 새 원문 준비

2026-10-20. 구현9888255의 push/PR 필수 CI와 별도 CI 영수증 커밋27bc3da의 양쪽 필수 CI를 확인했다. 현재 실제 원문·문항·tokenizer·모델 실행은0이다.

## 목적과 순서

회의와 일반 문서를 함께 읽는 자연어 답변을 평가한다. Split마다 공개 family와 명시적 합성 조직을 하나씩 준비하고, 각 family는 날짜가 다른 회의2개와 일반 문서1개로 구성한다. 전체12문서의 출처·이용조건·크기·의미적 적합성·Java/Python 처리 일치·독립 검토와 동결 커밋을 마친 뒤 질문을 만든다.

크기 조건을 맞추려고 문서를 자르거나 요약·재분할·제목 축약하지 않는다. 원본 prospective manifest와 모든 raw identity를 먼저 보존하고 고정 `admit_sources` 경로로 검사한다. 채택된 원문과 metadata는 그 원본에 정확히 연결하며 채택·검토 annotation만 허용된 범위에서 바뀔 수 있다. 거부된 원본과 실패 영수증을 덮어쓰지 않는다. 바이트 규칙을 통과해도 의미 난도를 만족하지 않으면 채택하지 않는다.

## 과거 자료와의 분리

[과거 출처 목록](../data/evaluation/meetings-c7-prior-source-fingerprints-v1.json)은 metadata3개에서110행을 보존한다. 이전98행에 닫힌 C6의12행을 추가했고, canonical107행·중복 원본3행·정규화 fingerprint42행·제외 repository13개다. 과거 coverage 누락3항목은 그대로 남긴다. 닫힌 원문·질문·oracle을 열어 fingerprint를 보충하지 않았으며 완전한 의미 중복 부재의 증거로 해석하지 않는다.

공개 repo는 본문 읽기 전에 split별 예약을 조율한다. 과거 repo와 동일 repo의 교차 split 충돌을 피하고, 선정 후에는 독립 검토자가 새 자료의 의미적 신선도와 반복 문단을 확인한다. Validation 검토자가 새 calibration 원문을 비교할 필요가 있을 때에는 원문 확정 후 별도 지시로만 허용한다. Calibration 질문·oracle은 열지 않는다.

## 실제 역할과 아직 수행하지 않은 일

| Split | 작성자: source와 후속 item | 독립 검토자: source와 후속 item |
| --- | --- | --- |
| calibration | /root/c7_calibration_author | /root/c7_calibration_prereviewer |
| validation | /root/c7_validation_author | /root/c7_validation_prereviewer |

네 역할 모두 새 GPT-6 Astra xhigh/fork none을 도구가 실제 수락했다. 같은 split에서 source→item 역할을 재사용한다는 점과 자동 AGENTS·memory의 과거 집계 노출을 [등록 기록](../data/evaluation/meetings-c7-role-registration-v1.json)에 남긴다. Pristine/blind 상태나 런타임 introspection을 주장하지 않는다. 작성자는 자기 자료를 검토하지 않으며, 네 역할 모두 최종 답변 판정에서 제외한다.

역할 수락은 자료 준비 완료가 아니다. 등록과 prior index를 커밋한 뒤 작성자에게 별도 지시한다. 작성자는 현재 HEAD·동결 코드·CI·역할을 실제 Git proof로 확인한 뒤에만 원문 검색과 작성에 착수한다. 이 증명 중에는 부모가 HEAD를 유지한다. Java 검사는 한 담당자씩 실행한다.

부모는 원문·문항 의미 대신 status/count/hash를 확인한다. 사용자 검수는0이며 실제 품질·추론 시간·서비스 채택은 다음 단계에서 별도로 검증한다.
