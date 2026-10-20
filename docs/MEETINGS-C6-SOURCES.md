# C6 새 원문 준비

2026-10-20. 도구 source d3e4e2e 양쪽 필수 CI와 별도 CI 영수증1d9227b의 양쪽 필수 CI를 확인했다. 아직 실제 원문·문항·tokenizer·모델 실행은0이다.

## 목적과 방법

회의와 일반 문서를 함께 읽는 답변을 검증한다. 질문에 맞춰 근거를 만들지 않도록 split마다 공개 family와 명시적 합성 조직을 하나씩 선정하고 각각 날짜가 다른 회의2개와 일반 문서1개를 먼저 확정한다. 전체12문서의 출처·이용조건·고정 revision·Java/Python 처리 일치·독립 검토 뒤 질문을 작성한다. 토큰 계수나 모델 출력으로 원문을 바꾸지 않는다.

과거 출처 index659fef38은 metadata4개·98행(canonical95)·정규화 hash30행·누락3항목·제외repo11개다. 거부된 C5 validation v1과 채택v2를 모두 보존했고 동일 공개3행도 남겼다. 과거68행에는 정규화 hash가 없어 완전한 중복 부재를 증명하지 못한다. 과거 본문은 재개방하지 않는다.

## 실제 역할과 경계

| Split | 작성(source, 이후 item) | 별도 사전검토(source, 이후 item) |
| --- | --- | --- |
| calibration | /root/c6_calibration_author | /root/c6_calibration_prereviewer |
| validation | /root/c6_validation_author | /root/c6_validation_prereviewer |

모두 새 fork none, GPT-6 Astra xhigh를 도구가 수락했다. [역할 등록](../data/evaluation/meetings-c6-role-registration-v1.json)에 실제 수락시각·영수증·노출·허용 경로를 남겼다. 같은 split 역할 재사용을 공개하며 자기검토·split 간 겸임·최종 답변 judging을 금지한다. 부모는 원문/질문/oracle 의미를 열지 않는다. Validation 검토자의 이후 명시적 source 신선도 비교만 finalized C6 calibration SOURCE를 허용하며 문항/oracle은 금지한다.

## 순서와 확인

역할/index 커밋 뒤 각 작성자가 실제 code_contract/GitProof/role 계약을 검증한다. 부모는 이 동안 HEAD를 유지한다. 공개 repo를 본문 전에 예약하고 출처·이용조건을 확인한다. Java parity는 한 명씩 실행한다. 독립 source 검토·동결·커밋 후 item 작성·독립 검토·동결·공식 offline 준비1회·조건부 native 평가로 이어간다. 닫힌 실험과 원본 실패는 재실행/수정하지 않는다.

AI 작성·AI 독립 검토와 사용자 직접 검수는 다르다. 이번 등록은 모델 답변 품질을 입증하지 않으며 Phase1과 PR14는 미완료/draft다. 실제 준비·실패·수용 결과는 이후 절에 추가한다.
