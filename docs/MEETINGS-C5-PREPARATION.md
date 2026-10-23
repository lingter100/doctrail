# C5 공식 입력 준비와 실행 경계

2026-10-20. 독립 수용 문항14개와 item freeze를 먼저 `cefbfeebf4cfecf0226fb8c7f9a7eac98fbe6d7d`로 커밋했다. 기존 두 split 담당자가 실제 committed code/source/item 전체 증명을 거친 뒤 공식 offline 준비를 각각 한 번 실행했다. 두 단계의 증거를 분리하며 모델 생성은 아직0이다.

| 구분 | Calibration | 격리 validation |
| --- | ---: | ---: |
| 공식 입력 수 | 6 | 8 |
| 입력 토큰 최소 | 1570 | 2575 |
| 입력 토큰 최대 | 5021 | 4999 |
| Tokenizer load | 1 | 1 |
| Native/model/download | 0 | 0 |

모두 상한5,120 이내이며 원래 질문/payload/전체 청크를 그대로 유지했다. 공식 출력 `.local/meetings-c5-{phase}-prepared-v1/`는 실패도 소비하는 단발 예약이므로 다시 실행하지 않는다. 원본의 정확한 공개 복사본4개는 `data/evaluation/meetings-c5-{phase}-inputs-v1/`에 보존했다. 부모는 의미 본문을 열지 않고 hash·계수·영수증만 확인했다.

두 CLI는 종료0·passed summary·원본 영수증이 일치했고 소유 프로세스0을 확인했다. Offline CLI 시간은 calibration92.219초/validation75.203초이며 서비스 요청 시간으로 해석하지 않는다. Item commit의 push39348557481/PR39348561878 필수3job 모두 성공을 직접 확인했다.

공식 CLI는 `uv run --group retrieval --no-sync python -m scripts.prepare_meeting_c5_inputs --phase calibration|validation`이며 각 `--draft`, `--oracle`, `--source-freeze`, `--item-freeze`와 대응 `--*-sha256`은 receipt의 references를 사용한다. 이번 등록은 이미 소비됐으므로 재현 검토에서는 저장된 결과와 hash를 대조한다. 캐시 tokenizer만 사용하고 다운로드·입력 재선택·자르기·재계수는 하지 않았다.

새 실행계획 `data/evaluation/meetings-c5-execution-plan-v1.json`은 입력/영수증/원문/item, 동결76개, 사전등록된 별도 판정자2명과 제외역할14개를 연결한다. 계획 경로 검사를 통과했으며 실제 Git을 쓰는 실행 check는 계획 커밋 뒤 한다. 이후 calibration을 최대6회 실제 생성하고 독립 최종 판정6/6과 운영 무결성이 모두 통과한 경우에만 validation8회를 연다. 요청90초·출력928·최종JSON384·GPU28·재시도0은 고정한다.

판정자에게 매핑이나 reasoning을 공개하기 전에 모든 judgment hash를 잠근다. 자료 준비 통과나 CI는 모델 정확도·검색 품질·Java 전체 지연·사용자 만족을 입증하지 않는다. 사용자 검수0·서비스 미채택·Phase1 미완료이며 무료/로컬 원칙을 유지한다. [실측 영수증](../experiments/results/meetings-c5-preparation-v1.json), [문항 검토](MEETINGS-C5-ITEMS.md), [고정 계획](MEETINGS-C5-PLAN.md)을 참고한다.
