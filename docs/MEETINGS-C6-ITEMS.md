# C6 질문과 정답 근거 준비

2026-10-20. 이 문서는 새 문항 작성·독립 검토 단계의 실제 기록이다. [확정된 원문](MEETINGS-C6-SOURCES.md)과 [사전등록 설계](MEETINGS-C6-PLAN.md)를 따른다. 아직 모델 답변 품질 결과가 아니다.

## 해결할 문제와 비교 기준

회의록 하나를 요약하는 능력만으로 여러 회의와 일반 문서를 연결하는 답변을 보장할 수 없다. 같은 원문에 있는 모든 충분한 근거를 검토해 단일 문서, 복수 회의, 일반 문서와 회의의 결합, 근거 부재에 따른 보류를 구분한다. 인용 문자열이 정확한지와 답변 내용이 참이고 충분한지를 별도로 확인한다.

Calibration6은 한국어3/영어3, 답변4/보류2다. 격리 validation8은 한국어4/영어4, 답변4/보류4다. 각 split의 공개 family와 AI 합성 family를 분리하며 원문6개는 이미 독립 검토·동결·커밋됐다. 답변 문항마다 필수사실3~6개와 모든 충분한 근거 대안을 작성한다. 일반 문서만으로 답할 수 있는 문항, 복수 회의, 일반 문서+회의, 반드시2개 이상 문서가 필요한 문항과 양방향 교차언어 근거를 포함한다.

토큰 수를 보고 청크를 자르거나 질문에 맞춰 원문을 만드는 대안은 사용하지 않는다. 보류는 원문 family 전체에 필요한 정보가 없는지 검토하며 답이 있는 청크를 숨겨 만들지 않는다. 품질 판단은 소규모 사전등록 관문이고 일반 서비스 성능 추정치가 아니다.

## 실제 작성 시작과 한계

Source commit887e89f의 필수 CI 통과 뒤 문서 HEAD eae7140에서 작성자가 실제 검증을 새로 수행했다.

| Split | 코드/원문 bindings | Git revision/path 증명 | snapshot | 상태 |
| --- | --- | --- | --- | --- |
| calibration | 77/14 | 189 | 96 | 통과, NEW4 반환·독립 검토 중 |
| validation | 77/15 | 191 | 97 | 통과, NEW4 반환·독립 검토 배정 |

영수증은 로컬 `.local/meetings-c6-{calibration,validation}-item-v1/preauthorization-v1.json`이다. 각각 SHA063650d5·bde9ec03이며 실제 Git 실행을 사용했다. 부모는 hash·개수·역할·상태만 읽었다. Validation 작성자는 calibration 원문/질문/oracle 및 자기 source-freshness의 교차 비교 사유를 열지 않는다.

Validation 작성자는 proof 실행을 기다리는 동안 이전에 허용된 자기 source 대화 기억에서 질문 주제를 검토했다고 밝혔다. 증명 전 새 원문 열람이나 파일 작성은 없었으며 해당 한계는 원본 proof를 수정하지 않고 sequence note와 author receipt에 남긴다. Git 증명을 내부 사고 시각의 증명으로 해석하지 않는다. Calibration의 receipt 생성 전 너무 이른 hash 조회에서 not_found가 난 도구 타이밍 오류도 별도 보존했다.

## 역할과 다음 관문

작성자가 calibration6/필수사실29개, validation8/필수사실33개를 반환했다. 작성자 자체의 C6 schema/구성/전체 청크·좌표 검사는 통과했고 부모는 NEW8의 반환 hash와 LF 바이트를 확인했다. 별도 검토자가 실제 새 Git proof 뒤 의미 검토를 완료했다. Calibration5수용/1거부, validation7수용/1거부이며 양쪽 item freeze는 만들지 않았다.

양쪽 모두 원문과 제공 context에 있는 다른 충분한 근거 대안이 oracle의 한 필수사실에 빠져 있었다. 구조·좌표·배분 검사가 통과해도 근거의 완전성을 보장하지 못한 실제 사례다. 전체 원본8과 검토6을 보존하며 최초 묶음은 동결/토큰 준비하지 않는다. 원본·거부 기록을 커밋한 뒤 같은 split 작성자가 자기 제한 피드백으로 해당 대안만 NEW v2에 추가하고 같은 별도 검토자가 다시 판단한다. [새 경로 승인](../data/evaluation/meetings-c6-item-revision-authorization-v1.json)은 기존 역할 등록을 덮어쓰지 않는 사전 추가 기록이며, [첫 검토 결과](../experiments/results/meetings-c6-item-review-v1.json)에 hash와 한계를 남겼다. 양쪽 표시용 helper 오류1개씩은 데이터/제품 실패와 별도로 보존한다.

각 기존 작성자는 draft/oracle-draft/context-selection/author-receipt만 작성하고, 별도 기존 prereviewer가 문항 의미와 근거 완전성·독립 복수문서 조건을 검토한다. 부모는 질문/정답을 직접 읽지 않는다. 거부된 초안은 그대로 보존하고 제한된 피드백을 반영한 새 버전을 별도 검토한다.

최종 답변 judge는 새 `/root/c6_calibration_final_judge`와 `/root/c6_validation_final_judge`다. 실제 도구가 Astra xhigh/fork none을 수락했고 각64byte 공개 재현 seed와 노출 진술을 [등록 파일](../data/evaluation/meetings-c6-review-registration-v1.json)에 묶었다. 부모·설계·구현·source/item 작성/검토 역할은 제외한다. 자동 metadata 노출이 있으므로 완전 맹검이라고 하지 않는다. 현재 판정0이며 실제 출력 뒤 별도 지시로 익명 pack만 열고, 판정 hash를 잠근 뒤 mapping을 공개한다.

독립 item 수용/동결·커밋 뒤 각 split 공식 offline 준비를 한 번만 수행한다. 계수 실패를 payload 수정이나 재계수로 살리지 않는다. 실행 plan의 모든 입력/역할을 커밋한 뒤 calibration을 한 번 평가하며, 원래6개 완전정답과 운영 무결성 통과 시에만 validation8을 연다. 지금은 tokenizer/native/사용자 검수0, Phase1 미완료다.
