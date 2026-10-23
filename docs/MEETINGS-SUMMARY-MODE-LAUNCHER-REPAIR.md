# 요약 모드 진단의 소유 실행·종료 판정 보완

2026-10-23. [기존 계획](MEETINGS-SUMMARY-QUALITY-NEXT.md) 18,650B/SHA256 `fb32d66f4c2264edec160b908b83fa1050731c455099636b985793db40d0b329`에 대한 **실행 전 보완**이다. 부모가 수용한 독립 코드 검토 `391ad9b6152ddd6af81a18926c969a823afa3345f88421f21d1ca958732904af`의 SM-01~05와 상태 기록 SM-N1을 해결한다. 이 문서만 작성하며 부모 검토·수용·커밋 뒤 같은 구현자에게 별도 수정 배정한다. 실제 실행 승인은 아니다.

## 변경 경계와 보존

- 이후 수정 가능 파일은 새로 만든 [probe](../scripts/probe_meeting_summary_mode.py)와 [test](../tests/test_probe_meeting_summary_mode.py) **2개뿐**이다. 초기 probe36,268B/`a12f1bfdee6e24c36b5a8e180fab74ce88cf67cbd267de0a06a92dd678878171`, test29,532B/`5c2d3b6a0f09a2de3ed34c14570fd5a161a09eeec70813b2bbc218cb821db196`, 초기102개 합성 검사·Ruff·receipt·독립 review를 수정 전에 그대로 보존한다. 이전 실패 기록을 새 결과로 덮지 않는다.
- Frozen77에 속한 `serve_meeting_gpu_placement.py`(`083474393f80d0386edcb1cad6efe9ee644655671efa75b8cd921e76a9e23bf5`)와 `serve_meeting_thinking_compat.py`(`3a3dbe8302c1793b1b3766d7276f0408eba66cb48f81ecde10ba52e0e746c73e`) 및 다른 공유 파일은 byte-identical로 유지한다. 기존 계획도 수정하지 않는다.
- 유일한 실행 연결 변경은 기존 `start_llama` context 전체 호출을 **probe 내부의 작은 소유 실행 context**로 대체하는 것이다. 새 launcher 파일·범용 실행 계층은 만들지 않는다. 기존 안전한 command/profile·prepare·lease·readiness·cleanup primitive를 그대로 호출하고 아래 소유권 공백만 probe에서 닫는다.
- 모델·가중치·native revision·실제 argv·GPU28·환경 격리·A/B 순서·입력·원문·prompt·schema·최종 검토·평가 기준은 바꾸지 않는다. 512는 soft 요청, total1312/final 재계수768/input4096, 생성150초/arm180초/startup120초/active1500초/cleanup5초/whole1625초와 최대16completion을 유지한다. 자료·criteria·QA·분류·서비스120초·Java/React·권한도 기존 범위다.

## 생성 직후부터 소유권과 정리 보장

1. 기존 `command(..., 28)`·`normalized_argv(28)`로 argv를 만들고 등록된 값과 대조한다. manifest/profile·자산 검증과 `prepare(..., allow_download=False)`, 기존 순서의 GPU/worker/llama lease, loopback 포트·인증 토큰·offline 환경·숨김 창·pipe 설정·discard 정책을 유지한다. 기존 worker lease의 일시 확인/나머지 lease 보유 방식도 조용히 바꾸지 않는다.
2. **Popen 호출 전에** process/drain 초기값과 최소 정리를 보장할 `try/finally` 범위를 세운다. Popen이 반환한 즉시 그 원래 객체와 PID를 소유 기록으로 붙잡는다. drain 생성·thread 설정·create_time 조회·readiness·observer·증거 저장보다 먼저 정리 의무가 유효해야 한다. 나중의 callback 등록만으로 앞 구간이 보호된다고 보지 않는다.
3. 반환받은 **원래 Popen 객체/Windows 프로세스 handle**이 초기 정리의 소유 근거다. create_time을 바로 관측해 이후 자원 감시의 PID/create_time 검사에 결속하되, 그 관측 실패도 원래 객체에 대한 정리 의무를 없애지 않는다. PID만으로 새 객체를 찾아 종료하거나 전역 subprocess/launcher monkeypatch, 프로세스 검색·범위 종료는 금지한다. 소유 handle을 증명할 수 없는 상태는 실패·부재 미확인으로 남기며 다른 프로세스를 종료하지 않는다.
4. 정상 drain이 있으면 기존 `cleanup_owned`를 재사용한다. drain 생성 전 실패에는 probe 내부의 **최소 no-drain 정리 분기**만 둔다: 원래 process의 terminate→필요 시 kill/wait와 열린 소유 pipe 정리다. 이것은 모델 재시도가 아니며 새 프로세스·조회·profile 호출을 만들지 않는다. 생성되지 않거나 시작되지 않은 drain을 joined=true로 꾸미지 않고 `absent/not_started`와 실제 pipe 닫힘을 구분한다.
5. 모든 정리 분기는 하나의 최초 cleanup 시작시각·공유5초 잔여 한도·누적 측정을 사용한다. 분기 전환이나 context 재진입으로5초를 다시 받지 않는다. 중복 정리는 이미 끝난 소유 자원 확인에 그치고, 정리 실패를 추가5초 시도로 구제하지 않는다. 종료·wait·drain/pipe 정리가 끝난 뒤 실제 소요·소유 process 부재·남은 thread/handle·오류를 기록한다. 원래 startup 실패와 cleanup 실패를 각각 보존하고 lease는 해당 정리 의무보다 먼저 풀지 않는다.
6. Popen 전/중 실패, Popen 성공 뒤 drain 생성·시작 실패, readiness·create_time/guard·adapter load 실패, 정상 실행·중간 실패 모두 같은 소유 경계로 닫힌다. `process_started=false` 하나로 정리를 생략하지 않는다. creation_attempted/returned/owned/absence_confirmed를 분리하며 부재 증거가 없으면 미확인으로 남긴다. Native 시작을 포함해 once가 소비된 실패를 자동 재개하지 않는다.

## 결과와 시간 기록의 의미

- **SM-01:** `first_failure`는 첫 의미상 거부까지 포함하는 역사 기록이다. 운영 판정은 별도로, 예정된8arm 완료·운영 오류 없음·동일 바인딩·모든 시간/자원/정리/terminal 검사 통과를 요구한다. A의 정상 semantic final-review rejection 뒤 나머지 arm이 정상 완료되면 그 A는 실패·비수용으로 유지하면서 진단의 운영 완료는 가능하다. rejected arm을 accepted로 바꾸거나 지우지 않는다.
- **SM-02:** 첫 실패는 write-once로 유지한다. 뒤의 generation abstained·transport·cleanup 오류는 각각 정지 원인/첫 운영 오류/후속 오류로 추가한다. 정상 abstained는 schema 오류가 아닌 semantic 비수용이며 이번 계약의 전체 중단이다. claims가 없어 review0인 이유와 남은 arm 미실행을 명시한다. 앞선 review rejection→다음 arm abstention에서도 최초 실패를 덮지 않는다.
- 운영 eligible/CLI 성공은 진단 운용의 완료만 뜻한다. `model_review_accepted`와 독립 품질 수용을 구분한다. B4/4 전체 주장 지원·핵심 충분·읽기 쉬움·실제 review/운영 수용, A 대비 완전 요약 회복≥1·퇴보0이라는 기존 기준은 그대로며, 이후 눈가림 독립 평가 전에는 후보 채택을 주장하지 않는다. B의 semantic rejection도 관측 가능하지만 품질 후보로는 비수용이다.
- **SM-N1:** 단계는 `not_started/attempted_failed/returned` 등으로 구분하고 요청 함수 진입, HTTP transport에 실제 넘긴 시도, 응답 수신, 검증된 완료를 따로 기록한다. 요청 evidence 쓰기나 최종 admission에서 실패한 것을 실제 dispatch로 세지 않는다. 클라이언트 dispatch 역시 서버의 실제 처리 증명은 아니므로 응답/trace와 구분한다. 최대16 한도는 보수적으로 적용하고 실패 뒤 새 completion은0이다.
- **SM-03:** arm body뿐 아니라 guard의 마지막 자원 확인·sampler 종료/join·증거 처리 뒤에 동일한 원래180초 deadline을 다시 검사한다. 초과 arm의 elapsed/resources와 실패 원인을 보존하고 다음 arm으로 넘어가지 않는다. 생성150초와 전체 active deadline도 재시작하지 않는다. 마지막 arm에도 같은 사후 검사를 적용한다.
- **SM-04:** cleanup·posthash·final-report/index/seal 쓰기를 모두 마친 뒤 **하나의 최종 clock 관측**에서 whole/active 기간과 운영 판정을 함께 산출한다. 그보다 이전 시간으로 합격을 정하고 나중 시간을 영수증에 넣지 않는다. active에서 제외할 cleanup은 실제로 측정된 해당 구간뿐이고 whole에는 모두 포함한다. Startup 실패처럼 active가 시작되지 않은 경우는 명시적 null이다.
- Seal 전 저장본은 terminal receipt가 필요한 잠정 기록이다. 최종 관측이 한도를 넘으면 append-only invalidation을 남기고 첫 원인은 유지한다. 그 추가 저장 뒤 다시 기간을 관측하되 판정은 계속 실패다. CLI는 검증에 사용한 같은 최종 관측·등록 hash·상태를 반환하며, 이후 시간을 새로 보고한다면 그 값도 다시 검사한다. 자신의 미래 출력 완료까지 자가 측정했다고 주장하지 않는다. 외부 custody는 terminal 발행/프로세스 종료 관측과 영수증의 일치·기한을 확인하며, terminal 부재나 모순은 비수용이다. 별도 실제 wrapper/once 바인딩 전에는 이 외부 증명이 완료됐다고 보지 않는다.

## 등록·합성 반례·다음 배정

- 사전 등록은 **원래 계획의 정확한 file/hash/bytes와 이 보완 문서의 정확한 file/hash/bytes를 둘 다 필수 참조**로 묶는다. 어느 한쪽을 대체하지 않는다. 수정된 probe/test와 기존 전체 코드·cached 자산·manifest·runtime argv·새 자료/동결 receipt/source-only lock·고정 순서도 기존 방식으로 묶고 실행 전후 검증한다. 보완 참조 누락·다른 hash·기존 계획 변조를 거부한다. 실제 입력/criteria의 수용 판단은 별도 담당자와 부모가 맡는다.
- 수정 전102개와 원본 증거를 보존하고, fake process/HTTP/clock만으로 각 반례를 먼저 남긴 뒤 수정한다: A 거부/B 수용의8arm 운영 완료, 앞선 거부 뒤 abstention, guard exit에서180초 초과, seal 뒤 관측 사이1500/1625초 초과, dispatch 전 evidence 실패와 전송 후 응답 실패, 모든 startup/소유/정리 경계, 공유5초 및 최초 원인 보존, 정상/실패 terminal의 바인딩·판정 일치다. 모든 startup 예외에서 소유 handle 정리·잔여 completion0·남은 arm 미실행을 확인한다.
- 정상 launcher의 argv/환경/profile/lease 순서·download=false·단일 소유권을 기존 값과 직접 대조하고 no-drain/미시작 drain/정상 drain을 각각 검사한다. 등록의 원계획+보완 필수 참조와 잘못된 참조 거부도 합성 검사한다. 기존 A/B 동일성·cap/EOS·전체 원문/gap/title·반복 좌표·필수 review 검사와 오래된 계약 검사를 축소하지 않는다.
- 부모가 이 문서를 읽고 수용·커밋한 뒤 같은 구현자가 probe/test2만 수정한다. 수정 반환→독립 코드 읽기→정확한 source CI→부모 등록/새 자료 수용·독립 source-only 기준 잠금→명시적 once 배정 순서를 지킨다. 초기102/review1과 새 실패/수정 증거는 별개로 남긴다. 합성 통과는 실제 native 호환·자원·의미 품질 증명이 아니며 기존 자료 재실행/튜닝은0이다.

이번 보완의 코드 수정·테스트·모델/tokenizer·native·Java/browser·다운로드·Git·실제 자료/criteria 읽기는0이다. 기존 노출 고지는 유지하며 설계자는 source/criteria 작성자나 최종 의미 judge를 맡지 않는다. Phase1은 미완료이고 유료 호출·공개 서비스 배포는0이다.
