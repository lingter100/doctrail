# C5 품질 실행: 두 번째 요청 시간 초과

2026-10-20. 실행 커밋 `2f327d3179ad443773b2b1834aa9e00fee9c5e1f`, 계획 SHA `5450de67255b151519b9443306f43466a65b8269dae3c2264da8eca38341df1a`. 해당 push39349148144/PR39349154882의 필수 backend/java-service/web 모두 성공했다. 실제 모델 실행은 아래와 같이 실패했으며 두 결과를 구분한다.

## 결과

두 번째 calibration 요청에서 `generation_deadline_exceeded`로 종료했다. 전송 시도2·파싱된 응답1·구조 수용1이고 의미 판정0이다. 나머지 calibration4/validation8은 실행하지 않았으며 선택 자격false, 서비스 미채택이다. C5나 미실행 문항을 다시 실행하지 않는다.

| 실제 관측 | 첫 요청 | 두 번째 요청 |
| --- | ---: | ---: |
| 입력 토큰 | 2776 | 5021 |
| 전체 출력 토큰 | 872 | 미관측 |
| 최종 JSON 재계수 | 357 | 미관측 |
| 전체 요청 | 89.859초 | 90.953초 |
| 최초 자료 검증 | 19.687초 | 23.094초 |
| native prompt | 4.924507초 | 미관측 |
| native prediction | 46.470570초 | 미관측 |
| 종료 | EOS·구조 수용 | deadline 오류 |

CLI는 exit1/failed_closed,293.234초였으며 phase는232.687초다. CLI의 실행 전 검증과 phase를 같은 구간으로 세지 않는다. 둘째90.953초는 제한 이후 오류 처리까지 포함한 관측값이며 제한 내 성공이 아니다. 생성이 얼마나 진행됐는지 추측하지 않는다. Owned process0·native drain0bytes/EOF·정리 오류0을 확인했고 HEAD는 같았다. 추가 retry/warmup/resource/restart는0이다.

## 해석과 다음 개선

첫 요청의 native 합계51.395077초와 전체89.859초의 차이는38.463923초다. 최초 검증19.687초는 직접 기록된 값이지만 나머지를 전부 Git이나 디스크 비용이라고 단정할 수 없다. 전송 직전 재검증, HTTP/template/tokenize, 응답 검증과 저장도 포함된다. 남은 시간 여유는0.141초여서 첫 구조 통과가 안정적인 운영을 뜻하지 않는다.

이전 C4와 문항·입력·출력이 다르므로 native 시간이 짧아졌다는 관측으로 GPU28의 인과 개선률을 만들지 않는다. 요청된 GPU layers는28이고 실제 offload/Flash Attention은unknown이다. 기존 합성 host profile의 warm2.933초도 이번 실제 최초 검증19.687/23.094초와 같은 작업이 아니다.

다음 선택은 별도 실제 Astra xhigh 역할이 frozen code·허용 scalar metadata만 읽어 검토한다. 닫힌 본문이나 실패 출력을 이용해 질문을 바꾸지 않는다. 원래 일반 문서·복수 회의·혼합 문서·KO/EN·보류와 근거 요구를 유지하며, 검증 비용을 줄이더라도 HEAD/바이트/경로/새 import 후보/전송 직전 상태 확인을 우회하지 않는다. 아직 새 후보 설계나 추가 모델 실행을 완료했다고 기록하지 않는다.

## 원본 보존과 모델 없는 재생

- [원본 보고서](../experiments/results/meetings-c5-quality-calibration-v1/report.json), SHA `5d2da15ac9a9c9bb6f0abb96518e470ea683594e0947814dcacb95f0d63b1edd`.
- [실패 metadata](../experiments/results/meetings-c5-quality-failure-metadata-v1.json), SHA `21fcf3da665c82d9d3fc4a8b1d9727389046ee891f1b708b2cc159f3e15650b4`.
- [별도 구조 재생](../experiments/results/meetings-c5-quality-failure-replay-v1.json), SHA `97bd85ddd4c515673381afe4aedc66a9bb7ad762d2f000e192dfc7cc129f025c`: 실제 Git material·108 snapshot·첫 응답의 동결 trace·불변27 event가 통과했다. 전체 report는 `c5_report_not_complete`로 거부됐고 validation은 원래 selection 부재로 본문 접근 전에 거부됐다.
- [정확한 공개 복사 영수증](../experiments/results/meetings-c5-quality-failure-publication-v1.json), SHA `f496e66313bfc28107160494054c211f6d083957e5956b9cf8aac59b33dd8b6a`: report/ledger/trace29개, 총1023971bytes가 로컬 원본과 동일하다. 라이선스가 확인된 공개 자료와 명시적인 합성 calibration만 포함한다. Validation 의미 내용, launcher 설정·credentials·모델 파일은 복사하지 않았다. 제한된 절대 경로/credential 패턴 검사는0건이며 모든 가능한 민감 값 부재를 보장하지는 않는다.

원본 `sources_unchanged:false`, `metadata_recovery:false`, `restarts:0`은 성공 후 경로를 완료하지 못한 상태로 그대로 남겼다. 별도 사후 검사가 통과했다고 원본을 수정하지 않는다. 재생은 다른 checkout에서2f327d3의 도구/계획과 공개 영수증의 원래 상대경로로 report/ledger/trace만 복원해 확인한다. 기존 결과를 덮거나 `run`·tokenizer 준비를 다시 호출하지 않는다. `probe_meeting_c5_quality.check('calibration')`와 첫 `trace_replay`는 모델 없이 확인할 수 있고 전체 `report_replay`는 위 거부가 기대 결과다.

## 포트폴리오에 설명할 내용

문항14개가 독립 AI 검토와 입력 계수를 통과하고 CI가 성공해도 실제 품질 비교는 시간 제한 때문에 끝나지 못했다. 인용/형식이 맞는 응답1개로 정확도 수치를 만들 수 없다. 운영 지연과 의미 품질을 모두 만족해야 서비스에 연결한다는 원칙을 실제 실패와 함께 설명한다. 사용자 검수0이며 Phase1/PR14는 미완료/draft, 전체 goal은ACTIVE다.
