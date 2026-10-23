# 근거 연결 요약 후보의 1회 개발 실행 계약

2026-10-22. `grounded-summary-v1`의 실제 개발 비교를 위한 사전 계약이다. 문서 작성은 실행 권한이 아니다. 공식 cal/val/test, 이미 소비된 개발 실행과 기존 판단은 재실행·재채점하지 않는다. 기존 합성 개발 자료를 재사용하는 노출된 개발 비교이며 독립 일반화 평가나 사용자 검수가 아니다.

## 결정과 재사용 경계

- 기존 `.local/service-rag-batch-development-v1/development-runner-v3.py`를 **원본 보존 후 최소 수정하여 재사용**한다. 현재 26,374B/SHA `efe7e9e6260b3970d27ce2e9ac4baab835f802a9fc5e39c7f8a7636b7e366fbe`다. cleanup26 회귀와 이전 실패·receipt·seal은 보존한다. 새 복제 runner, 별도 서버, prepare/probe/audit 체계는 만들지 않는다.
- 그대로 실행할 수는 없다. `verify_runtime`은 과거 code10개와 harness2개를 고정하고(68–91행), `run_development`는 `run-v3`만 허용하며(253행), `start_services`에는 `analysis_policy="batch-v2"`만 전달한다(310–313행). 따라서 새 assembly를 지정하지 않으면 legacy가 선택된다. 원래 v3에 실제 실행을 먼저 해보는 예행은 하지 않는다.
- 기존 `development-browser-v2.mjs`도 흐름을 재사용한다. 현재 36,892B/SHA `312bdae3dee6bea14aab2b0d58b9733cc9d29ce30f49618463b79b27a04267a5`다. 전체 분석을 복사해 항목 상태만 수정하는 기존 편집/링크 경로는 v2와 연결 가능하지만, 현재 349–364행은 모델 identity와 ready만 확인하므로 새 요약 형식·표시·근거 이동 확인을 작게 보강한다. 이는 코드 판단이며 실제 native 호환 통과 주장이 아니다.
- 후속 구현 범위는 이 기존 harness2개와 NEW generic 회귀1개(`.local/service-rag-batch-development-v1/test_grounded_harness.py`)다. 수정 전 harness2 원본·해시·기존 회귀를 별도 보존하고 이전 실행 binding은 그 원본으로 해석되도록 보존 위치를 기록한다. 기존 제품·frozen77·closed run·과거 runtime-binding 파일은 수정하지 않는다.

## 새 후보의 고정 입력과 실행 위치

- 후보는 `analysis_policy=batch-v2`, `extraction_assembly=grounded-summary-v1`, 개발 실행 이름은 `grounded-summary-development-v1`이다. CLI의 명시 opt-in과 부모가 지정한 binding 파일/SHA 외에 모델·정책·fixture endpoint override를 추가하지 않는다. assembly를 service 인자, browser config, 실행 summary에 명시하고 누락·다른 값은 native 시작 전에 거부한다. 실제 선택과 정확한 summary metadata는 기존 launcher health 검사로 확인한다.
- 유일한 새 출력 위치는 `.local/service-rag-batch-development-v1/run-grounded-summary-v1/`로 고정한다. 디렉터리의 배타적 생성과 consumed reservation 이후 첫 실패도 소비된 실행이다. 경로가 이미 있으면 시작하지 않는다. 기존 `run-v1`, `run-v2`, `run-v3`를 새 후보 결과로 사용하거나 지우지 않는다.
- 새 runtime binding은 같은 base의 `runtime-bindings-grounded-summary-v1.json` 한 개다. 기존 binding 형식을 확장해 후보·고정 출력 경로·원래 입력 index·정확한 source commit/CI receipt·runtime code·harness2·JAR/UI를 묶는다. 기존 `runtime-bindings-v2.json`은 그대로 보존한다. 숫자10 검사를 늘리는 대신 중복 없는 **정확한 실행 원본 경로 집합**과 각 bytes/SHA를 검사한다.
- 실행 원본 집합은 현재 `scripts.run_meeting_rag_acceptance.CODE`의 실행 파일(검사 파일 제외), 실제 launcher/import 의존성(새 summary, coverage, batch, native/answer/Java resolver/CPU retrieval 접점 포함), Java 서비스 및 React 실행 원본·실행 설정으로 고정한다. 코드에 없는 `launcher.CORE_CODE`를 가정하지 않는다. 테스트는 검사 증거로 분리하고 런타임 파일 수를 채우는 데 쓰지 않는다. 전체 frozen77은 기존 목록/해시를 재사용하며 새 freeze 체계를 복제하지 않는다.
- JAR와 UI 파일은 현재 소스에 대응하는 로컬 산출물 bytes/SHA, JAR 안 UI의 일치를 고정한다. 이를 CI에서 내려받은 동일 binary라고 하지 않는다. 부모가 정확한 source CI 결과와 commit을 확인하고 CI receipt를 binding에 고정한다. runner는 그 파일과 runtime/harness/binary/input binding을 시작 전·종료 후 확인한다.
- 원래 index SHA `fae0db8b6c03cc591da5dda7fb9b81a9e046132d956cfeb0ee764d2d6785ca32`와 기존16개 입력 bytes를 그대로 유지한다. 일반문서2+회의4, 질문6의 원래 순서·원문·기대 의미·기존 source-only annotation·actor 동작 조건을 바꾸지 않는다. 새 corpus나 새 정답은 만들지 않으며 기대 답/annotation/이전 labels를 모델 문맥에 넣지 않는다.

## 한 번의 실제 서비스 흐름

- 기존 real factory로 Java→CPU 검색→Python worker→동일 설치 Qwen/GPU28/native 인스턴스→React를 사용한다. 합성 transport·모델 identity 대체·fixture 응답은 금지한다. 실제 launcher 인자, health의 후보/모델/두 prompt·grammar SHA, JAR/UI binding으로 이를 확인한다. Java health는 HTTP 준비만 의미하며 실제 효과는 `/meetings` 응답과 worker 관측으로 확인한다.
- startup120초 + active1500초 + 전체 cleanup5초, 최종 증거 쓰기/해시/seal까지 전체1625초를 유지한다. 동기 시작 구간은 hard preemption 보장이 아닌 수용 시간 검사다. 분석은 각 요청의 같은120초 안에서 전체 입력 admission·batch-v2 분류·요약 생성 최대1회·검토 최대1회·조립·관측을 수행한다. 재생성/repair/fallback/자동 재분석은0이다. 생성768/검토128 출력 cap, 각 실제 template 포함 입력4096, EOS, 기존 answer90초·설정은 그대로다.
- 자료6건을 각1회 업로드하고 회의4건의 자동 분석 종료를 관찰한다. 첫 실패면 뒤 단계는 미실행으로 남긴다. 성공한 분석은 현재 source revision, 저장된 `ai_analysis.summary_version=2`, claims/파생 summary/evidence와 outer `summary_review` 계약을 확인한다. 요약의 자기검토 표시는 독립 품질 합격이 아니다.
- companion의 새 확인은 기존 분석 ready 직후에만 넣는다. `.summary-section [data-summary-claim]`의 개수·문장 text와 각 근거 버튼을 실제 저장 응답에 대조한다. 모든 근거를 열어 현재 document/revision의 전체 원문, 정확한 quote와 code-point 시작/끝 위치·닫기 후 초점을 확인한다. 이미 있는 화면 회귀의 선택자/위치 확인을 재사용하고 의미를 평가하는 문구 규칙을 추가하지 않는다. 조회·근거 이동은 GET/UI 동작이며 새 모델 호출을 만들지 않는다.
- 이어 기존 ACL 확인, 질문6의 UI 제출 각1회와 모든 답변 인용 이동, 원래 합성 actor 편집/링크를 그대로 수행한다. 별도 search 예행이나 oracle context 주입은 없다. 편집은 실제 추출된 결정을 확인한 뒤 항목 상태만 변경하며 summary claims와 저장된 AI 원본은 그대로 보존한다. 실제 결정이 없거나 모호하면 기존 prerequisite failure를 남기고 정답 항목을 만들어 넣지 않는다. 새 요약 성공으로 분류/링크 실패를 덮지 않는다.
- 전 단계의 첫 고정 실패코드·시점·현재 대상·미실행 상태를 보존한다. startup/입력 초과/metadata 충돌/schema/EOS/검토 거부/시간 초과/관측 저장/cleanup 실패 모두 실패다. 수정이나 재호출로 이 실행을 이어붙이지 않는다. 원문 축약, 선택적 index, 상한·시간 증가, 검토 생략을 허용하지 않는다.

## 관측과 종료 판정

- 기존 `Evidence`/HTTP hook으로 실제 전체 request·선정 context·분류 batch IDs·생성/검토 payload와 응답·token/template/EOS·단계·첫 실패를 private raw에 보존한다. 성공한 회의마다 전체 units의 순서/coverage, source_parts+gaps의 연결이 저장된 전체 content와 같은지, 생성문→검토의 unit ID 연결→Java 저장 claims가 같은지 기계 대조한다. JSON/원문/자기검토 값은 부모에게 보내지 않는다.
- API 분석4회와 실제 native completion 수를 구분한다. 성공한 각 회의의 completion은 실제 분류 batch 수 + 생성1 + 검토1이어야 한다. 단계 event를 completion으로 중복 합산하지 않고 실제 transport attempt/response로 셈한다. tokenization/template 재호출·실패 호출도 별도로 기록한다. 실패 때 추가 completion이 없었는지 확인하며 assembly 진단을 request 성공으로 해석하지 않는다.
- 기존 v3의 PID+creation identity, prior browser/native cleanup 차감, 남은 같은 절대5초 내 absence 관찰, query 비용 포함, unknown 실패, 앞선 cleanup 실패의 sticky 상태, null/unset에만 첫 실패 설정을 유지한다. 관측을 위해 추가 kill이나 새 wait 예산을 만들지 않는다.
- Node 최종 exit, 실제 CLI exit0, cleanup/소유 absence, 입력 불변, 마지막 seal 이후1625초 검사와 정확 receipt/index SHA, failure marker 부재를 모두 요구한다. provisional summary나 `eligible_candidate`만으로 통과하지 않는다. 기존 실패 기록은 이후 PID 소멸이나 좋은 답변으로 성공 처리하지 않는다. 실행 수용과 요약 품질은 별개다.

## 독립 의미 판단과 최단 진행 순서

1. 부모는 제품 source `17a5dd60d367e72249d3d2dab413b87eaffbda90`의 push39749052460/PR39749062768 필수3 job 모두 성공을 확인했다. 공개 CI receipt SHA는 `e852d3795e4c56164fab0fa91577b1c5e7f0a6d7f98f73dd4baf5c0b69f39743`이다. 이 계약과 CI 기록을 함께 커밋한 뒤 최소 harness 수정을 배정할 수 있다. 실행에 영향을 주는 제품 수정이 생길 때만 그 수정의 정확한 source CI를 다시 확인한다.
2. 원본 보존 후 harness2의 위 최소 delta와 generic 회귀1개를 구현·검사하고 독립 읽기 검토한다. 회귀는 잘못된 assembly/누락·중복·변경 binding/기존 경로 재사용의 시작 전 거부, factory 실제 인자, v2 저장·투영과 반복 인용 좌표·편집 보존, 실패 뒤 completion0을 확인한다. 기존 cleanup26 및 finalization/first-failure 경계도 유지한다. 가짜 clock/HTTP/process/DOM 자료만 쓰고 모델/실제 개발 자료 예행은 하지 않는다. 정확한 runtime 의존 경로 열거는 구현자가 실제 imports와 기존 binding 목록으로 확정하고 검토받는다.
3. 부모가 최종 harness/runtime/JAR/UI/원래 입력 bindings를 고정하고 그 hash와 검토 결과를 실행 전 기록한다. private 자료를 공개하지 않으며 기존 계약/CI 기록과 이 실행의 binding이 연결되어야 한다. 문서·메타데이터만을 위한 추가 CI 연쇄는 실행 조건으로 만들지 않는다. 기존 실행 담당을 재사용하고 새 독립 `grounded_summary_judge`(실제 Astra xhigh)의 역할·노출·입력 금지를 기존 방식으로 기록한다. 새 등록 framework나 평가 기준은 만들지 않는다.
4. 부모의 **별도 명시 once 배정** 후 기존 실행 담당만 새 폴더에서 수행한다. 그동안 필요한 Java/GPU 슬롯과 실행 소스·산출물을 고정한다. 실패 여부와 관계없이 다시 실행하지 않고 원본/종료/안전 집계를 반환한다. 이번 설계는 그 배정이 아니다.
5. 독립 판단 담당은 기존 source-only locked 기준과 원문 binding을 먼저 확인·잠근다. 새 기준이나 문구별 통과 조건을 만들지 않는다. custodial packet은 대상/source revision과 새 요약 주장·연결 citation만 담아 기존 원문에 결속하고, labels·items·이전 출력·자기검토/성능·오류 진단은 제외한다. 처음에는 지원성과 핵심 충분성을 각각 판단·잠근 뒤 자기검토와 지연/실패를 공개한다. 이미 알고 있는 과거 결과/기준 노출은 그대로 기록한다.
6. 검토가 거부한 경우에도 기계적으로 유효한 생성 draft가 있다면 담당자가 기존 parser/정확 source-span mapping으로 새 private diagnostic packet에 분리할 수 있다. 검토 결과를 숨긴 같은 판단을 먼저 잠가 잘못된 수용/거부를 비교하며, 저장 성공이나 운영 통과로 간주하지 않는다. draft가 없거나 기계 계약을 위반하면 의미 판단 미실행으로 남긴다. 새 extraction/답변 판단은 각각 별도 잠금이며 원래4개 기준·기존 질문 기대를 수정하지 않는다.

완료 보고는 실행·저장/UI 연결, 주장 지원성, 핵심 충분성, 동일 모델 검토의 일치/오류, 분류의 남은 오류, 지연·입력 거부·cleanup을 분리한다. 기존 분류10오류/작업 확약3의 해결을 요약 성과로 주장하지 않는다. 전체 원문4096 또는 shared120을 넘거나 충분성에 실패하면 해당 후보 결과를 그대로 기록한다. 모델 자기검토·합성 회귀·개발4건의 개선을 공식 품질 수용/사용자 검수/배포로 확대하지 않는다.

읽기 근거: `AGENTS.md`, `docs/STATUS.md`, 기존 grounded 설계 SHA `ca04c0634bbb71ee9a07667f60837e28bc4e8efdc8ddda28a649067913486aed`, 위 v3/companion의 generic 제어 경로, 기존 runtime-binding/preparation의 해시 metadata, 제품 Python/Java/React 계약과 generic 검사다. 원문·질문·기대 답·actual labels·private judgment·raw run은 열지 않았다. generic 검색 출력에 기존 합성 actor literal 일부가 우연히 포함된 노출을 부모에게 알렸고 이후 그 구간은 제외했다. 설계자는 이전 노출 및 final judge 제외를 유지한다. 이번 변경은 이 문서1개이며 제품/자료 수정·검사/모델/tokenizer/Java/browser/Git 실행은0이다.
