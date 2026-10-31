# 충분한 참고 답변을 먼저 정한 표현 길이 진단

2026-10-31. 새로운 공개 개발 사례2개와 토큰 측정기를 준비했다. [구현 검사·독립 코드 검토](../experiments/results/meetings-free-qa-representation-implementation-v1.json)를 마쳤다. 모델 평가 결과가 아니며 토큰 측정도 아직 실행하지 않았다. 닫힌 기존6문항 비교와 격리 validation·최종 test는 사용하지 않는다.

## 자료와 질문

OpenSearch 기술 운영 저장소의 고정 커밋 `eef3b36e5cd9a7bd1500e4f4f3510856a88d4fde`에서 다음 원문을 사용한다.

- [2025년6월 회의](https://github.com/opensearch-project/technical-steering/blob/eef3b36e5cd9a7bd1500e4f4f3510856a88d4fde/meeting-minutes/2025/2025-06-11-minutes.md)
- [2025년11월 제목의 회의](https://github.com/opensearch-project/technical-steering/blob/eef3b36e5cd9a7bd1500e4f4f3510856a88d4fde/meeting-minutes/2025/2025-11-12-minutes.md)
- [기술 자문 그룹 운영 규칙](https://github.com/opensearch-project/technical-steering/blob/eef3b36e5cd9a7bd1500e4f4f3510856a88d4fde/technical-advisory-groups/README.md)

원문3개10,795바이트, 출처·라이선스·이전 명칭 확인용 자료까지6개24,194바이트를 보존했다. 해당 판본의 [Apache-2.0 LICENSE](https://github.com/opensearch-project/technical-steering/blob/eef3b36e5cd9a7bd1500e4f4f3510856a88d4fde/LICENSE)와 [NOTICE](https://github.com/opensearch-project/technical-steering/blob/eef3b36e5cd9a7bd1500e4f4f3510856a88d4fde/NOTICE)를 함께 기록했다. 현재 main의 NOTICE로 바꾸지 않았다.

질문은 ①6월부터11월까지 Search 그룹 추진 경과와 정식 출범에 필요한 운영 절차 ②해당 자료에서 확정된 담당 범위와 초기 구성원이다. 첫 참고 답변은 원문에 근거한 세 주장, 둘째는 확정 결과가 없어 전체 보류다. 원문 전체를133개 근거 단위로 연결했다. 질문과 참고 답변은 AI 작성이며, 별도 Astra xhigh가 원문 전체·주장·보류·좌표를 검토해 개발용 진단으로 수용했다. 사용자 검수는0이다.

SIG/TAG 명칭은 각 시점 그대로 두었다. 11월 파일의 제목과 내부10월 표기 불일치도 원본에 남기고 정확한 회의일로 확대 해석하지 않았다. 이 자료에는 엄격한 미해결 충돌 질문이 없다.

## 이 진단이 확인하는 것

원문과 적합한 참고 답변을 먼저 고정한 뒤, 현재 기준 모델의 실제 입력·응답 표현이 설정 한도에 들어가는지 측정한다. 한도를 넘기려고 요구사항을 늘리거나 한도에 맞추려고 사실을 빼지 않는다. 검색을 생략하고 원문3개를 직접 제공하므로 검색 품질 측정이 아니다.

기준 모델은 기존 Ministral3-3B Q5_K_M, 실행기는 고정 llama.cpp b11429다. 서버의 실제 템플릿 처리와 compact 입력을 사용한다. 모델을 한 번 로딩하지만 답변 생성 없이 속성 조회1회·템플릿 처리2회·토큰화4회만 수행하는 실행기를 구현했다. 입력4096토큰과 참고 응답 JSON256토큰을 각각 비교하고 종료 토큰1개 가정은 별도로 표시한다.

고유 가상 검사30개를 여러 실행에 걸쳐 확인했으며 단일 전체30개 통과 실행으로 합치지 않는다. 별도 코드 검토에서 원래 실패가 보호 절차의 오류로 덮일 수 있음을 발견했고, 최초 오류와 종료 오류를 따로 보존하도록 수정했다. 수정 전 실패와 이후 관련6개 통과를 보존했다. 현재 공개 소스는 이 로컬 진단의 고정 자료·검토 파일을 참조하므로, 아직 누구나 복제할 수 있는 공개 입력 묶음은 아니다. 원문 이용 조건을 포함한 재현 묶음은 별도 정리한다.

참고 답변 토큰 수는 모델이 그 답변을 생성한다는 증거가 아니다. 모든 적합한 다른 표현의 길이를 대표하거나 실제 생성 토큰 분할·비용·시간과 같다고 볼 수도 없다. 기록된 출처·해시에서 중복이 없음을 확인했지만 모든 과거 자료·번역·의미 중복과의 완전한 독립성을 주장하지 않는다. 사람 평가·모델 품질 수용·기본 서비스 채택은 별도 단계다.
