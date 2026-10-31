# C4 품질 실행: 두 번째 요청 시간 초과로 종료

2026-10-16. 실행 커밋 `43139e09f6a0aecfdde1c0c510a563efd348e8d5`, 실행계획 SHA `ca2c21eb5e039dc230193513d990a23545659147173d1bbe065995edcaa5034d`. 해당 커밋의 push38858681852와 PR38858688059는 필수 backend/java-service/web 작업이 모두 성공했다. 이 CI 상태는 모델 품질 성공을 뜻하지 않는다.

## 결과와 중단 범위

Calibration 두 번째 요청에서 `generation_deadline_exceeded`가 발생해 사전등록대로 종료했다. 요청 전송 시도2회, 파싱된 native 응답1개, 계약에 맞는 답변1개다. 두 번의 생성이 완료됐다는 뜻이 아니다. 나머지 calibration4개와 validation8개는 실행하지 않았다. 의미 판정·사용자 검수0, 선택 자격false이며 서비스에 채택하지 않는다. C4 및 미실행 문항을 재실행하거나 새 이름으로 이어서 실행하지 않는다.

| 관측 | 첫 요청 | 두 번째 요청 |
|---|---:|---:|
| 등록 입력 토큰 | 1,255 | 2,647 |
| 출력 토큰 | 812 | 관측 없음 |
| 최종 JSON 재계수 | 297 | 관측 없음 |
| 종료 | EOS, 구조 수용 | deadline 오류 |
| 전체 요청 시간 | 86.157초 | 91.343초 |
| native prompt 시간 | 3.999651초 | 관측 없음 |
| native prediction 시간 | 63.402728초 | 관측 없음 |

전체 phase261.64초. 두 번째 요청의91.343초는90초 watchdog 이후 오류 처리·대기까지 포함한 관측값이며 제한 내 성공이 아니다. 출력/생성 진행 정도를 추측하지 않는다. 종료 때 owned process stopped/within-budget, cleanup errors0, emitted bytes0, EOFtrue, drain read/join errors0을 확인했다. 추가 retry/warmup/resource 실행/restart는0이다.

원본의 `sources_unchanged:false`, `metadata_recovery:false`, `restarts:0`은 성공 후 검증·복구 경로를 완료하지 못한 실제 상태다. 후속 별도 검사에서 파일이 같았다고 원본 flag를 true로 바꾸지 않았다.

## 원인에 대해 확인한 범위

첫 요청에서 native prompt+prediction은67.402379초, 전체 요청과의 차이는18.754621초,90초까지 여유는3.843초다. 이 차이는 Git 비용 측정값이 아니다. HTTP, template/tokenize, native 미계측 작업, 파일·경로 검증, 응답 검사·기록 등이 포함될 수 있다. 두 번째 요청에 native timing이 없으므로 host 검증을 줄이면 성공했을지도 알 수 없다. Java 서비스 응답 시간이나 사용자 지연 지표로 사용하지 않는다.

독립 코드 검토는 요청 전 검증과 전송 직전 콜백의 전체 검증 중복을 조사 후보로 찾았다. GitProof는 이미 Git blob 결과를 캐시하므로 매번85개의 `git show`가 반복된다고 설명하지 않는다. AST import 탐색은 파일 내용뿐 아니라 후보 경로 존재에도 의존한다. 기존85파일 hash만 캐시하면 새 shadow module이 생긴 것을 놓칠 수 있다.

다음은 별도 사전등록한 **모델 없는 host 검증 프로파일링**이다. 고정 합성 metadata와 허용 코드만 사용해 구간별 시간·호출 수·bytes를 측정한다. 실제 C4 입력·원문·trace를 재사용하지 않고 native/tokenizer/HTTP0을 유지한다. 실제 측정 뒤에만 최적화 대상을 정하며 HEAD·파일 바이트·경로·전송 직전 검증을 우회하지 않는다. 일반 문서·복수 회의·KO/EN·완전한 자연어 답변과 근거·보류 요구는 그대로다.

## 증거와 모델 없는 재생

- [실패 metadata](../experiments/results/meetings-c4-quality-failure-metadata-v1.json), SHA `2bf0362f6d34fccd8458867e1e050c37190483452cafa3b43b38296e30552c8a`: 전송 수·시간·정리·134개 별도 binding 확인. 질문·근거·답변·reasoning 본문을 출력하지 않았다.
- [별도 구조 재생](../experiments/results/meetings-c4-quality-failure-replay-v1.json), SHA `2d03948516a3b5e15aa335b4bb10e1c6ed410be7882e422531feb83dccfdd33b`: 실제 Git material, 첫 응답의 동결 trace replay,27event의 참조/hash/value 및 추가 파일 부재 확인. 첫 응답17event, 실패 요청10event다.
- 전체 `report_replay`는 `c4_report_not_complete`로 거부됐고, validation check는 원래 calibration selection 부재로 의미 metadata/body 전에 거부됐다.115개 snapshot도 재확인했다. 이는 실패의 사후 구조 확인이며 품질 판정이 아니다.
- [원본 보고서](../experiments/results/meetings-c4-quality-calibration-v1/report.json), SHA `4c95b97cafb1abaf9655443023ffefdd1a436250d40b5cc3fff84fa0b8c87b91`: 로컬 원본352,062bytes와 동일하다. [공개 복사 영수증](../experiments/results/meetings-c4-quality-failure-publication-v1.json), SHA `da5b6f03bed247731c462df66e5701a8a7a1c3d6fe1a9b2982c832767758b8bc`에 report/ledger/trace29개567,780bytes의 경로/hash를 보존했다.

공개 원본은 이미 채택한 이용 조건이 확인된 공개 calibration 자료와 명시적 합성 자료를 포함한다. validation 의미 내용, launcher 설정, credentials, weights, corpus cache는 복사하지 않았다. 절대 환경 경로·credential 패턴 검사는0건이지만 임의의 모든 민감 값 부재를 증명하는 검사는 아니다. 최초 검사 regex가 URL 끝의 `s:/`도 Windows drive로 세어204건을 거부했으며 파일 복사 전이었다. drive 경계를 명시한 후0건을 확인해 최초 복사를 수행했다.

다른 사람이 확인할 때는 별도 checkout에서43139e0의 동결 도구와 계획을 사용하고, 공개 복사 영수증의 원본 상대경로로 **report/ledger/trace만** 복원한다. 기존 `.local` 결과를 덮어쓰지 않는다. `scripts.probe_meeting_thinking_quality.check('calibration')`, 첫 case의 `trace_replay`는 모델 없이 원본 구조를 확인한다. 전체 `report_replay`의 위 거부를 기대한다. 원래 `run`이나 tokenizer 준비를 다시 실행하는 절차가 아니다. 검토 역할별 validation 접근 제한은 계속 지킨다.

## 포트폴리오 해석

구조적으로 유효한 응답 하나가 있어도6/6 비교가 완료되지 않았고 의미 검토도 없으므로 답변 정확도 수치를 만들 수 없다. 요청 시간 예산 안에서 품질 평가 자체를 끝내는 능력도 후보 채택 조건이다. 실패 원본을 고정하고 검증 비용을 따로 측정한 뒤 새 실험을 설계하는 것이 다음 개선이다. 사용자에게 맡길 부분은 최종 실제 서비스 사용성과 답변 적합성 검수이며, 아직 수행한 것으로 기록하지 않는다. 전체 goal은 ACTIVE, Phase1과 PR14는 미완료/draft다.
