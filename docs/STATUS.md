# 진행 상태

기준일: 2026-10-14 (Asia/Seoul).

## C2 원문 처리 구현·실제 Java/Python 대조

새 source inventory helper를 구현하고 공개 전체2문서에서49청크(18+31)를 생성했다. 실제 Java21 처리 결과와 원문·위치·순서·ID·hash가 **49/49 일치**했고 Java 전체 **127passed/0skip**, 새 Python helper **45passed/1Windows-link-skip**, Ruff가 통과했다. [재현·원본 영수증](MEETINGS-C2-SOURCE-PROCESSING.md)을 따른다. 새 품질 질문·합성 평가 본문·tokenizer·모델 호출은0이다.

첫 전체 Python 실행은1,523passed/2skip/2failed다. 변경하지 않은 기존 C0 runner의 임시 `report.tmp` 교체에서 Windows PermissionError가 발생했고, 하나는 실패 상태 때문에 gate가 거부됐다. 원본 로그를 `.local/c2-source-inventory-python-tests.log`에 보존한다. 해당2검사 재확인은2passed이며 전체 재검사 결과는 따로 기록한다. 동결 코드를 수정하거나 실패를 지우지 않았다.

같은 코드의 전체 재검사는 **1,525passed/2skipped**(121.88초, 기존 deprecation warning1)로 통과했다. 두 skip은 Windows에서 symlink 생성 권한이 없는 검사다. 첫 실패를 지우거나 실제 모델 재실행으로 대신하지 않았다. 자료 처리 소스13파일을 `meetings-c2-source-processing-freeze-v1.json`에 고정한다. 검증 자료 채택 과정에서 등록된 RST 원문3개의 명시적 plain-text 처리 필요성을 확인했으며, 현재 공개 calibration용 처리 결과를 보존한 뒤 질문 작성 전에 별도 후속 버전으로 해결한다.

공개 출처 등록 `a5cd9d5`의 push38494460795·PR38494467474 CI는 모두 성공했다. 구현 역할이 작업을 마친 뒤 새 격리 validation source 역할 생성도 실제 수락됐으며, 아직 source 채택만 진행하고 질문은 작성하지 않는다. 처리 helper/영수증 고정 후 calibration 합성 원문 작성과 일관성 검토로 이어간다. 전체 목표는 active이며 PR14는 draft다.

## C2 calibration 공개 출처 채택·처리 규칙 등록

고정된 OpenTelemetry community의 공개 절차 문서2개를 전체 본문·Apache-2.0·별도 고지 여부와 함께 검토했다. [채택·처리 규칙](MEETINGS-C2-CALIBRATION-SOURCES.md)과 [manifest](../data/evaluation/meetings-c2-calibration-v1/source-manifest.json)에 원본/처리본 SHA, Git blob, 원본 수집 영수증, 기존 Java/Python 처리 소스 hash를 기록했고 부모가 다시 대조했다. 실제 회의 발생이나 완료 기록으로 해석하지 않는다.

공개 calibration source2개만 채택됐으며 합성 본문·질문·oracle·선택 context·tokenizer·품질 모델 호출은0이다. 다음은 **새 처리 helper와 두 공개 전체 문서의 실제 Java/Python 청크 동등성 확인·동결**이다. 그 뒤 합성 원문을 작성·고정하고 새 질문을 준비한다. Validation 자료 채택은 아직 시작하지 않았고 역할 분리 후 별도로 진행한다. 사용자 승인 대기가 아니며 목표는 active다.

## C2 비교 실행·독립 검토 도구 구현

새 비교 runner, 공식 tokenizer 입력 준비, 엄격 oracle/판정 schema와 익명 audit를 실제 구현했다. [실행 계약](MEETINGS-C2-REVIEW-CONTRACT.md)을 따른다. 두 방식의 같은 DTO·교대 순서·calibration16/선택 후 validation12 호출 상한·실행 전 기록·한 번만 쓰는 출력 경로·90초 제한을 강제한다. 검토 판정을 먼저 잠근 뒤 대응표를 열고 전체 근거를 재생해 선택한다. 새 품질 질문·oracle·실제 비교 호출은 여전히0이다.

새 합성 검사145passed/1skipped와 Ruff가 통과했다. Windows에서 symlink 생성 권한이 없어 건너뛴1개는 별도 표시하며 실제 alias 차단 검증으로 세지 않는다. 성공 선택→별도12검증의 전체 파일 연결도 합성 데이터/가짜 native 기록으로 확인했다. 테스트 안의8/8·12/12는 모델 성능이 아니다. 실제 품질 검토·인간 검수·유료 사용0이다.

부모가 전체 Python도 실행해 **1,480passed/1skipped**를 확인했다(`.local/c2-comparison-full-tests.log`,105.46초). 기존 Starlette/httpx 사용 중단 경고1개가 있다. 이 변경은 Java/React 서비스 코드를 수정하지 않았으며 이전 Java125·타입/빌드·회의 브라우저5 결과를 새 측정으로 세지 않는다. 새 source 커밋의 원격 CI 상태는 PR에서 별도로 확인한다.

독립 코드 검토에서 artifact/gate 경로를 확인하기 전에 읽는 문제, 원본 native 메타데이터와 요약의 대조 누락, family별 구성 검사 부족, 시간/flag의 느슨한 타입을 찾아 수정했다. 입력·oracle·seed·출력 경로를 호출 전 등록하고 잘못된 경로는 파일을 읽기 전에 거부한다. Native 원본을 동결 mapper로 재생하고 설정·인용·토큰·시간·모델 식별을 별도로 대조한다. 수정 전 실제 품질 실행은 없었다.

이전 등록 커밋 `8a424be`의 push/PR CI는 모두 성공했다. C2 자원 계획28파일과 C1 실행 계획92파일의 hash도 그대로다. 현재 작업은 기존 Java/React API와 기본 모델을 바꾸지 않은 오프라인 비교 준비이며 phase1/PR14는 미완료/draft다.

**다음 실행:** 검증된 비교 소스41파일을 고정한 커밋에서 split별 자료 작성자가 공개 파일 이용 조건·본문 적합성·처리 규칙/원본 hash를 먼저 기록한다. 그 다음 새 calibration8/격리validation12를 작성·별도 사전 검토·tokenizer 준비하고 실행 계획을 봉인한다. 실제 비교 전에 질문을 보며 정책을 바꾸지 않는다. 전체 목표는 active이며 사용자 진행 지시를 다시 기다리지 않는다.

### 원격 Linux 실패와 질문 작성 전 고정 v2

구현 `48aa4f6`은 사용자 계정lingter100이 author/committer로 연결됐지만 원격 push/PR CI의 backend에서1실패가 났다(1,459passed/21skipped). Java-service와web은 성공했다. 합성 보류 fixture가 가짜 native 처리 시간을10ms로 고정해 Linux의 더 짧은 전체 요청 시간과 모순됐기 때문이다. 실제 시간 검사·모델·prompt·지표를 느슨하게 바꾸지 않고 fake backend의 시간값을 보류/잘림 fixture가 그대로 쓰도록 수정했다.

수정 후 해당 runner/audit75passed/1Windows-symlink-skip와 Ruff를 확인했다. `meetings-c2-comparison-source-freeze-v1.json`과 실패한 CI는 보존하고, 질문 작성 전 테스트1파일만 다른 **source-freeze-v2**를 등록한다. 새 품질 질문·모델 호출은0이다. 별도 Astra xhigh 역할이 calibration 공개 source 이용 조건/처리 manifest를 준비 중이며, 아직 질문/합성 원문을 작성하지 않는다. 새 validation 역할 생성은 thread limit으로 거절됐고 시작으로 집계하지 않는다.

수정 고정 커밋 `8582e60`의 [push38493453786](https://github.com/lingter100/doctrail/actions/runs/38493453786)와 [PR38493457841](https://github.com/lingter100/doctrail/actions/runs/38493457841)에서 backend·java-service·web이 모두 성공했다. source41파일이 실제 디스크·Git index의 hash와 같은지 확인했고 GitHub author/committer도 각각lingter100이다. CI 성공은 실제 모델 품질 또는 phase1 완료가 아니다.


**C2-P0 실제 자원 확인은 통과했다.** `662965d`로 고정한 문단·목록·표·코드 보존 후보를 새 합성 중립 자료2개에 한 번씩 실행했다. 정상3.079초(474입력/27출력/EOS), 강제 부하31.953초(3881입력/384출력/length)이며 source28해시·native로그0바이트·소유 프로세스 정리·metadata만 재시작을 확인했다. [실측 원본과 한계](MEETINGS-C2-RESOURCES.md)를 따른다. **native2·품질 질문/평가0이며 서비스 채택이 아니다.** 같은 중립 검사를 다시 실행하지 않는다.

블록1024 codepoints·출력384 tokens·90초 제한이며 큰 단위를 잘라 넣지 않고 명시적으로 거부한다. 새 어댑터 합성92개·자원 실행기15개가 통과했고 독립 코드 검토의 종료 실패 오판·중복 native 재시작 위험2개를 수정·재검토했다. 다음은 같은384/90 예산을 쓰는 줄 단위 대조군·새 비교 실행기·자료 가족을 고정한 뒤 신규 calibration/격리validation이다. 기존 질문을 재사용하지 않으며 전체 목표는 계속 활성 상태다.

C1 실패 보존 커밋 `ee8d0de`의 push/PR 필수 CI가 모두 성공했다. 새 후보 개발은 실패 기록과 별개이며 PR14는 계속 draft다.

C2 고정 전 전체 Python1,325개·Ruff가 통과했고 C1 실행 계획의92파일과 새28파일의 hash를 확인했다. Java125·React 타입/빌드·회의 브라우저5는 서비스 코드가 바뀌지 않은82b0fff에서 확인한 결과다. 이번 Python 후보 검사를 새 Java 서비스 지연이나 UI 검증으로 해석하지 않는다.

`662965d`의 push/PR 필수 CI도 모두 성공했고 GitHub author/committer가 각각lingter100인 것을 확인했다. 새 비교용 줄 단위 대조군은 별도 파일에서 구현했으며 원래 C0 prompt/grammar/mapper와384/90 제한을 합성10개로 확인했다. 대조군 추가 후 전체 Python1,335개·Ruff도 통과했다. 실제 C2 품질 비교는 아직 실행하지 않았다.

대조군·실측 보존 커밋 `ddae7bb`의 push/PR 필수 CI도 모두 성공했다. [새 비교 계획](MEETINGS-C2-COMPARISON-PLAN.md)과 [4계열 registry](../data/evaluation/meetings-c2-family-registry-v1.json)를 질문보다 먼저 등록한다. Calibration8/validation12의 출처·언어·답변 가능성 구성과 선택 조건을 고정했지만 실제 질문·oracle·context는0이다. 공개2계열의 고정 commit·경로·LICENSE/NOTICE 메타데이터를 확인했고 개별 문서 이용 조건·본문 적합성은 자료 작성자가 확인해야 하므로 source 채택은 HOLD다. 사용자 승인 대기가 아니다.

등록 당시 남은 작업이었던 비교 runner·익명 audit·metric/review schema는 위 최신 묶음에서 구현했다. 새 질문 작성·실제 품질 호출은 아직 미완성이며 기존 실험의 재실행으로 대신하지 않는다.

**C1 실제 비교는 구조 오류로 종료했다.** `45810d2`에서 중립2건/native4회는 통과했고 calibration8계획 중4건/native8회를 실행했다. 네 번째 V0가 초안 주장2개 중1개만 검토해 `generation_invalid_review`로 차단됐다. 나머지4건과 validation은 실행하지 않는다. [원본·실측·원인](MEETINGS-C1-RESULTS.md)을 보존하며 처음3건의 구조 수용을 의미 정답으로 세지 않는다. 사후 부분 의미 검토도 완료했으며 [문단 보존 후속 설계](MEETINGS-C1-FAILURE-FOLLOWUP.md)에 따라 새 단일 생성 후보와 자원 진단을 구현한다. 전체 목표는 활성 상태이며 사용자 진행 지시를 기다리지 않는다.

중립+calibration 총12native회, D1/V1실행0, 유료0이다. calibration 요청은69.094~119.032초이며 모두120초이내지만 수정 경로의 여유는 입증되지 않았다. 종료 후92파일해시 일치·프로세스정리·native로그0바이트를 확인했다. 원본의 초기false flags는 그대로 보존한다. 준비커밋45810d2의 push/PR 필수 CI는 모두 성공했다. PR14는 draft이고 회의1차 자연어답변은 미완성이다.

별도 AI가 역할 대응표를 열기 전에 부분 판정8개를 고정했다. attempted4의 완전 적합은 D0 0/4→C1 0/4다. 인용 문자열·위치58/58은 정확하지만 답변7개 모두 주장 전체를 선택 인용이 지지하지 못했다. 내용의 필수 항목 포함은 양쪽3/4지만 이를 근거 일치로 바꾸어 해석하지 않는다. 선택 조건·문장 후반·추가 열거의 근거 누락을 기준으로 **새 근거 단위 설계**를 진행한다. 새 부분 감사 도구의 합성5개와 모델 없는3artifact 재생이 통과했다. 형식 수정만으로 충분하다는 가설은 채택하지 않는다.

## C1 실행 전 준비 기록

**연속 개발 목표가 활성 상태다.** 사용자의 “계속 목표 설정해서 진행해” 요청에 따라 회의 1차 확장 완료 목표를 실제 goal 도구로 등록했다. C1 어댑터·단계 실행기·자료 가족은 `82b0fff`에서 고정했고 해당 push/PR 필수 CI가 모두 통과했다. 계획만 전달하고 다음 지시를 기다리지 않는다. 기존 동결 비교는 재실행하지 않으며 PR #14는 draft다.

C1 코드·가족 등록을 [새 source freeze](../data/evaluation/meetings-c1-source-freeze-v1.json)로 고정한다. 전체 Python 1,194·Java 125·회의 브라우저 회귀 5·프런트 타입/빌드·Ruff가 통과했다. 독립 코드 검토의 요청별 telemetry 경합과 watchdog 시작 실패 시 native 정리 누락을 수정하고 각각 합성 회귀로 확인했다. Windows 파일 교체의 일시적 잠금에는 같은 바이트의 저장만 최대 3회 시도하며 모델 재시도는 0이다. 고정 native의 `--no-warmup` 지원을 도움말로 확인했고 실제 C1 생성은 아직 0이다. 다음은 고정 코드 이후 새 calibration 8항목 작성·사전 검토와 중립/실제 비교다.

**사용자 비용 결정: 무료·로컬만 사용한다.** 24회·US$2 이내 API 비교 제안에 사용자가 “유료 사용 보류하고 무료만 가능하게”라고 답했다. API 호출·키 접근·과금은 0이며 승인 대기 중인 작업이 아니다. 유료 요청을 반복하지 않고 무료 후속 설계를 진행한다. 공개 서비스 배포는 별도 승인 범위로 유지한다.

**C0 실제 비교도 의미 기준 실패로 종료했다.** `7c59042`에서 중립 2회는 정상 답변/보류를 확인했고, 알려진 4회는 모두 구조 검사를 통과했다. 인용 9개는 원문·codepoint 위치와 정확히 일치했다. 별도 AI 검토의 전체 의미 기준은 2/4다. 진행자 안내 누락은 회복했지만 데모 의제를 완료 사실로 바꾼 주장과 선택한 인용 밖의 개인정보 이유가 남았다. [원본·독립 검토](../experiments/results/meetings-spans-c0-known-v1.semantic-review.json)를 보존한다. 같은 네 사례의 수정·재실행은 종료하고, 새 검증 12건 호출은 0으로 유지한다. Python 전체 1,077개·Ruff와 해당 head의 push/PR 필수 CI 3종이 통과했지만 자연어 답변 기능 완료나 main 통합은 아니다.

새 calibration은 8문항(공개4·합성4, KO4·EN4, 답변가능6·근거부족2) 작성과 별도 AI 사전검토 8건을 마쳤다. 채점 기준 명확화 1건을 수정·재확인했고 질문·원문은 바꾸지 않았다. 공개 원문4개의 고정 바이트·이용 조건, 원문 구간19개·인용24개 검사가 통과했다. 작성 시점 summary의 독립검토0과 이후 별도 prereview receipt의8을 구분하며 사용자 검수는0이다.

[92파일 실행 계획](../data/evaluation/meetings-c1-execution-plan-v1.json)에 입력·oracle·검토·토큰 준비·익명화 seed hash를 고정했다. 공식 tokenizer의 계획 여유 포함 최대는 calibration3,621·중립2,138 tokens로4,096 아래다. 실제 native 토큰과 동일함이나 최악 상한의 증명은 아니다. 새 도구의 합성19·전체 Python1,213·Ruff가 통과했고 기존46파일 동결을 확인했다. [검토 절차](MEETINGS-C1-EXECUTION.md)의 입력 snapshot 경합도 수정·독립 재검토했다. 다음은 중립2개와 calibration8개의 실제 로컬 실행이다. 현재 C1 native/model 호출0, validation작성0이며 자연어 답변 완료가 아니다.

## 이전 진행 기록

아래는 시점별 준비·실패·완료 기록이다. 각 시점의 “다음”, “아직 확인 전”은 현재 실행 지시가 아니며 위 최신 상태와 동결 계획을 우선한다.

C0 구현·독립 코드 검토를 마치고 [6회 한정 계획](../data/evaluation/meetings-span-c0-plan-v1.json)을 준비했다. 원문 전체를 보존하는 480-codepoint 구간, 최대 160구간, 기존 4096/768-token·120초 제한을 고정한다. 새 합성 단위·실행기 검사 102개가 통과했고 알려진 입력의 기계적 분할은 30~85구간이다. 실제 native 문법·답변 품질은 아직 확인 전이다. 중립 2회 뒤 통과 시 알려진 4회만 실행하며 validation 단계는 계획에 없다. 실패 후 같은 사례에 추가 수정·재실행하지 않는다.

무료 C0 인용 구조를 새 파일에서 구현 중이다. 기존 Java 응답 계약을 유지하고 Python 모델 어댑터가 원문 구간을 복원한다. 준비 단계의 전체 staged 공백 검사 출력에서 부모에게 새 검증 자료의 일부 공개 원문이 노출되어 [사고 기록](MEETINGS-VALIDATION-EXPOSURE.md)을 남겼다. 질문·정답·모델 출력은 보지 않았고 구현자·설계자는 원문을 보지 않았다. 엄격한 완전 블라인드라고 주장하지 않는다. C0의 수치·분할·출력 정책 결정은 그 전에 끝났으며 현재 새 실행 준비는 중립 최대 2회와 알려진 질문 4회까지만이다. 기존 12문항은 미실행으로 보존한다.

이번 후속 로컬 검증은 Python 975개·Ruff·M5-B 동결 18파일·9B 계획 33파일·기존 출력 구조 계획 24파일 검사를 통과했다. 새 12문항은 공개 6/합성 6, 답변 가능 8/근거 부족 4이며 AI 작성·독립 검토 12, 사용자 검수·모델 호출·토크나이저 호출 0이다. 최초 두 명확화 권고만 수정·재검토했고 원문과 인용은 바꾸지 않았다. 독립 검토자의 뒤늦은 후보 실패 정보 노출 한계는 summary/receipt에 명시한다. [실패 gate 확인](../experiments/results/meetings-qwen35-validation-gate-v1.json)은 실제 67개 파일 바인딩을 확인한 뒤 입력 해석·모델 로드 전에 종료됐으며 새 질문을 실행하지 않았다.

**최신: 9B 답변 후보도 품질 기준 미달, 1차 확장은 아직 미완성이다.** `f81fd8b`의 고정 정책으로 중립 자원 확인 2회와 알려진 개발 질문 4회를 각각 한 번 실행했다. 자원 확인은 통과했지만 답변은 구조 검사 2/4, 별도 AI의 전체 의미·완전성·인용 기준 1/4 통과다. 공개 답변의 Markdown 표식, 진행자 답변의 따옴표가 원문과 달라 차단됐고, 진행자 정보 누락과 한국어 부연의 선택 인용 지지 부족도 남았다. [원본·분석](MEETINGS-RESULTS.md)을 보존한다. 기존 gate를 완화하거나 새 검증 12문항을 실행하지 않는다.

9B의 Python 어댑터 답변 시간은 4.249~13.128초다. 중립 확인 중 측정한 native RSS 최대 표본은 6,355.8125MiB, 전체 GPU 최대 표본은 4,619MiB이며 로드 시작 구간을 포함한 정확한 peak가 아니다. Java HTTP 수치나 답변 품질로 바꾸어 해석하지 않는다. 4B 분석·회의 관리의 기존 33개 운영 검사와 실제 UI 9개 검사는 유효하지만 자연어 답변 완료를 뜻하지 않는다.

후속 선택은 [무료 인용 구조 제안](MEETINGS-CITATION-ARCHITECTURE-PROPOSAL.md)과 [제한된 API 비교 제안](MEETINGS-API-COMPARISON-PROPOSAL.md)에 분리한다. 유료 제안은 최대 24회, 사용료 US$2 이내의 계획이며 승인·키 확인·호출은 모두 0이다. 무료 설계·구현은 별도 사전등록으로 이어갈 수 있다. 같은 네 질문에 추가 프롬프트/모델 조정을 반복하지 않는다. 새 검증 실행기는 실패한 사전 gate에서 모델 로드 전에 차단하도록 구현했으며 실제 validation 호출은 0이다.

원격 CI: `f81fd8b`의 선택 의존성 없는 CI에서 자원 모의 검사 2개가 psutil 부재로 실패했다. 기존 동결 의존성을 변경하지 않고 해시가 고정된 CI 전용 설치를 `2bff59a`에 추가했고, 해당 push·PR의 backend/java-service/web은 모두 성공했다. Draft PR #14는 계속 draft이며 main에 통합하지 않았다.

실제 회의 관리 검증 `453bd5f`: Java·4B GGUF·CPU 검색·React를 연결해 분석4건과라이프사이클33검사를 통과했다. 전송 대역 없는 브라우저9검사, 원문 근거·저장된 작업·모바일 화면을 확인했다. [원본](../experiments/results/meetings-operations-v1.json), [UI](../experiments/results/meetings-operations-v1.ui.json), [독립 AI 검토](../experiments/results/meetings-operations-v1.semantic-review.json)를 보존한다. 자연어 답변 호출0이며 전체1차 완료가 아니다. 실제 사용된48개 소스는 해당 커밋과 일치했고 실행 중 변경이 없었다. 별도9B 준비 파일 때문에 dirty=true였음을 유지한다.

운영 보고서 한계: 테스트 클라이언트가 반환 객체를 편집하면서 두 합성 회의의 저장된 `analysis`에도 이후 확정 상태가 반영됐다. 원본보고서는 수정하지 않는다. 별도 `ai_analysis`는 처음의 확인 필요 상태를 그대로 보존하고115개 인용이 원문에 맞는다. 후속 실행에서 깊은 복사로 이 기록 오류를 막는 새 검증 기반과 회귀 검사를 추가했다. 기존GPU실행을 반복하지 않는다.

출력 구조 비교 `730ea0c`도 완료됐다. 네 raw 출력의 JSON은 모두 유효하지만 진행자 인용은 여전히 거절됐고 공개 답변의 출시 시점 합성이 남아 의미 gate2/4로 실패했다. 다른 세 출력은 v2와 동일하다. [원본·별도 AI 검토](../experiments/results/meetings-answer-decoder-v1.semantic-review.json)를 보존한다. 같은 사례에 추가 프롬프트 수정을 하지 않는다. 새 실험용 launcher와 별도 분석·라이프사이클 운영 검증기를 준비하며, 이 검증은 자연어 답변 readiness를 포함하지 않는다.

최신 후속: `38d02a9`의 원문 인용 우선 v2 답변4건을 한 번 실행했다. 3건 형식 통과·진행자 답변 JSON 실패이며, 별도 AI 검토에서 진행자 인용 불일치와 공개 답변의 출시 시점 합성도 확인했다. 한국어 날짜·로그 금지는 회복했지만 의미 gate는 실패했다. 원본과 검토를 보존하고 [출력 구조만 제한하는 비교](MEETINGS-ANSWER-DECODER-PLAN.md)를 별도 고정한다. 같은 질문/프롬프트·모델로4건1회, 분석0·재시도0이다. 정확한 인용·의미·완전성 검사는 완화하지 않는다. 해당 head의 push·PR CI3종은 모두 통과했으며 기능은 여전히 draft PR에 있다.

최신 실제 결과: `1b01139`로 고정한 무료 로컬 4B 양자화 비교5요청/16completion을 완료했다. 분류·담당자 미정 작업과 영어 근거 인용은 회복됐지만 출시 예정/완료 혼동, 날짜 누락, 답변 언어 문제가 있어 의미 gate는 실패했다. [원본·해석](MEETINGS-RESULTS.md)을 보존하고 후속 답변 정책을 별도 설계한다. 동일 head의 push·PR 필수 CI3종은 모두 성공했다. 기능은 여전히 개발 브랜치와 draft PR에 있으며 main 통합·1차 전체 완료·M5-B 평가 완료가 아니다.

회의 확장 후속: 실제 Java 서비스 v2도 담당자 미정 작업 누락에서 중단됐고, 별도 AI 검토에서 복합 답변의 잘못된 인용과 누락이 확인됐다. 전체 청크 전달로 영어 근거 유실을 고친 개발 v11도 의미 오류가 남았다. 출력·실패를 보존한 뒤 무료 로컬 4B 양자화 후보의 명시적 준비·hash 검증·실행 어댑터와 알려진 실패5개 비교를 준비 중이다. [사전 조건](MEETINGS-GGUF-CANDIDATE.md)을 따른다. Draft [PR #14](https://github.com/lingter100/doctrail/pull/14)의 `1c771c5` push·PR 필수 CI 3종은 성공했지만, 미완성 품질과 후속 미커밋 변경이 있어 main에 통합하지 않았다.

GGUF 준비: 실제 가중치·실행 archive·license·runtime55개 검증과 설정 확인용 native1회가 통과했다. 로드 직후 GPU 스냅샷3733MiB는 최대 사용량이 아니다. 기존 Torch 실행과 새 native 실행의 GPU 선점 경합을 공통 사전 잠금으로 고친 후 Python848개·Ruff·기존18파일 동결 검증이 통과했다. 다음은 커밋으로 고정한 알려진 실패5개 비교이며 아직 품질 통과 결과는 없다.

**최신 사용자 요청: 회의록 지능형 관리 1차 확장 구현 중.** 기존 `main`의 `3d39c5a`에서 깨끗한 상태와 중복 모델 작업·잠금 부재를 확인하고 `feat/meeting-intelligence`를 시작했다. [공통 설계](MEETINGS-DESIGN.md)를 따라 문서·권한·리비전 저장을 재사용한다. Java 서비스, React 화면, 별도 로컬 AI worker를 구현하며 아직 기능 완료나 모델 품질 통과를 주장하지 않는다. 녹음·STT·실시간·외부 회의 도구 연동은 2차 범위로 보류한다.

M5-B 준비 결과와 18개 동결 파일을 보존하고 예정된 비교 실행은 이 새 사용자 우선순위 뒤로 미룬다. 기존 validation 질문·정답에 접근하거나 기존 모델 실험을 반복하지 않는다. 새 회의 기능의 개발·통합 검증 자료는 별도이며 일반화 성능 평가가 아니다. 실제 공개 Jupyter 회의록 2건·진행자 운영 문서 1건은 `data/manifests/meeting-public-v1.json`의 고정 revision·BSD-3-Clause·원문/처리본 hash를 따른다. 소량의 공개 검증 fixture만 저장하며 접속·연락처 행 제거를 명시한다. AI 작성 한국어 회의 2건·영어 운영 문서 1건은 별도 synthetic 파일이다. 사용자 검수는 0이다.

중간 구현 기록: Java 회의 등록·비동기 분석 계약·원문/분석 revision·사용자 편집 보존·결정 연결·작업·권한 선필터 통합 검색을 구현했다. React 회의/작업/Q&A 및 데스크톱·모바일 원문 확인을 연결했다. Java 124개와 기존 실제 HTTP 11묶음이 통과했으며 일반 문서 DTO 호환 회귀를 발견·수정했다. 브라우저 전체 27개와 답변 후보 수 조정 후 새 기능 5개가 통과했다. 브라우저 성공 모델 대역은 명시적 합성 전송 fixture이며 실제 생성 품질로 집계하지 않는다. 실제 GPU 서비스 v1은 공개 분석 2건·일반 문서 답변 뒤 다중 회의 인용 검증 실패로 중단됐다. 원본과 AI 의미 검토를 보존하고 새 모델 경로를 수정 중이다. **아직 1차 기능 전체 완료·원격 통합을 선언하지 않는다.** [실패·검증 구분](MEETINGS-RESULTS.md), [API·운영·시연](MEETINGS-RUNBOOK.md)을 따른다.

**M5-B 자료·정책 사전 준비 완료, 새 생성은 0회.** [사전등록](M5-CALIBRATION-PLAN.md)과 [준비 결과·실패·재현법](M5B-PREPARATION.md)을 따른다. Registry를 질문보다 먼저 `2de1487`에 고정하고 calibration 24·validation 24·별도 예시 3개를 작성했다. 합성 원문은 81개(38/38/5)다. 서로 다른 작성·검토 역할로 51개 항목의 의미를 검토했고 초안 결함 7개를 수정·재검토했다. Validation을 읽기 전에 예시는 `f7e9692`로 고정했다. 부모·prompt 작성자는 validation 문구·정답·검토 본문을 읽지 않고 hash·집계만 확인했다. 사용자 검수는 0이다.

고정 tokenizer로 양쪽 정책 각각 48입력, 총 96개의 전체 prompt를 확인했다. 최대 입력은 baseline 753, few-shot 1,039 tokens로 cap 1,536 아래이며 잘림 0·초과 0이다. 실제 Torch import·가중치 열기·기존 평가 자료 접근을 차단한 별도 프로세스에서 통과했고 모델 호출은 없다. 계열 간 정확 중복과 0.85 문자열 유사도 경고는 각각 0개지만 이를 의미 독립성의 자동 증명으로 쓰지 않는다. [준비 영수증](../experiments/results/m5b-preparation-v1.json) SHA는 `95cdd2f70139f0bb08f331909aedc97a67e1debc17fa790c9ff42836f04dc5ad`, [18파일 동결](../data/evaluation/m5b-preparation-freeze-v1.json) SHA는 `09e055bc9928efab2f479ff86a8ba7114aad7818d19dba12adac30f21dc1ddfb`다. `generation_ready=false`이며 실제 생성 완료·성능 개선·서비스 채택을 뜻하지 않는다.

이 묶음의 로컬 검증: Python **711passed**(새 의미 있는 검사 25개, 기존 deprecation warning1), Java **82passed**, Playwright **22passed**(Chromium19·순수 helper3), 프런트 타입·production build·Ruff 통과. 별도 코드 검토에서 준비 범위의 blocker는 없었다. 모델 없는 자료·검토 재검사와18파일 hash 검증, 기존 M5 v1/v2 동결 바인딩 보존을 확인했다. CI는 tokenizer를 새로 측정하지 않고 자료·검토·저장 hash를 확인한다. 정확한 PR head 및 main의 원격 검사 상태는 GitHub 기록과 구분한다.

다음은 **새 실행기·형식/인용 판정 분리·익명화 의미 검토·사전 W/C/F 선택 규칙**을 구현하고 실행 계획을 동결한 뒤 calibration 두 정책 각24회, 선택 정책 validation24회를 한 번씩 수행하는 것이다. 기존 M5-A나 M4 평가를 반복하지 않는다. Validation의 질문·정답·의미 검토 설명은 격리된 검토 역할만 읽는다. 이미 고정한 예시를 validation에 맞춰 고치지 않는다. Java Q&A 연결·기본 채택·최종 test 개방·유료 사용·외부 서비스 배포는 아직 아니다.

선행 [PR #12](https://github.com/lingter100/doctrail/pull/12)는 `f4d4b8d`로 main에 통합됐고 동일 SHA의 [main CI](https://github.com/lingter100/doctrail/actions/runs/38338891892)가 성공했다. 새 묶음을 시작할 때 기존 GPU 작업·잠금이 없음을 확인했다.

M5-B 원격 증거: [PR #13](https://github.com/lingter100/doctrail/pull/13)의 구현·자료 head `8bb2b91`에서 [push CI](https://github.com/lingter100/doctrail/actions/runs/38345095633)와 [PR CI](https://github.com/lingter100/doctrail/actions/runs/38345133958)의 java-service·backend·web이 모두 통과했다. 원격 Python은 **690passed/21skipped**이며 선택적 모델 의존성 부재로 인한 skip을 로컬711개와 구분한다. 브라우저22개와 새 모델 없는 자료·검토·18파일 동결 확인도 통과했다. GitHub API에서 작성자·커미터가 모두 lingter100으로 연결되고 미해결 review thread0을 확인했다. 이 증거 문서 커밋까지 포함한 최종 head와 main 통합은 같은 PR·GitHub Actions의 정확한 SHA로 확인한다.

**M5 첫 로컬 생성 검증 완료, 답변 품질은 미달.** 깨끗한 `93d6e2f`에서 수정 v2의 실제 GPU11회와 빈 근거 사전 차단1개를 완료했다. 실제 적용 설정16개 필드와 `greedy_search`를 매 요청 검사했고 한·영 기본 실행 조건과 메모리 한도를 통과했다. 그러나 JSON 거절2개, 정상 모델 보류0/4이며 인용이 유효한9답변 중3개는 누락·충돌 무시·대상 혼동 문제가 있다. 두 실행의 raw 출력11개는 동일해서 설정 오류 수정으로 품질이 좋아졌다고 말하지 않는다. [실패·의미 분석](M5-GENERATION-ANALYSIS.md)을 따라 새 문서 family를 분리한 M5-B calibration/validation과 제한된 보류·완전성 개선을 별도 설계한다. Java Q&A 연결·기본 채택·최종 test 개방은 아직 하지 않는다.

[v2 원본 보고서](../experiments/results/m5-generation-v2.json)의 SHA는 `85a057d52a4a9375e89a18e1a701940c546e8feb39c979c995879654e43d1556`, [journal](../experiments/results/m5-generation-v2.progress.jsonl)은 `a2327b8b1c0e0cbdb96b604bcd4ae08893eb50a9ff13ed4bd6cd9a16035ca10f`다. 공개 사본은 원본 바이트 그대로이며 모델 없는 재생이 통과했다. 입력501~703 tokens, 출력 총628 tokens, Python 순차 생성 중앙값3.196초(0.868~4.654초), 최대 reserved3622MiB다. Java HTTP·동시 검색 모델·최대 길이·실사용 부하 수치가 아니다. 사용자 검수0·유료API/GPU/클라우드0·외부 서비스 배포0이다. 원격 CI·PR 통합은 후속 기록에 남긴다.

[별도 AI 의미 검토](../experiments/results/m5-generation-v2.semantic-review.json)는 실제12사례·9주장을 원본 report/fixture hash에 연결한다. 로컬 재생은 Torch·Transformers·NumPy·safetensors import와 모델 파일·최종 test 질문·학습 pack 접근을 막은 별도 프로세스에서도 통과했다. 구현 head `93d6e2f`의 [원격 CI](https://github.com/lingter100/doctrail/actions/runs/38337916124)는 Python665passed/21skipped, 실제 Java HTTP11묶음·브라우저22개를 포함해 성공했다. 로컬686개와 원격의 선택 의존성 skip을 구분한다. 결과 문서·재생 CI까지 포함한 PR 최종 head는 통합 전에 별도로 확인한다.

**M5 v1 실행 완료, 생성 설정 위반으로 기준 결과 무효.** 실제 GPU11요청과 빈 근거 사전 차단1개는 끝났으나 Transformers4.57.6이 요청한 `do_sample=False`를 모델 기본값 `True`로 바꾼 경고를 발견했다. 중단을 시도했을 때는 이미 모든 요청이 끝났고 실제 종료시킨 프로세스는 없다. `completed`를 등록한 greedy 설정 준수로 해석하지 않는다. [원본 보고서](../experiments/results/m5-generation-v1.json)·[진행 기록](../experiments/results/m5-generation-v1.progress.jsonl)과 [설정 감사](../experiments/results/m5-generation-v1.protocol-audit.json)를 보존한다. 기존 v1 소스를 바꾸지 않고 새 v2에서 실제 적용 설정을 검사하며, 프롬프트·질문·모델을 고쳐 점수를 튜닝하지 않는다.

수정 v2 실행 전 전체 Python686개·Ruff를 통과했다. 실제 설치 라이브러리의 설정 준비 함수에서 v1 오류와 v2 greedy 적용을 모델 없는 CPU 검사로 재현했다. [v2 계획](../data/evaluation/m5-generation-plan-v2.json) SHA `f0ac2fd91c2356c03b5b53feaed729825641fec968be61880f9e02f311ce6045`에12개 소스/설계와 동일 입력을 고정한다. [v1 실패 분석·v2 사전 수정 범위](M5-GENERATION-ANALYSIS.md)를 기록한 뒤 새 실행을 한 번 수행한다.

모델 준비에서도 디렉터리 목록의0바이트 표시만으로 전송을 중단한 판단 오류가 있었다. 닫힌 partial은 실제3,355,443,200바이트였으므로 네트워크 정지로 확정하지 않는다. 받은 바이트 수를 직접 알리는 기능을 추가했고 동일 고정 snapshot의11개 파일·총4,079,448,540바이트를 다시 검증했다. [준비 과정 기록](../experiments/results/m5-generation-preparation-v1.json)을 남긴다. GPU 실행과 분리된 준비 실패이며 유료 사용은0이다.

**M5 첫 생성 계약 구현·실행 준비 중.** [PR #11](https://github.com/lingter100/doctrail/pull/11)은 `be896c3`으로 통합됐고 [main CI](https://github.com/lingter100/doctrail/actions/runs/38332721238)가 성공했다. 새 `feat/grounded-generation`에서 고정 Qwen3-1.7B 로컬 런타임, 엄격한 답변/보류·인용 검사와 합성12항목의 실행 계획을 준비한다. 원문 인용 일치와 의미 정확도를 분리하며 아직 생성 성공·Java 질의응답 연결을 주장하지 않는다. 기존 학습·calibration/main-dev를 반복하지 않았다.

GPU 실행 전 검증: 전체 Python669개, Java82개, Playwright22개(Chromium19·순수 helper3), 프런트 타입·production build·Ruff 통과. Python 경고1개는 기존 Starlette/httpx deprecation이다. 새 watchdog은 fake 검사와 별도로 실제 CPU child process의 제한시간 초과·강제 종료를 확인했다. [동결 계획](../data/evaluation/m5-generation-plan-v1.json)의10개 소스/설계 바인딩·합성12개 입력 검증을 마쳤다. 계획 SHA는 `6adf2fda8837d2d6df54070a5c3fa583b8168c0b1430364719ed7ab01c4849b6`이며 결과를 보기 전에 커밋한다.

[PR #10](https://github.com/lingter100/doctrail/pull/10)은 `1051af7`로 main에 통합됐고 [main CI](https://github.com/lingter100/doctrail/actions/runs/38327502543)는 성공했다. 완료된 모델 비교는 재실행하지 않았다.

**M4 학습 저장본 로컬 운영 검증 완료.** `61285dd`의 깨끗한 작업 트리에서 실제 CUDA·Java·React의16검사 묶음을 통과했다. 권한 회수·문서 갱신/재처리/삭제·원문 근거·모델 identity·이력·worker 장애·base 복구와 실제 데스크톱/모바일 흐름을 확인했다. [결과·실패·한계](M4-OPERATIONS-RESULTS.md), [원본 보고서](../experiments/results/m4-terminal-service-v1.json), [실행 안내](MODEL-SERVING.md)를 따른다. 기본 BM25·base는 유지하고 학습 모델은 명시적 실험 경로다. 운영 통과를 새로운 검색 품질이나 기본 모델 채택으로 해석하지 않는다.

현재 묶음의 로컬 검증: Python518개(잠금 후속 수정 포함)·Java82개·Playwright22개(Chromium19·순수 helper3), 실제 기본 Java HTTP11묶음, 타입·production build·Ruff, 기존 main-dev의 모델 없는 저장 순위 재생 통과. 브라우저 첫20통과/2실패는 공유 서버의 정상 인증 제한이 원인이었고 spec별 서비스/DB 격리로 해결했다. 최초 실패와 성공을 모두 보존했다. 새 GPU 추론은 합성 운영 자료에만 실행했고 완료된 calibration/main-dev는 반복하지 않았다. 다음은 M5 근거 기반 답변·보류의 별도 설계와 로컬 생성 모델 자원·라이선스 확인이다. Test 잠금·사용자 검수0·유료 사용0·외부 서비스 배포0을 유지한다. 이 브랜치의 원격 CI·PR 통합은 아래 후속 기록을 따른다.

**M4 main-dev 실제 비교 완료.** 실행 전 `6938c3c`에 고정한 계획·코드·설계로 새 base/terminal을 한 번 비교했다. 양성59질문의 전체 근거 @50은34→47, @5는29→37로 통과했다. @50 회복15·퇴보2, @5 회복14·퇴보6이며 다중 문서 @5는1→0/7이다. [분석](M4-MAIN-DEV-ANALYSIS.md)과 [보고서](../experiments/results/m4-main-dev-v1.json)를 따른다. 새 base는 과거 M3 dense의79질문 후보 순위·점수와 정확히 같았다. 원본 보고서·journal을 바이트 그대로 보존했고, 모델·로컬 학습 pack·test 질문 접근을 차단한 상태에서도 공개 자료 재생이 통과했다. 후속 로컬 운영 검증은 위 최신 기록에 완료 결과가 있다. 기본 서비스 모델·검색 정책을 바꾸지 않았으며 calibration/main-dev 재튜닝·test 개방은 하지 않는다.

Main-dev 비교 묶음 당시 로컬 검증: 전체 Python478개(새 실행기29개 포함), Java59개, Chromium18개, 프런트 타입·production build, Ruff 통과. 기존 Starlette/httpx deprecation warning1개는 남아 있다. 원격 검증·통합 상태는 아래 후속 기록을 따른다. Python 시간은 HTTP가 아니다. 사용자 검수0·외부 서비스 배포0·유료 GPU/API 사용0이며 전력·개발 보조 비용은 미측정이다.

**사용자 요청으로 재개.** 2026-10-13 “진행해” 요청을 받아 중단 기록·Git 상태·진행 중인 프로세스를 확인했다. 중복 GPU 작업은 없고 기존 파일을 보존한다. `doctrail` 예약은 기존 한글 설명·이름·주기를 보존한 ACTIVE 상태로 재개·검증했다. 아래 일시중지는 과거 이력이며 현재 재개 승인을 대신하지 않는다.

재개 후 통합: [PR #9](https://github.com/lingter100/doctrail/pull/9)는 `66d2406`으로 main에 병합됐다. 정확한 head의 [push CI](https://github.com/lingter100/doctrail/actions/runs/38325419320)와 [PR CI](https://github.com/lingter100/doctrail/actions/runs/38325423268)에서 java-service·backend·web이 모두 성공했다. 원격 Python429passed/20skipped(선택 모델 의존성 없음)·Chromium18passed·모델 없는 readiness v1/v2 재생을 확인했다. 로컬449개 통과와 원격 모델 미실행을 구분한다. GitHub API에서 작성자·커미터 모두 lingter100임을 확인했고 feature 브랜치를 정리했다. 새 `feat/main-dev-evaluation`에서는 기존 학습 저장본의 별도 dev 비교를 준비하며 아직 새 dev 추론은 실행하지 않았다.

동일 통합 SHA의 [main CI](https://github.com/lingter100/doctrail/actions/runs/38325650456)도 성공했다.

**사용자 요청으로 일시중지.** “일단 멈춰 나중에 다시 시작할게” 요청에 따라 작업과 서브에이전트를 중단하고 `doctrail` 예약을 PAUSED로 확인했다. 예약 설명 저장 중 생긴 한글 인코딩 오류도 정상 한글로 복구·검증했으며 예약은 재개하지 않았다. 사용자가 명시적으로 다시 시작하기 전에는 개발을 이어가지 않는다.

중단 시점: `feat/train-readiness`, 마지막 커밋 `8a9d3eb`. 실제 학습·calibration·replay 및 로컬 검증은 완료됐지만 문서 변경은 일부 미커밋이고 PR 생성·push·원격 CI·main 통합은 아직 하지 않았다. GPU 작업은 끝났고 분석 에이전트는 중단했다. 재개하면 Git 상태부터 확인하고 `docs/M4-CALIBRATION-ANALYSIS.md`의 존재·완성 여부를 확인해 사례 분석을 마친 뒤 문서·PR·필수 CI 통합을 완료한다. 저장된 학습이나 calibration을 다시 실행하지 않는다. 주요 분석 단서: 001은 base의 한국어 대체 근거, 002는 다른 설명 청크가 있어 주석 지표와 답변 가능성을 구분해야 한다. @5 퇴보010·014·015, MRR 추가 퇴보003, 계속 누락016도 보존한다.

선행 M4 단계: fit64·calibration16을 분리하고 음성128쌍·잘린12입력을 검토했다. 첫 GPU 수치 실패를 보존한 뒤 고정 배율1024에서16회 실제 가중치 갱신을 마쳤다. 내부 평가의 근거 회수는 @50 **13→15/16**, @5 **8→11/16**으로 사전 조건을 통과했으나 @5 퇴보3개도 있다. [실행·실패 기록](M4-READINESS-RESULTS.md)과 [품질 분석](M4-CALIBRATION-ANALYSIS.md)을 따른다. 이후 별도 main-dev 결과는 위 최신 기록에 있다. Java/React는 원래 검증 모델을 유지하며 학습 모델 채택·생성 답변·외부 배포는 아직 아니다.

선행 확인: 빈 작업 폴더, 별도 상위 프로젝트 지침 없음, GitHub 사용자 인증 확인, Python 3.11·Node·uv 사용 가능, RAM 약 32GB·RTX 4050 6GB 확인. Docker 명령은 설치되어 있으나 엔진은 실행 중이지 않음. 첫 단계는 Docker 없이 실행한다.

## M1에서 구현·검증한 범위

- 계정·세션·작업공간, 워크스페이스/개인 문서 권한, TXT·MD·텍스트 PDF 업로드, 본문·청크 저장.
- BM25 검색 전에 권한 필터를 적용한다. 원문 구절·PDF 페이지·리비전 확인, 수정·삭제와 검색 반영, 실패 이유·재처리, 개인 검색 기록·피드백.
- 자동 테스트 36개 통과. 로그인·권한·변경·삭제·재처리·Unicode/PDF 근거·내용 없는 로그·백업 복구·평가 입력 드리프트·분할 누출 거부를 포함한다.
- 프런트엔드 타입 검사·빌드 통과. 실행 시점 npm audit 0 vulnerabilities.
- 브라우저에서 로컬 검증용 계정 생성 → 합성 문서 업로드 → 검색 → 원문 확인 → v2 수정 → 새 내용 검색 → 피드백을 실제 수행했다. 데스크톱과 390px 화면을 확인했고 모바일 가로 넘침은 없었다. AI가 수행한 점검이며 사용자 검수는 아니다.
- 실제 로컬 서버를 중지·재시작한 뒤 브라우저에서 v2 문서와 개인 검색 기록의 유지를 확인했다.
- 공개 Kubernetes 문서 8개와 AI 작성 smoke 질문 12개를 처리·평가했다. [실측·실패 분석](../experiments/README.md)을 참고한다. 사용자 검수 질문은 0개다.

## 원격·공개 상태

- [공개 저장소](https://github.com/lingter100/doctrail), [M1 PR](https://github.com/lingter100/doctrail/pull/1).
- GitHub API에서 커밋 작성자·커미터 계정이 모두 `lingter100`에 연결되는 것을 확인했다.
- main 필수 검사·선형 이력·강제 푸시/삭제 금지를 설정했다. 통합 규칙은 CONTRIBUTING을 따른다.
- GitHub Actions: 구현 커밋 `357be1a`의 backend/web 검사 모두 [원격 통과](https://github.com/lingter100/doctrail/actions/runs/38196203926). 이후 문서 커밋과 main 통합 상태는 GitHub의 해당 SHA 검사 결과를 기준으로 확인한다.
- 서비스는 로컬에서만 검증했다. 외부 서비스 배포·유료 API·클라우드·GPU 임대는 하지 않았다.

## M1 당시 한계

BM25의 한국어 bigram·어휘 일치는 의미와 답변 가능성을 판단하지 못한다. PDF OCR·원본 레이아웃 편집·파서 프로세스 격리는 없다. 파싱은 동기식이며 검색마다 허용된 코퍼스를 토큰화한다. 1,000문서 부하·GPU 실행·임베딩·리랭커·학습·생성 답변은 아직 검증하지 않았다. Starlette TestClient의 httpx 연동에 deprecation warning 1개가 있으며 현재 테스트는 통과한다.

## M1에서 정한 후속 작업

1. M2: 공개 자료 약 1,000문서를 검토하되 문서 계열·번역·버전 수량을 별도로 센다. 포함 정의·파싱 결함을 검수한다.
2. Train 문서 계열과 dev/test 계열을 먼저 분리하고 학습 질문과 평가 240질문 목표를 별도로 준비한다. AI 작성·자동 검수·사용자 검수 상태를 보존한다.
3. 실패 유형별 BM25 기준선을 고정한 뒤 임베딩·하이브리드·리랭킹을 비교한다. 로컬 GPU 메모리·시간을 확인한 뒤 학습 대상을 확정한다.

실행은 README와 [OPERATIONS](OPERATIONS.md), 이후 단계는 [roadmap](roadmap.md)을 따른다. 유료 사용 및 공개 서비스 배포는 미승인이다. M1 당시에는 자동화나 예약 실행을 설정하지 않았다.

2026-10-12 추가 위임에 따라 현재 채팅의 매시간 후속 실행을 ACTIVE로 등록했다. 예약 실행의 첫 성공은 아직 미확인이다. 실행 조건과 승인 경계는 [AUTONOMY](AUTONOMY.md)에 기록한다. 그 뒤 수행한 첫 M3 비교의 실제 결과를 아래에 기록한다.

## M2 실제 수행 결과

| 항목 | 확인한 결과 |
|---|---|
| 공개 코퍼스 | Kubernetes 고정 커밋, CC-BY-4.0. 2,287개 검사 목록 중 313개 적격 문서, 1,974개 제외 |
| 언어·분할 | EN 235 / KO 78. Train 180 / dev 65 / test 66 / smoke 2 문서 |
| 중복 처리 | canonical 계열 255개, 번역·정확 중복·유사 중복 연결 그룹 212개 |
| AI 질문 | 최초 240개. 검색 실행 전 다중 문서 조건이 불확실한 dev 1개를 별도 버전에서 제외 |
| 현재 활성 질문 | dev 79 / test 후보 160 = 239개. 사용자 검수 0개. Test 검색 평가는 실행하지 않음 |
| 데이터 검사 | 원문·정제 해시, 재정제, 중복 그룹 재계산, 분할, 정확한 근거 오프셋, 출처 검사 통과 |
| BM25 개발 평가 | 313문서·3,588청크. 양성 59질문 중 top-5 청크에 모든 필수 근거가 있는 질문 30개(50.85%) |
| 교차 언어 | 주석상 다른 언어의 근거가 필요한 23질문 중 완전 근거 적중 1개(4.35%) |
| 실제 HTTP | 임시 DB에 로그인·313문서 업로드. 32검색 성공/0실패, p50 255.991ms / p95 385.146ms |
| 검수 도구 | 질문·근거·주변 문맥·전체 코퍼스 탐색 HTML, 실제 검수 JSON 제출/검증. AI가 승인하지 않음 |

수집과 저장된 질문 초안의 재컴파일은 재현 가능하다. AI를 다시 호출해 동일 질문을 얻는 추론 재현은 아니다. 1,000문서 목표는 미달이며 파싱 결함을 통과시켜 수량을 늘리지 않았다. 범위·제외 원인·편향은 [DATA-CARD](DATA-CARD.md), 계약은 [M2-EVALUATION](M2-EVALUATION.md), 실제 수치·실패는 [실험 기록](../experiments/README.md)에 있다.

## M2 검증과 재현

```powershell
uv sync --frozen
uv run ruff check src tests scripts
uv run pytest -q
uv run python -m scripts.prepare_corpus replay
uv run python -m scripts.prepare_corpus verify
uv run python -m scripts.question_dataset --manifest data/manifests/kubernetes-v1.json --questions data/evaluation/m2-dev-v1.1.jsonl data/evaluation/m2-test-a.jsonl data/evaluation/m2-test-b.jsonl
cd web
npm run typecheck
npm run build
```

질문 초안 재컴파일·리비전까지 포함한 전체 명령은 [data/README](../data/README.md)에 있다. 최종 로컬 검증은 **93 tests passed**, Ruff·프런트엔드 타입 검사·production build 통과다. 313문서를 재현·재검증하고 최초 240질문과 활성 239질문의 해시·원문 span·분할 검사를 통과했다. Starlette TestClient 관련 deprecation warning 1개는 남아 있다. 두 측정 보고서의 모든 코드·잠금 파일·입력 해시가 기록된 Git 커밋의 blob과 일치함을 확인했다. 오프라인 평가 커밋은 `65338f2`, HTTP 성공 실행은 `76a20fc`다. `git_dirty=true`는 당시 미커밋 문서·결과가 있음을 그대로 드러낸다.

첫 HTTP 측정은 Windows 임시 DB 정리 시 파일 잠금 오류로 끝났다. 지연시간 결과가 보존되지 않아 인용하지 않는다. [실패 기록](../experiments/results/m2-http-attempt1-failed.json)을 남기고 제한된 정리 재시도를 추가했다. 두 번째 실행은 서버 종료·임시 DB 정리까지 성공했다. 잠금을 잡은 프로세스는 확인하지 못했다.

## M2 한계와 다음 작업

1. 사용자 검수 0개인 현재 점수는 AI 라벨에 대한 예비 회수 지표다. [검수 화면 생성 방법](../data/README.md#실제-사용자-검수)을 제공했다. 확정 정답률·실사용 품질로 말하지 않는다.
2. M3에서 동일 dev·코퍼스로 BM25→다국어 임베딩→혼합→리랭커를 비교한다. 현재 기준선을 유지하며 test 질문으로 튜닝하지 않는다.
3. 현재 청크에 전체 주석 span을 담을 수 없는 dev 질문 3개는 별도 청크 설정 실험으로 다룬다. 순위 모델과 청크 설정을 동시에 바꿔 개선 원인을 혼동하지 않는다.
4. 정제 범위를 넓히면 새 코퍼스 버전·분할 영향을 먼저 검토한다. 미해결 include 때문에 절차 문서가 많이 제외되어 참조 문서 편향이 있다.
5. 모델 라이선스·고정 리비전·로컬 6GB GPU 메모리·지연을 확인한 뒤 학습 대상을 결정한다. Train 문서는 예약만 했고 학습쌍·가중치는 아직 없다.

근거 없음 12질문에도 모두 결과를 반환했다. 답변 보류 기능은 없다. 공개 코퍼스 점수로 최신성 충돌·권한·수정·삭제의 의미적 QA를 검증하지 않았다. 해당 API 회귀 테스트와 검색 품질 평가는 별개다. 동기 파싱, 검색마다 재토큰화, OCR·파서 프로세스 격리 부재, 최고 메모리 사용량 미측정이 남았다. HTTP는 로컬 동시성 1·32건이고 캐시·전원·다른 부하는 통제하지 않았다. 공용 배포·부하 시험 수치가 아니다.

M2에서도 서비스 외부 배포·유료 API·GPU 임대는 하지 않았다. 면접에서 설명할 판단과 한계는 [M2-LEARNING](M2-LEARNING.md)을 참고한다.

## M2 원격 재현 확인

[M2 PR #2](https://github.com/lingter100/doctrail/pull/2)의 구현·결과 커밋 `21c6019`에서 backend/web 모두 [원격 CI 통과](https://github.com/lingter100/doctrail/actions/runs/38200944111)를 확인했다. 새 Linux 환경에서 93개 테스트와 빌드뿐 아니라 313문서의 실제 재수집·해시 검증, 질문 240개 재컴파일, 리비전·활성 239개 검증을 수행했다. 이후 이 확인 기록을 추가한 커밋도 필수 검사를 통과한 뒤 같은 사용자 계정으로 main에 fast-forward한다. 현재 통합 SHA의 최종 상태는 PR과 GitHub 검사에서 확인한다.

## M3 첫 비교 · 실제 로컬 GPU 실행

실행 커밋 `a8fb5a9`, 보고서 [m3-retrieval-dev-v1.json](../experiments/results/m3-retrieval-dev-v1.json), 완료 checkpoint [journal](../experiments/results/m3-retrieval-dev-v1.json.stages.jsonl). 코드·잠금 파일·입력 해시가 해당 Git blob과 일치하며 모델·코퍼스의 실행 전후 해시도 같았다. 질문·청크·라벨을 바꾸지 않았고 이전 BM25 top10 순위·점수·지표와 정확히 일치했다. Journal과 문서 파일 때문에 `git_dirty=true`를 그대로 기록했다.

| 방법 | 양성 59질문의 모든 필수 근거 @5 | 주석상 교차 언어 23질문 |
|---|---:|---:|
| BM25 | 30/59 (50.85%) | 1/23 |
| E5-small 다국어 임베딩 | 29/59 (49.15%) | 1/23 |
| BM25+E5 RRF | 27/59 (45.76%) | 0/23 |
| RRF+ BGE reranker | 36/59 (61.02%) | 6/23 |
| 후보 예산 진단 RRF 25+25 | 30/59 (50.85%) | 0/23 |

혼합+리랭커는 BM25 대비 7질문 개선·1질문 퇴보로 순증 6개다. 전체 원문 근거 회수의 예비 dev 비교이며 답변 정확도·사람 검수·최종 test 개선이 아니다. 단순 임베딩·혼합은 이 조건에서 개선되지 않았다. 리랭커 입력50 안에 모든 근거가 있는 질문도 37/59에 그쳐 후보 회수의 한계가 남았다. 질문별 원문·순위·후보 손실과 면접 설명은 [M3-ANALYSIS](M3-ANALYSIS.md)에 있다.

로컬 RTX 4050 6GB에서 E5 FP32·문서 batch8/query1, BGE FP16·batch1로 실제 실행했다. 문서 벡터 준비 45.08초. 따로 측정한 단계 시간의 합계 p50/p95는 BM25 424/516ms, dense 25/35ms, hybrid 457/542ms, hybrid+reranker 2,556/2,925ms다. 실제 HTTP나 모델 상주 서비스 응답 시간이 아니다. E5 38/3,588개 문서 청크, 리랭커 803/3,950쌍이 512토큰 한도를 넘어 잘렸다. 잘린 뒤 모델이 실제 본 span의 근거 회수는 아직 측정하지 않았다.

E5 문서 준비의 GPU allocator peak allocated/reserved는 794/1,808MiB, 리랭커 질의 단계는 1,123/1,138MiB였다. 리랭커 로드 중 CPU RSS 샘플 peak는 4,353MiB였다. 전체 장치 VRAM·전력·동시 모델 상주 서비스의 메모리 사용량으로 해석하지 않는다.

로컬 **129 tests passed**, Ruff, 프런트엔드 타입 검사·production build 통과. 기본 의존성만 있는 CI에서는 NumPy/Torch에 의존하는 검사 2개를 skip하며 GPU 모델 품질은 검증하지 않는다. 상세 명령은 [M3-RUNBOOK](M3-RUNBOOK.md). Starlette TestClient와 모델의 `torch_dtype` 인자 deprecation 경고가 남지만 실제 실행은 완료했다. 토큰 길이 진단에서 출력된 길이 경고는 실제 forward 전에 512로 자르는 경로와 구분한다.

다음 자동 실행에서는 실패 분석을 바탕으로 후보 회수·잘림의 후속 실험을 제한적으로 설계하고, 새 검색 방법을 명시적으로 선택할 수 있는 서비스 연결을 구현한다. 기본 BM25를 유지하며 ACL 선적용, 벡터의 revision·청크 해시, 수정·삭제·재처리·warm cache 회귀를 확인한다. 이것을 마치기 전 M3 전체 완료로 표시하지 않는다. Train 학습·생성 답변·유료 API·공개 서비스 배포는 하지 않았다.

## M3 첫 비교의 원격 코드·데이터 검사

[M3 PR #3](https://github.com/lingter100/doctrail/pull/3)의 구현·결과·분석 커밋 `0241e4b`에서 backend/web 모두 [원격 CI 통과](https://github.com/lingter100/doctrail/actions/runs/38203764861)를 확인했다. 기본 의존성 Linux 환경에서 **127 passed, 2 skipped**였고 Ruff·프런트엔드 타입 검사·빌드, 313문서 재수집·해시 검증, 최초 240/활성 239질문의 재컴파일·검증이 성공했다. 두 skip은 선택적 NumPy/Torch 검사이며 이 CI가 GPU 모델 추론이나 품질 결과를 재현한 것은 아니다. 실제 모델 실행은 위의 로컬 CUDA 기록으로 구분한다.

이 확인 기록을 추가한 뒤에도 실제 PR head의 필수 검사를 기다리고 사용자 작성자·커미터를 유지해 main에 통합한다. 현재 SHA의 최종 통합·검사 상태는 PR과 GitHub 검사에서 확인한다.

## Java 서비스 전환 · 로컬 검증

사용자의 Java 요청으로 `server/`에 실제 Java 서비스를 구현했다. Spring Boot MVC·JDBC·SQLite, PDFBox 파싱, Java BM25를 사용하며 계정·권한·문서 요청을 Python에 넘기는 구조가 아니다. 기본 실행 `./scripts/start.ps1`은 Java이며 이전 구현은 `-Backend Python`으로 남겼다. Java 기본 DB를 `var/doctrail-java.sqlite3`로 분리해 기존 DB를 자동으로 옮기거나 덮어쓰지 않는다. 실제 사용자 DB 이전은 수행하지 않았다.

- JDK 21.0.12.1, 체크섬 고정 Maven 3.9.16에서 Java 테스트 **20개 통과**. 로그인·세션 회전·만료·제한, 권한 선필터와 숨긴 문서의 점수 불변, 변경·삭제·재처리·피드백, 오류 롤백, 동시 검색, Unicode 원문 위치, PDF 경계를 검사했다.
- Python 회귀 **129개 통과**, Ruff, 프런트엔드 타입 검사·production build 통과. Python TestClient deprecation 경고는 남아 있다.
- [실제 Java HTTP 검증 보고서](../experiments/results/java-migration-v1.json): Python 합성 DB의 복사본으로 기존 계정·세션·문서 호환, Java 변경의 Python 역방향 읽기, Java 재시작 후 데이터 유지, 삭제 반영 등 **11개 검증 묶음** 통과. 이 숫자를 단위 테스트 11개나 사용자 검수로 소개하지 않는다.
- 같은 보고서에서 공개 문서 **313개를 Java API로 등록**, **3,588청크와 dev 79질문의 top10 문서·청크·점수·오프셋**이 기존 동결 Python BM25 결과와 일치했다. 검색 품질 개선이나 Java/Python 성능 우열을 측정한 실험이 아니다. Test 160질문은 검색 평가하지 않았다.
- 길이 헤더가 없는 JSON·multipart 초과 요청, 잘못된 HTTP target·쿠키, 운영 로그의 합성 비밀 표식 미포함을 실제 HTTP·소켓으로 확인했다. 정적 검토에서 발견한 Tomcat의 필터 이전 로거 노출을 설정에서 막았다.

첫 Java HTTP 검증은 Windows Oracle javapath 실행기가 남긴 자식 JVM의 로그 파일 잠금으로 정리 단계에서 실패했다. [실패 기록](../experiments/results/java-migration-attempt1-failed.json)을 보존하고 실제 JDK 실행 파일을 직접 시작·종료하도록 수정했다. 두 작업 전용 잔여 JVM과 검증용 임시 디렉터리는 정리했다. 이후 성공 실행은 종료·정리까지 포함한다.

명령은 아래와 같다. 공개 문서 원문이 없으면 [데이터 재현](../data/README.md)을 먼저 실행한다. 결과 파일은 기존 파일을 덮어쓰지 않는다.

```powershell
./server/mvnw.cmd -B -f server/pom.xml verify
uv run --group retrieval python -m scripts.verify_java_service --full-corpus --output .local/my-java-check.json
```

PDFBox와 pypdf의 일반적인 PDF 텍스트 출력은 동일하다고 주장하지 않는다. 저장된 예전 청크를 시작 시 자동 재처리하지 않는다. JAR의 UI 제공은 HTTP로 확인했지만 이번 전환에서 새 브라우저 시연이나 사용자 검수는 기록하지 않았다. 공개 서비스 배포·새 모델 추론·학습·생성 답변은 별도 후속 작업이다. 다음 자동 실행은 [M3 실패 분석](M3-ANALYSIS.md)에 따른 후보 진단과 Java 서비스의 모델 연결을 이어간다.

## Java 전환의 원격 검사

[PR #4](https://github.com/lingter100/doctrail/pull/4)의 코드·결과·문서 커밋 `09a25e9`에서 `java-service`·`backend`·`web` 모두 [원격 CI 통과](https://github.com/lingter100/doctrail/actions/runs/38206010313)를 확인했다. Linux/Temurin Java 21에서 Java 테스트·JAR 패키징과 실제 HTTP 11개 검증 묶음이 성공했다. 기존 Python 검사는 127 passed/2 skipped이며 공개 313문서 재현과 질문 검증도 통과했다. Java 전체 79질문 순위 대조는 위 로컬 보고서의 결과로 구분한다.

`main` 보호 규칙에 `java-service` 검사를 추가했고 기존 `backend`·`web`, strict, Actions 앱 ID 제한을 유지했다. 마지막 상태 기록 커밋도 필수 검사를 통과한 뒤 사용자 작성자·커미터를 유지하는 fast-forward로 통합한다. 최종 SHA의 통합·검사 상태는 PR에서 확인한다.

## 첫 heartbeat · 후보 선택과 토큰 근거 진단 완료

2026-10-12 05:06:57 UTC에 실제 예약 메시지를 받아 작업을 시작했다. 당시 main `7166c80`은 clean이고 실행 중인 서비스·모델 실험은 없었다. Java 전환과 기존 M3 전체 비교를 반복하지 않고 [사전 설계](M3-CANDIDATE-DESIGN.md)를 `2a6ffa8`에 고정한 뒤 구현을 `52549f7`에 커밋했다.

- [후보·tokenizer 진단](../experiments/results/m3-candidate-diagnostic-dev-v1.json): B/D 합집합의 완전 근거는 40/59, 기존 H50은 37/59. 양성 59문항에는 필수 근거 그룹 72개가 있다. 원래 HR top-5의 전체 근거 회수 36/59와 관련 근거 토큰 보존 36/59가 같았다. 엄격한 문자 offset 합집합은 잘림 전후 모두 27/59로, 이 차이를 잘림 실패 9개라고 읽으면 안 된다. AI 주석·토큰 위치의 자동 진단이며 의미 이해 측정은 아니다.
- [새 후보 선택 실측](../experiments/results/m3-candidates-dev-v1.json): 저장 B50·D50을 번갈아 읽어 중복 없이 50개를 선택했다. 모든 근거를 가진 후보는 **37/59 → 38/59**, 같은 BGE의 최종 top-5는 **36/59 → 37/59**. `m2-dev-017`을 회복했고 완전 근거 지표의 추가 퇴보는 없다. 기존 BM25 대비 8개 회복·1개 퇴보(`060`)로 순증7개다. 교차언어는 6/23 → 7/23이고 다중 문서는 1/7로 남았다. 회복 근거는 사전 고정한 B 우선 순서의 마지막 50번째 자리에 들어왔으므로 분기 순서를 바꿔도 유지되는 이득이라고 주장하지 않는다.
- 기존 다섯 방법의 79문항 결과·집계·paired 비교를 정확히 재계산한 뒤 새 정책을 실행했다. E5/BM25는 재추론하지 않았다. CUDA FP16·batch1로 3,950쌍을 실제 BGE 추론했고 전체 점수·토큰·입력 해시를 저장했다. 이전 top-10과 겹치는 778쌍의 raw 점수가 모두 같았다. 전체 과거 3,950쌍의 동등성을 확인한 것은 아니다.
- 새 BGE 구간만의 p50/p95는 **1,855.325/2,488.538ms**, 입력 잘림은 804/3,950쌍이었다. 이전 검색 시간을 더해 새 HTTP 응답 시간으로 표시하지 않는다. 단일 순회·캐시/전원/부하 미통제이므로 이전 실행보다 빨라졌다는 인과 결론도 내리지 않는다. OOM·묵시적 fallback·유료 API 사용은 없었다.
- 두 보고서 모두 실행 커밋 `52549f7`의 코드·설계·의존성 해시와 일치하고 완료 journal의 출력 hash가 실제 파일과 같다. 결과/journal 생성으로 `git_dirty=true`인 상태를 보존했다. 기존 M2/M3 결과·라벨·test 잠금은 변경하지 않았다.

실제 명령:

```powershell
uv run --locked --group retrieval --no-sync python -m scripts.analyze_candidates --tokenizer-visibility --output experiments/results/m3-candidate-diagnostic-dev-v1.json
uv run --locked --group retrieval --no-sync python -m scripts.evaluate_candidates --output experiments/results/m3-candidates-dev-v1.json
```

로컬 Python **177 passed**, Ruff, Java **20 tests**, 프런트엔드 타입 검사·production build가 통과했다. 새 synthetic 테스트 48개 중 2개는 검증한 로컬 tokenizer 파일을 사용한다. 원격 기본 CI는 GPU 모델을 실행하지 않으며 기존 tensor 검사와 이 tokenizer 검사 총4개를 선택적으로 skip한다. CI에 모델 없는 후보 진단과 기존 다섯 방법의 정확 재생을 추가했다. 테스트를 품질 향상의 증거로 대신하지 않고 위 실제 dev 비교를 별도로 남긴다.

사용자 검수0·test 검색 평가0·학습0·생성 답변0이다. 다음은 Java 서비스에 선택적 모델 추론을 연결하는 구조·토크나이저 호환을 검토하고 ACL 선필터, revision/cache, 수정·삭제 회귀를 검증하는 작업이다. 연구 측면에서는 합집합부터 누락된 근거와 3개 청크 경계 문제를 별도 실험으로 다룬다. 지금 dev에서 후보 정책을 계속 조정하지 않으며 Java 기본 검색은 BM25를 유지한다. [해석과 면접 설명](M3-CANDIDATE-ANALYSIS.md)을 참고한다.

구현 커밋 `52549f7`의 [원격 CI](https://github.com/lingter100/doctrail/actions/runs/38207832080)는 `java-service`·`backend`·`web` 모두 성공했다. Python173passed/4skipped, Java 테스트·실제 HTTP11묶음, 코퍼스 재현·활성 질문 검증과 모델 없는 후보 분석·기존 결과 정확 재생이 통과했다. 실제 GPU 실험은 위 로컬 기록으로 구분한다. 결과·분석 커밋도 실제 PR head에서 세 필수 검사를 통과한 뒤 사용자 작성자/커미터를 보존해 main에 통합하며 최종 상태는 PR에서 확인한다.

## React 전환 · 로컬 검증 완료

사용자의 React 전환 승인을 반영해 `feat/react-frontend`에서 구현했다. 기존 main `d25f623`은 시작 당시 clean이었다. 기존 CSS·한국어 UI, Java API와 Python 연구·동결 데이터는 보존했다. `App`, 계정·목록·검색/이력·원문·모달 컴포넌트, 상태 조정 hook, API·타입·원문 helper로 나눴다. [선택 이유](decisions/0003-react-frontend.md), [구조·실행법](FRONTEND.md)을 제공한다.

- React/React DOM **19.2.8**, Vite **7.3.7**, React 플러그인 **5.2.0**, Playwright **1.64.0**을 잠금 파일에 고정했다. 설치 시 npm audit 0 vulnerabilities를 확인했으며 포괄적인 보안 감사 완료를 뜻하지 않는다.
- 브라우저에서 실제 Java JAR과 production React 번들을 연결했다. 가입·로그인·로그아웃, MD/TXT/PDF 업로드, 검색·Unicode 원문 위치, HTML을 텍스트로 표시, 피드백·이력, 수정·삭제, 작업공간 생성·전환, 별도 회원 권한, 실패 PDF 재처리와 파일 크기 검사를 확인했다.
- 첫 15개 검사를 통과한 뒤 리뷰에서 발견한 초기 목록과 검색 경합, 역순 수정 응답 문제에 검사를 추가했다. 최종 **17 passed / 0 failed / 0 skipped**(브라우저 흐름14·순수 helper3), 자동 재시도0이다. 실제 서버 응답을 보류해 오래된 검색·상세·작업공간·모달 응답, 수정v2 뒤 v3, 수정 응답 뒤 삭제를 재현했다. 새 세션 뒤 이전401은 명시적인 합성 오류로 검사했다.
- 별도 Java 회귀 **20 tests**, 기존 Python **177 passed**, Ruff, 프런트엔드·검사 코드 타입 검사와 production build를 통과했다. Python GPU 실험이나 동결 평가를 반복한 것이 아니다. 기존 Python 참조 의존성에서 Starlette/httpx 사용 중단 예고 경고1건은 남아 있다.
- 최종 [자동 검사 기록](verification/react-frontend.json)에 실제 실행 UTC, 원본 보고서 hash, LF 정규화 소스 hash, 개별 검사명, 결과와 번들 크기를 저장했다. JS 번들233,162bytes/gzip73,096bytes는 빌드 산출물 크기이며 HTTP 지연이나 이전 화면 대비 속도 향상 수치가 아니다.
- [데스크톱](images/react-desktop.png)·[390px 모바일](images/react-mobile.png)을 AI가 확인했다. 합성 계정·문서·피드백이며 사용자 직접 시연이 아니다. 원문 태그가 그대로 보이는 화면은 HTML 실행 방지 검사 자료다.
- 각 실행은 새 합성 DB·임시 localhost 포트를 사용했다. JAR 화면과 현재 빌드 index 일치, 검사 종료 후 소유 JVM 종료를 확인했다. 기존 사용자 DB는 사용하지 않았다. 서비스 인터넷 공개·유료 자원 사용은 없다.

실행 순서는 `npm --prefix web run typecheck`, `npm --prefix web run build`, `./server/mvnw.cmd -B -q -f server/pom.xml verify`, `npm --prefix web run test:e2e`다. 마지막 상태 수정 후 프런트엔드를 다시 빌드하고 Java를 `-DskipTests package`로 재패키징해 최종17개를 수행했다. Java 소스는 이번 작업에서 변경하지 않았다. Python은 `uv run --locked --group retrieval --no-sync pytest -q`와 Ruff로 검증했다.

CI의 기존 필수 `java-service` 작업에 실제 Chromium 검사를 추가했다. 이 로컬 기록 작성 시점에는 새 PR의 원격 검사가 아직이며, 통과·통합은 별도 기록한다. 사용자 검수0·학습0·생성 답변0은 유지한다. 다음 개발은 Java 서비스의 선택적 검색 모델 연결과 ACL·문서 변경 반영 검증이며, 유료 사용·공개 서비스 배포 승인 조건은 유지한다.

## React 전환 · 원격 검사

구현 커밋 `c52cb39`의 [PR #6](https://github.com/lingter100/doctrail/pull/6)에서 `java-service`·`backend`·`web` 모두 [원격 CI 성공](https://github.com/lingter100/doctrail/actions/runs/38211284184)을 확인했다. Ubuntu/Temurin Java 21의 실제 JAR·Chromium 검사가 로컬과 동일한17개를 통과했다. 기존 Python 기본 CI는173passed/4skipped이며 모델 없는 동결 데이터·질문·후보 결과 재현과 Java HTTP11묶음도 통과했다. 로컬 GPU 의존성의 선택적 검사4개와 원격 skip을 구분한다.

이 기록 커밋 역시 실제 PR head에서 세 필수 검사를 통과한 뒤 사용자 작성자·커미터를 유지하는 fast-forward로 main에 통합한다. 최종 통합 SHA·상태는 PR을 기준으로 확인한다. 후속 실행은 React를 다시 전환하지 않고 Java의 검색 모델 연결 단계로 돌아간다.

## M3 · Java 선택적 검색 모델 연결 · 로컬 검증 완료

`feat/model-search`는 clean main `e7b8cf7`에서 시작했다. 기존 실행 중 작업이 없는 것을 확인했다. React 전환과 동결 M2/M3를 보존하고 Java 서비스에 `dense`, `hybrid`, `hybrid_rerank`를 추가했다. 기본 검색은 BM25다. Python은 고정 E5/BGE 추론만 처리하며 Java가 세션·ACL·문서·cosine/RRF·후보 선택·최종 순위·기록을 관리한다. [ADR](decisions/0004-model-serving.md), [실행·복구·면접 설명](MODEL-SERVING.md).

- Java는 현재 허용 청크만 모델에 보내고 추론 중 DB 트랜잭션을 해제한다. 완료 후 쓰기 트랜잭션에서 세션·membership·전체 가시 문서 스냅샷을 다시 확인한다. 수정·삭제·비공개 변경·새 문서·membership 삭제·로그아웃 경합에서 오래된 결과/이력을 거부했다.
- Worker는 고정 revision/hash의 E5 FP32, BGE CUDA FP16을 상주시킨다. 인증된 loopback만 사용하고 cache는 본문 hash·encoder 설정 기반의 메모리 LRU다. 원문/질문·사용자 세션·문서 목록을 cache에 보존하지 않는다. 두 모델의 기존 offline telemetry 누적 배열은 wrapper에서 비운다.
- React에서 검색 방식과 실제 결과 방법을 표시하고 이력 재검색도 원래 방법을 사용한다. Worker 미연결/실패 안내와 명시적인 BM25 선택을 제공한다. 모델 실패를 조용히 키워드 검색으로 바꾸지 않는다. 문서 탐색 디자인은 유지했다.

**실제 로컬 GPU·HTTP:** [보고서](../experiments/results/m3-model-service-v1.json)는 2026-10-12 06:35:30–06:35:56 UTC의 실제 실행이다. 합성 계정·문서로12개 운영 검사 묶음을 통과했고, 그 안의 실제 Chromium 모델 흐름6개에서 가입·업로드·세 모델 방식·원문·피드백·방법별 이력·390px 폭을 확인했다. 모든 모델 요청에서 실제 `cuda`, E5 `torch.float32`, BGE `torch.float16`을 확인했다. 원문 codepoint 위치·revision·private ACL·수정·동일 본문 재처리·삭제를 대조했고, 모델 중단 후503/no fallback/no history 및 기본 BM25 동작을 확인했다. 로그 표식·비밀번호·세션/worker token 미노출 검사도 통과했다.

HTTP 실측은 짧은 합성 문서2개·청크2개에서 방식당2회만 측정했다. E5 첫 요청498.692ms, 반복57.277ms; 재정렬 첫310.724ms, 반복115.201ms였다. 모델 상주 준비19,135.831ms는 요청 시간과 별개다. Passage cache가 빈 시점은 첫 E5뿐이며 이후 방식은 cache를 공유했다. 다른 BM25 브라우저 회귀 프로세스가 동시에 실행되었고, 전원/부하를 통제하지 않았다. 따라서 이 작은 값으로 전체 코퍼스 p95·서비스 SLO·이전 실험 대비 속도 향상·확정 품질을 주장하지 않는다. 별도 cache witness에서 최초 miss1 → 동일 본문 hit1 → 변경 본문 miss1을 실제 관측했다.

**자동 회귀:** Java **59 tests**, Python **220 passed**, Ruff, TypeScript 검사·production build, 실제 Java HTTP 기본/복사 DB 호환 **11묶음**, 모델 없는 Chromium **18 passed / 0 failed / 0 skipped / 0 retry**(브라우저15·helper3)를 통과했다. 첫 브라우저 실행의 disabled option 판정1건은 실제 DOM에 disabled가 있었으므로 속성 검사로 바꾼 뒤 다시 검증했다. Python Starlette/httpx 사용 중단 경고1건은 기존 상태로 남는다. 가벼운 원격 CI에는 모델 가중치를 설치하지 않으며 이 기록 작성 시점의 새 PR CI는 아직이다.

[통합 검증 기록](verification/model-service.json)에 개별 browser 검사, Java 집계, report hash와 LF 정규화 화면 source hash를 남겼다. 실제 모델 보고서의24개 source hash와 JAR hash가 실행 파일과 일치하고 동결 source/input/results가 base와 변경 없음을 확인했다. 모델 보고서는 실행 당시 미커밋 상태(`git_dirty=true`)를 정직하게 보존했다. [데스크톱](images/model-desktop.png)·[모바일](images/model-mobile.png)은 실제 합성 시연 자동 캡처이며, AI가 가독성·가로 넘침·근거 패널을 확인했다. 잠깐 보이는 업로드 알림도 실제 화면 상태다. 사용자 검수는 아니다. 검증 종료 후 소유한 Java/Python 프로세스가 남지 않은 것을 확인했다.

실행 명령:

```powershell
npm --prefix web run typecheck
npm --prefix web run build
./server/mvnw.cmd -B -q -f server/pom.xml verify
uv run --locked --group retrieval --no-sync pytest -q
uv run --locked --no-sync ruff check src tests scripts
npm --prefix web run test:e2e
uv run --locked --no-sync python -m scripts.verify_java_service --output .local/java-model-search-baseline.json
uv run --locked --group retrieval --no-sync python -m scripts.verify_model_service --device cuda --browser --output experiments/results/m3-model-service-v1.json
```

**다음 작업:** train 계열에서 후보 누락과 청크 경계 문제를 분리하고, train 전용 학습쌍·hard negative 품질을 검증한 뒤 임베딩/리랭커 학습 대상을 근거로 확정한다. 최종 test를 열거나 dev에서 계속 후보 정책을 바꾸지 않는다. 사용자 검수0·학습0·생성 답변0·공개 서비스 배포0이다. 모델 검색은 현재4,096청크 상한과 직렬 추론이므로 대규모 운영 검증이 남아 있다. 외관·사용성도 최종 기준에 포함하지만 로드맵 순서를 바꾸지 않는다.

## M3 모델 연결 · 원격 검사

구현 커밋 `1a7babb`의 [PR #7](https://github.com/lingter100/doctrail/pull/7)에서 `java-service`·`backend`·`web` 모두 성공했다. [실제 head push 검사](https://github.com/lingter100/doctrail/actions/runs/38213876293)와 [PR 검사](https://github.com/lingter100/doctrail/actions/runs/38213907700)를 확인했다. Ubuntu/Temurin Java21의 실제 HTTP11묶음과 Chromium18개, Python216passed/4skipped, 코퍼스·질문 재현과 모델 없는 후보 결과 재생이 통과했다. 원격은 GPU 모델을 실행하지 않았으며 로컬220개 검사·실제 CUDA 추론과 구분한다.

GitHub API에서 구현 커밋의 작성자와 커미터가 모두 `lingter100`임을 확인했다. 이 진행 기록도 별도 Conventional Commit으로 필수 CI를 통과한 뒤 사용자 계정을 유지하는 fast-forward로 main에 통합한다. 최종 통합 SHA·상태는 PR에서 확인한다. 다음 실행은 완료한 모델 연결을 반복하지 않고 train180문서·128계열의 검토와 학습 설계를 시작한다.

## M4 train 자료 pilot · 실제 수행

2026-10-12 06:49:58 UTC heartbeat에서 저장소 지침·상태·Git·프로세스를 확인하고 시작했다. Main `f01d8f3`와 PR#7 통합·필수 CI 성공을 확인했으며 실행 중 모델/학습 작업은 없었다. 새 `feat/train-data`에서 설계와 자료를 준비했다.

[M4 설계](M4-DESIGN.md)는 저장된 후보 실패21개/순위 실패1개 집계를 근거로 E5 후보 생성 모델을 조건부 학습 대상으로 정했다. BGE·청크·후보 정책은 고정한다. 이 단계는 원래 train180문서·128연결 그룹만 사용하고 dev/test 질문을 학습 설계에 다시 열지 않는다. 기존 로더가 전체 코퍼스 무결성을 확인한 후 train만 남기는 것과 평가 질문을 읽는 작업을 구분한다.

| 확인 항목 | 실제 결과 |
|---|---|
| Train 내부 분할 | Fit150문서/103계열/1,643청크, calibration30문서/25계열/553청크 |
| AI 작성 질문 | Fit64/16계열, calibration14/4계열; KO59·EN19, 주석상 한국어 질문/영어 근거51 |
| 자동 원문 검사 | 78/78 인용·Unicode 오프셋·동결 청크 전체 포함, 질문 자동 격리0 |
| 양성 후보 | 80쌍; 중첩 청크2개에 든 질문2개가 있어 독립 질문 수78과 다름 |
| 독립 AI 의미 검토 | 별도 역할이78개 모두 accept; 원문·질문·답안 직접성 확인, 사용자 검수0 |
| BM25 음성 후보 | 1,560개 중 알려진 양성/동계열/중복 위험328개 격리, 나머지1,232개 미검토 |
| 확인한 음성·학습 | 음성 라벨0, 학습0, 모든 후보 training eligibility=false |
| 데이터 부족 | Calibration 목표16 대비2개 부족; 링크 모음에 독립 사실을 억지로 추가하지 않음 |
| 재현 | 저장 초안에서4개 compiler 산출물 byte-for-byte replay와 독립 검토 영수증 replay 통과 |

원본 초안은 AI 작성·semantic pending 상태를 보존하고 독립 의미 검토를 별도 파일로 연결했다. 검수자는 작성자와 다르며, 질문 canonical hash·원문 hash·author pack hash가 바뀌면 영수증 검증이 실패한다. 자동 검증은 의미적 진실이나 사람 승인을 대신하지 않는다. 전체 코퍼스의 대체 정답 관련성은 아직 확인하지 않았다.

계획·작성 지침을 `611a66a`에 고정했고 최종 초안 전에 public selection을 기록했다. 초기 pack의 계획 바인딩 및 Windows CRLF/Git LF 해시 차이는 실제 컴파일 전에 해결했다. V1/V3의 전체 문서·허용 ID 일치를 부모와 작성자가 확인했고, 최종 V3 pack 해시만 최종 행에 연결했다. 오래된 inventory/pack은 로컬에 보존하며 게시 자료에는 포함하지 않는다. 변경 이력은 [생성 영수증](../data/training/generation/receipt-v1.json)에 남겼다.

[데이터·재현 안내](../data/training/README.md), [자동 보고서](../data/training/m4-pilot-v1/report.json), [별도 AI 검토 보고서](../data/training/reviews/m4-semantic-report-v1.json)를 참조한다. Compiler 보고서는 의미 검토 전 snapshot이므로 후속 검토 결과를 소급 반영하지 않는다.

실행한 검증은 Java59개, React 타입 검사·production build, 실제 Java 기반 Chromium18개, Python 전체264개와 Ruff다. Python은 기존 Starlette/httpx 사용 중단 경고1건이 있다. 신규 데이터/영수증 검사44개를 포함하며 원격 PR CI 결과는 별도 통합 기록에서 확정한다. 기존 Java/M3 모델 동작은 변경하지 않았으므로 CUDA·동결 dev 비교를 다시 실행하지 않았다. 서비스 회귀 통과와 모델 품질은 별개다.

주요 실행 명령은 다음과 같다. 입력 생성·replay 전체 명령은 데이터 안내에 있다.

```powershell
uv run --locked --no-sync ruff check src tests scripts
uv run --locked --no-sync pytest -q
npm --prefix web run typecheck
npm --prefix web run build
./server/mvnw.cmd -B -q -f server/pom.xml verify
npm --prefix web run test:e2e
```

다음은 기존 pilot을 덮어쓰지 않는 보정 문서 추가 선택, 명시적 음성 검토, E5 tokenizer 근거 보존과 질문당 단일 양성 선택 규칙 동결이다. 조건 통과 후에만 실제1 optimizer step 자원 probe와 제한 학습·동일 calibration 비교를 진행한다. 유료 자원·공개 서비스 배포·최종 test 개방은 수행하지 않았다. UI 완성도는 기존 최종 기준을 유지한다.

## M4 자료 pilot · 원격 검사

구현 커밋 `a29618e`의 [head push 검사](https://github.com/lingter100/doctrail/actions/runs/38216813028)에서 `java-service`·`backend`·`web`이 모두 성공했다. Ubuntu의 Python260passed/4skipped, Java HTTP11묶음, Chromium18개, frozen M2/M3 검사와 새 train 자료·독립 AI 검토 영수증의 byte-for-byte replay가 통과했다. 원격에는 heavy 모델 의존성이 없어4개를 건너뛰었으며 로컬264개 통과와 구분한다. 학습·모델 추론은 이 CI에서 수행하지 않았다.

[PR #8](https://github.com/lingter100/doctrail/pull/8)의 마지막 head에 대한 필수 검사를 확인한 뒤 main에 fast-forward로 통합한다. GitHub API에서 구현 커밋의 author와 committer가 모두 `lingter100` 계정에 연결됨을 확인했다. 최종 통합 SHA·상태는 PR 기록을 기준으로 확인한다. 다음 실행은 이미 끝난 pilot을 재작성하지 않고 보정 질문 보완·음성 검수·토큰 보존 조건을 진행한다.

후속 검수 범위 확인: 격리 후 미검토 후보는 fit 질문마다6~20개, calibration 질문마다11~20개다. 후보 개수가 충분하다는 사실이 질문당 필요한2개의 실제 음성이 존재한다는 뜻은 아니다. 검토에서 대체 정답·모호성을 찾으면 그대로 제외 사유를 남긴다.


## M4 준비 v1 · 실제 실패와 보완

PR #8은 `42e682d`로 main 통합됐고 [main CI](https://github.com/lingter100/doctrail/actions/runs/38217802771)는 성공했다. 다음 작업 브랜치는 `feat/train-readiness`다.

새 선택 계획을 먼저 커밋한 뒤 기존 calibration과 다른 계열의 문서1개에서 질문2개를 추가하고 독립 AI가 수락했다. 기존78개를 보존한 `m4-pilot-v2`는 fit64·calibration16, 양성82쌍이며 구조·출처·언어·중복 조건을 통과했다. 질문의 사용자 검수는0이다.

독립 AI가 검색 순서로 고정한256후보를 질문·모든 양성 문맥과 함께 읽어 negative244/relevant4/ambiguous8로 판정했다. `m4-fit-048`은 대체 정답·불확실한 관련 예시만 있어 음성0개다. 전체80질문의 query와 선택 양성 인용 토큰은 보존됐고, 고정 음성은12질문에서 잘렸다. v1 `data_ready=false` 및 probe·학습 미실행을 실제 보고서에 보존했다. 관련 근거와 설명은 [M4 준비 결과](M4-READINESS-RESULTS.md)를 따른다.

후속 v2는 v1 코드·결과를 바꾸지 않고 같은 질문의 다음 후보4개와 이미 고정한 음성의 실제 잘린 입력만 검토한다. 새로운 학습 결과나 모델 개선을 뜻하지 않는다. 최종 통합 검증·원격 CI와 후속 결과는 아래에 추가한다.


## M4 준비 v2 통과와 첫 GPU probe

80개 질문·원래 양성·63개 기존 음성쌍은 유지했다. fit048의 추가4후보 검토는 negative3/ambiguous1이며 원래 rank6·7을 선택했다. 선택 음성128쌍/93개 청크를 실제 CPU tokenizer로 처리했고12개 잘린 쌍도 별도 AI가 모두 negative로 판단했다. 실제 토큰 재실행의 byte 일치와 v1·v2 저장 증거 replay를 확인해 v2 `data_ready=true`가 됐다. v1은 여전히 false다.

첫 실행은 `.local` 경로 검사 오류로 GPU 로드 전에 실패했고, 원인을 수정한 v1.1 계획을 따로 동결했다. 이어 실제 GPU probe는 finite forward4회·backward4회 뒤 gradient norm 검사에서 중단됐다. 저장 report는 generic runtime failure, 구체적인 비유한 norm은 부모가 관측한 도구 traceback 근거다. optimizer 호출0·가중치 갱신0·본 학습0이다. peak allocated1,523.46MiB/reserved1,982MiB였으나 AdamW moments 생성 전이므로 전체 학습 메모리 통과가 아니다.

원본 report·progress와 사전 검사 실패를 `experiments/results/m4-e5-*`에 보존했다. 초기 GradScaler 배율65536을1024로 낮춘 단일 후속 검사를 새 계약으로 준비하며, 원인을 확정하거나 같은 실패를 무기록 재시도하지 않는다. 데이터·seed·FP16·모델·목적함수·학습 횟수·메모리 상한은 유지한다.

## M4 학습·calibration 실제 완료

후속 probe는 같은 네 손실값으로 유한 norm56.11948·실제1회 optimizer 갱신을 통과했다. 원래 base에서 새로 시작한 본 학습은64질문×2epoch·16회 갱신을 마쳤다. 실제 학습 실행43.71초, peak allocated2789.22MiB/reserved3414MiB, 마지막 저장본 하나를 기록했다. 유료 API 요청0이며 전력·금액은 미측정이다.

공개 보고서 경로 사전 검사 오류는 추론 전에 발견해 기록·수정했다. 새 평가 계획 v1.1로 원래 train180문서·2196청크/내부 calibration16질문을 실제 비교했다. @50 13→15, @5 8→11, 근거 MRR@10 0.30156→0.60129였다. @5 회복6·퇴보3을 모두 기록했고016은 계속 후보 누락이다. 보고서·journal은 실제 원본과 바이트가 같고 저장 순위·지표·판정 replay가 통과했다. [분석](M4-CALIBRATION-ANALYSIS.md), [재현](M4-RUNBOOK.md)을 참고한다.

최종 로컬 Python449개·Ruff 통과, 기존 Starlette deprecation warning1개가 남는다. 같은 작업 묶음에서 Java59개(실패0), React 타입 검사·production build, 실제 Java 대상 Chromium18개도 통과했다. 서비스 코드는 이번 연구 작업에서 바뀌지 않았으며 동결 M3/dev나 Java CUDA 동작을 불필요하게 다시 실행하지 않았다. 원격 CI·통합 상태는 아래 또는 PR의 최종 head를 기준으로 확인한다.

다음 작업: 학습 저장본·청크·평가 정책을 먼저 동결한 한 번의 main-dev 비교를 설계하고 기존 결과 대비 회복·퇴보를 확인한다. 지금 얻은 calibration 결과로 추가 학습 설정을 탐색하지 않는다. 그 뒤 근거 기반 답변·보류, 운영 검증·화면 완성도·포트폴리오를 이어간다. 최종 test·유료 사용·공개 서비스 배포·사용자 검수는 아직 수행하지 않았다.

운영 실행 전 검증: 전체 Python513개·Java82개·프런트 타입/production build·Ruff, 실제 Java HTTP11묶음, Playwright22개(Chromium19·순수 helper3)가 통과했다. 최초 전체 브라우저 실행은20통과/2실패였다. 검사 수 증가로 공유 서버/IP의 정상 인증 제한20회에 걸렸으므로, 보안 제한을 바꾸지 않고 검사 파일마다 Java/DB를 분리했다. 모든22개 통과와 선택 파일+grep1개 통과, 소유 JVM 종료를 확인했다. 최초 실패 증거는 `.local/web-e2e-iR3MHQ`, 성공은 `.local/web-e2e-batch-xPAxoJ`, 선택 실행은 `.local/web-e2e-batch-lK1lNC`에 보존한다. 기존 main-dev의 모델 없는 순위/판정 재생과 terminal/base/BGE 파일 사전 검증도 통과했다. 아직 이 기록은 실제 terminal GPU HTTP 성공을 주장하지 않는다.

## M4 terminal 운영 · 원격 검사와 통합 경로

[PR #11](https://github.com/lingter100/doctrail/pull/11)의 구현·결과 커밋6974cf1에 대한 [head push CI](https://github.com/lingter100/doctrail/actions/runs/38331783889)는 java-service/backend/web 모두 성공했다. 원격 Python493passed/20skipped(선택 모델 의존성 없음), 프런트 회귀22개(Chromium19·순수 helper3), 실제 Java HTTP11묶음, 동결 코퍼스·학습 준비 및 main-dev 저장 결과 재생을 확인했다. 로컬513개·실제 CUDA 운영16묶음과 원격 모델 미실행을 구분한다.

GitHub API에서61285dd와6974cf1의 author/committer가 모두 lingter100에 연결됨을 확인했다. 독립 AI 결과 감사는 report/journal 원본 일치, source42개와 실행 커밋 일치, 운영/품질 주장 구분을 확인했다. 재현 예시는 새 출력 이름으로 보정하고 Playwright22개 중 순수 helper3개를 명시했다. 최종 문서 head도 필수 CI 후 fast-forward로 통합하며, 정확한 최종 SHA·CI·병합 상태는 PR 기록을 따른다. 모델 실행은 반복하지 않는다.

PR 자동 검토 후 잠금 cleanup을 보완했다. 기존 실행 도중 lock이 외부에서 교체되는 경우 소유권 token과 file identity가 다른 파일을 삭제하지 않으며, 누락된 lock이 원래 예외를 가리지 않는다. 추가5개를 포함한 전체 Python518passed·Ruff가 통과했다. 기존 Java/React/모델은 바뀌지 않았으므로 GPU 실측은 반복하지 않는다. 실제 운영 보고서는61285dd 바이트를 보존한다. main의 미해결 검토 보호로 첫 push가 거부됐으며 보호 규칙을 해제하지 않고 수정·자동 검토 항목 해결·새 head 필수 CI 후 통합한다. 최신 원격 검사·최종 병합 상태는 PR#11을 기준으로 확인한다.
