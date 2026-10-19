# C5 새 원문 준비와 역할 기록

2026-10-19. 검증 도구 소스 d084f86의 양쪽 필수 CI가 성공했고 CI 영수증은 ddc5080에 커밋했다. 이 문서는 새 자료 작성 전 역할과 순서를 기록한다. 현재 실제 원문·문항·tokenizer·모델 실행은0이다.

## 목적과 방법

회의와 일반 문서를 연결하는 답변을 검증하려면 질문에 맞춰 근거를 만든 자료를 피해야 한다. 각 split마다 새 공개 family와 명시적 합성 조직을 하나씩 정하고, 각각 날짜가 다른 회의2개와 일반 문서1개를 먼저 확정한다. 전체12문서의 출처·이용 조건·revision·문서 처리 일치·독립 검토를 마친 뒤 질문을 작성한다. 토큰 계수나 모델 출력으로 원문을 조정하지 않는다.

공개 저장소는 본문을 열기 전에 서로 다른 repo를 예약한다. 과거 metadata index의 제외 repo9개도 사용하지 않는다. 이전 raw/normalized/긴 문단 hash를 비교하지만 과거68행에는 정규화 hash가 없으므로 완전 중복 검증이라고 주장하지 않는다. 누락3항목은 index에 그대로 남긴다.

## 실제 역할

| Split | 작성(source, 이후 item) | 별도 사전검토(source, 이후 item) |
| --- | --- | --- |
| calibration | /root/c5_calibration_author | /root/c5_calibration_prereviewer |
| validation | /root/c5_validation_author | /root/c5_validation_prereviewer |

모두 실제 도구가 수락한 GPT-6 Astra xhigh, fork none이다. 부모 채팅 설정을 변경한 것은 아니다. [역할 등록](../data/evaluation/meetings-c5-role-registration-v1.json)에 수락 시각·허용 경로·노출과 시작 조건을 기록한다. 같은 split 역할 재사용은 공개하며 자기검토·split 간 겸임·최종 답변 판정을 금지한다. 부모는 validation 본문·oracle·의미 검토를 열지 않는다.

## 실행 순서와 소유권

역할/index 커밋 뒤 작성자가 실제 Git 기반 code_contract와 원래76개 동결을 확인한다. 부모는 이 확인 동안 HEAD를 유지한다. 공개 repo 예약 후 출처와 이용 조건을 확인하고 각자 원문6개·처리 inventory·처리 영수증·phase fingerprint metadata를 만든다. Java 검증은 Maven/포트 경합을 피하도록 순서를 조정한다.

원문 작성자는 자신의 사전검토나 source freeze를 만들지 않는다. 별도 검토자가 전체 원문·출처·일관성·신선도·Java/Python parity를 확인한 다음 수용한 자료만 동결한다. 원문 커밋 뒤 item 작성, 독립 item 검토와 동결, 공식 offline 준비1회, 실제 quality 실행 순서를 따른다. 이전 실험을 재실행하지 않는다.

## 설명할 핵심과 남은 한계

소프트웨어 검사 통과는 모델의 답변 정확성과 다르다. 이번 단계는 새 평가 자료를 신뢰할 수 있게 준비하는 과정이다. 공개 문서와 합성 문서는 구분하고 AI 작성/검토와 사용자 직접 검수도 분리한다. 실제 질문 난도·근거 충분성·답변 품질·운영 적합성은 아직 미확정이다. Phase1과 PR14는 draft를 유지한다.
