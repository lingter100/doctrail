# 실제 서비스 RAG 단일 실행 경로

2026-10-20. 이 문서는 **설계**다. 이번 작성에서 실행 코드·자료·문항을 만들거나 서버·브라우저·tokenizer·모델·검사·네트워크·Git을 실행하지 않았다. 후속 구현·검토·코드 CI와 별도 실행 등록이 끝나기 전 모델 호출 권한은 없다.

기준은 `MEETINGS-RAG-ACCEPTANCE-PLAN.md`의 서비스 수명 정정과 `meetings-service-rag-next-stage-registration-v3.json`의 일반 계약이다. 원문 전체, source/item 독립 검토와 freeze, cal6/validation8, 자연어 완전답변·복수 문서·충돌·제안과 확정·정확한 보류·권한·revision·삭제 요구를 유지한다. C7 및 닫힌 source 시도를 재개하거나 성공으로 바꾸지 않는다.

## 구현은 실행기 하나와 브라우저 연결로 제한한다

| 후속 구현 제안 | 책임 |
| --- | --- |
| NEW `scripts/run_meeting_rag_acceptance.py` | 한 split의 입력 binding, 단일 사용 예약, 기존 `start_services` 호출, 증거 sink, 호출 수·시간·소유 자원 관리, 안전 요약. 실제 실행 옵션이 없으면 native를 시작하지 않는다. |
| NEW `web/scripts/run-meeting-rag-acceptance.mjs` | 이미 시작된 loopback Java URL에 기존 Node Playwright로 연결하는 얇은 browser companion. 서비스·fixture를 시작하거나 답변을 재전송하지 않는다. |
| NEW `tests/test_run_meeting_rag_acceptance.py` | fake clock/process/browser events와 합성 요청으로 실행 순서·상한·정리·증거 실패를 검사한다. 실제 split 파일을 import/열람하지 않는다. |
| 기존 비동결 `serve_meeting_rag_service.py`, `serve_meeting_service_rag.py`, `meeting_service_rag.py` | 기본 `None`인 실행 전용 observer를 전달하는 최소 연결. 기본 서비스에는 원문 저장이 없다. 관측 callback은 응답·문맥·정책을 바꾸지 못한다. |

위 NEW3/기존3은 부모의 **후속 구현 배정 제안**이며 현재 수정 권한이 아니다. Java·React·동결77·추출/답변 decoder·native launcher를 변경하지 않는다. 새로운 prepare/probe/audit 체계, DB 스키마, HTTP proxy, 범용 관측 framework, 복사한 모델 정책을 만들지 않는다.

Python Playwright를 새로 설치하지 않고 이미 있는 `web`의 Node Playwright/Chromium을 쓴다. `web/scripts/test-java.mjs`는 합성 DB와 generation fixture/disabled 설정을 선택하므로 공식 실행에서는 호출하지 않는다. `support.ts`의 조작 방식과 `verify-model-browser.mjs`의 기존 서비스 연결 방식을 참고하되 고정 답변·합성 문서·`route.fulfill`·`delayResponse`는 가져오지 않는다. 기존 45초 test runner를 늘려 평가에 사용하는 대신 한 browser companion을 phase deadline에 묶는다.

## 시작 전에 고정할 입력과 역할

부모는 accepted source/item freeze, 실행 코드·JAR·packaged UI binding, 필수 CI 성공, split별 실행 담당과 독립 final judge 수락·노출, 새 로컬 출력 경로를 한 실행 manifest에 등록한다. 설계·구현·source/item 작성/검토·실행 담당은 final judge가 아니다. 실행 담당은 자기 split만 열고 부모는 bytes/hash/count/status만 읽는다.

CLI는 `--enable-real-service-rag-execution --phase calibration|validation --manifest ... --run-dir ...`만 공식 경로로 둔다. endpoint·모델·top-k·질문·oracle·fixture override는 받지 않는다. 단위검사용 의존성 주입은 공식 CLI에서 접근할 수 없어야 한다. 코드/자료 검증은 시작·끝에서 수행하며 production 요청마다 Git/full-toolchain 검사를 돌리지 않는다.

등록 v3의 서술형 문항 계약은 부모가 수용한 아래 필드명으로 구체화한다. 기존 등록 파일은 수정하지 않는다.

- Questions: `schema_version`, `phase`, `cases`; 각 case의 `id`, `query`, `language`, `family_id`, `source_kind`. `source_kind=public|synthetic`은 provenance이고 API의 자료 종류 필터가 아니다. `cases` 배열이 실행 순서이며 query는 UI가 trim해도 달라지지 않는 원본 문자열이어야 한다.
- Runtime UUID는 문항/oracle에 넣지 않는다. Manifest의 family별 source 목록은 accepted manifest의 논리적 `source_id`, 원본 path/hash, source revision, meeting/document 역할, 처리·chunk binding을 참조한다. 업로드 응답으로 `source_id → 실제 document_id/revision/chunk_id`를 만들고 원문·chunk text/hash/codepoint 좌표로 전수 대조한다. 제목이나 검색 점수로 ID를 추정하지 않는다.
- family별 workspace/principal/visibility 배치는 manifest에서 질문 실행 전에 고정한다. 각 질문은 해당 family의 전체3문서에 접근하는 주체로 `kind=all`, 현재 workspace, `hybrid_rerank`, `base`, answer limit5를 사용한다. 날짜·참석자·문서 하나를 골라 정답 위치를 암시하는 필터는 쓰지 않는다.
- Driver/browser가 여는 평가 입력 allowlist는 자기 split의 accepted source, source/item freeze의 실행용 metadata, questions, 실행 manifest다. Oracle·selection 설명·semantic review notes는 열지 않는다. Oracle 무결성은 등록된 custodian의 freeze 확인 binding으로 받으며 driver가 이를 해석하거나 context에 넣지 않는다.

새 source/item freeze나 CI가 없으면 시작하지 않는다. Validation은 원래 cal6의 독립 판정 **6/6**, 운영 무결성 수용, 정리 성공, 답변 판단 lock을 연결한 gate receipt 없이는 서비스 자체를 시작하지 않는다. Judge 모델명·노출·역할 수락을 출력 생성 후 소급 등록하지 않는다.

## 한 split의 실제 순서

1. 새 run directory에 exclusive reservation과 최초 manifest를 저장한다. 이미 존재하거나 일부 실행된 경로는 재사용하지 않는다. 시작한 case/phase는 실패·중단 후에도 소비된 것으로 남긴다. 사전 확인 실패도 원래 receipt를 보존하고 자동 재시작하지 않는다.
2. 기존 `start_services`를 실제 기본 factory로 호출한다. pinned JAR, CPU e5/reranker, pinned native GPU28, 실제 uvicorn worker를 소유한다. source/item/실행 코드 확인부터 인증 health 준비까지 외부 startup120초로 측정한다. 내부 launcher120초가 외부 시간을 새로 부여하지 않는다.
3. Java HTTP ready 직후 active1500초를 시작한다. browser launch, 계정·workspace 생성, 업로드·자동 분석, 요청·화면·증거 저장이 모두 이 안에 들어간다. 새 isolated DB와 fresh credentials를 쓰고 기존 source 준비 DB나 사용자 DB를 재사용하지 않는다.
4. Manifest 순서대로 **일반 문서2개는 `/documents`, 회의4개는 `/meetings`**에 전체 원본 파일을 UI로 각1회 올린다. 기존 TXT/MD/textPDF ingestion을 그대로 사용한다. 파일을 text 입력으로 변환해 우회하거나 줄이지 않는다.
5. 회의 업로드는 `MeetingController.autoAnalyze`가 실행을 큐잉한다. 해당 document의 detail와 `/runs`를 GET으로 관찰해 그 run의 종료를 확인한 뒤 다음 회의를 등록한다. 수동 `/analyze` 재호출0, 재등록0, 재분석0이다. `analysis_status=ready`, 해당 revision, `ai_analysis`, 실제 model identity 및 worker/native 관측을 함께 확인한다. `201`만으로 분석 성공이라 하지 않는다.
6. 전체6개 원문·모든 chunk의 저장/좌표 일치와 접근 범위를 확인한다. 원문 준비 때의 UUID와 이번 실행 UUID가 다르다는 사실을 매핑에 보존한다. 네 회의의 분석이 끝나기 전에 답변을 시작하지 않는다. 추출이 기존 구조/입력/시간 한도에 걸리면 그 상태로 중단한다.
7. 원래 `cases` 순서대로 실제 React 지식 화면에서 질문을 넣고 `질문하기`를 **한 번** 누른다. 전송 전 durable attempt marker를 남기고 실제 POST/query/filter 일치를 확인한다. 별도 `/knowledge/search` 예행0, 직접 worker `/answer` 호출0, warmup/중립 질문0, repair/fallback/번역 재호출0이다.
8. 같은 POST의 Java 응답 `results`와 worker 입력 contexts를 대응시켜 순서·revision·좌표·전체 text를 보존한다. 성공 시 `KnowledgeService`가 반환한 `results`는 실제 검색 선택이며 별도 검색으로 재구성하지 않는다. 오류로 관측할 수 없는 단계는 unavailable로 기록하고 원문/oracle로 채우지 않는다.
9. React가 받은 claims/보류와 표시 내용을 저장하고, **반환된 모든 인용**을 실제 클릭하여 source panel의 원문·quote·revision·codepoint 좌표를 확인한다. source를 열지 못하면 실패다. 각 질문의 응답/인용 화면, 회의 분석 화면, 등록된 대표 desktop/mobile 화면을 보존한다. 다른 viewport를 위해 질문을 다시 보내지 않는다.
10. 기록을 닫고 새 요청을 막은 뒤 전체 소유 자원을 정리한다. 독립 답변 판단은 서버가 종료된 뒤 수행한다. Cal 판정 대기 중 서비스를 유지하지 않으며 validation은 gate 확인 뒤 별도의 한 번 실행이다.

공식 요청 수는 cal6/validation8 이하, 질문별 Java answer POST≤1·답변 native 생성 시도≤1, 합계 answer≤14다. 검색 결과가 비면 Java의 `no_evidence`로 native0일 수 있으며 이를 모델 보류나 성공으로 자동 판정하지 않는다. 전송 여부가 불명확한 timeout도 소비된 시도로 남긴다.

회의 자동분석은 split별 API4건 이하로 별도 집계한다. 기존 `MeetingRuntime.analyze`는 최대160단위 분류 등 기존 정책에 따라 여러 native completion을 보낼 수 있다. API 요청 수·분류 단위·실제 native 요청 시도/응답 수·tokenize 호출을 분리하고 답변14회에 숨기지 않는다. 이 문서는 분석을 native1회로 바꾸거나 별도 오프라인 tokenizer 준비를 허용하지 않는다.

## 실제 경로와 관측 연결

기존 launcher health가 검사하는 Qwen/GGUF/build/context6144, answer5120/928/90초, extraction4096/768/120초, CPU/FP32·model revision을 manifest에 묶는다. 기본 factory와 소유 PID/argv binding, Java opt-in/base 명시 인자, 실제 native POST/응답을 함께 확인한다. `model_called` 또는 HTTP health 문자열만으로 실제 모델을 증명하지 않는다. Java `/api/health`는 status/version만 증명하며 opt-in 효과는 budget header와 실제 요청 경로에서 확인한다.

Java가 응답한 UI index와 실제 참조 JS/CSS의 bytes/hash를 등록된 packaged UI와 비교한다. 현재 launcher는 filesystem UI 경로를 별도로 차단하지 않으므로 JAR hash만으로 UI bytes까지 확인했다고 하지 않는다. 확인 불가/상이하면 시작 실패이며 현장에서 rebuild하지 않는다.

Observer는 세 비동결 모듈의 선택적 인자로만 전달한다. Runtime에서 자기 작업의 입력·반환값·오류·시작/끝을 기록하고, answer는 기존 `QualityThinkingGenerator.answer(..., observe=...)`를 호출한다. 기존 prepared/apply-template/tokenize/native/result 이벤트를 활용하며 full prompt·전체 native JSON·reasoning·token IDs는 split 전용 raw 경로에만 둔다.

분석에는 같은 서비스 모듈 안에서 `Qwen35Generator._request`를 그대로 위임하는 작은 관측 subclass를 둘 수 있다. 요청/전체 반환 JSON·고정 오류코드·작업 종류만 기록하며 classify/partition/decoder를 복사하지 않는다. `_remaining` 전후 검사로 callback 기록 시간도 기존120초에 포함한다. 상태 관측이 필요해도 stream을 미리 읽거나 response guard를 우회하지 않는다.

관측은 요청을 추가하거나 응답을 바꾸지 않는다. 기존 observer가 제공하는 값은 **전체 parsed JSON**이며 원본 wire bytes로 부르지 않는다. 기존 HTTP가 읽지 않은 non-200 body는 `body_available=false`로 남긴다. 증거 저장 실패·두 번째 답변 native 전송 시도는 전송 전에 중단하고 실패로 기록한다. 기존 policy deadline 안의 raw 저장 부담을 측정에서 빼지 않는다.

Browser companion은 request/response body, DOM, screenshot을 역할별 디렉터리에 저장한다. Authorization/Cookie/Set-Cookie/password·인증 응답은 보존 대상에서 제외하고, 이를 담을 수 있는 기본 HAR/trace를 켜지 않는다. UI/API 원문·모델 결과는 요약/잘라내기 없이 남기며 stdout/stderr에는 고정 코드·불투명 case ID·count만 낸다. 부모에게 원문 screenshot/DOM/log를 출력하지 않는다.

## 시간·실패·정리

| 경계 | 수용 및 기록 |
| --- | --- |
| Startup | 외부120초. 실제 모델 준비/identity/HTTP ready 포함. 동기 hash/context entry는 hard preempt할 수 없으므로 늦게 반환하면 실패이며 실제 시간을 남긴다. |
| Answer | 기존 Java 진입→retrieval→worker→native→검증→최종 ACL90초 유지. 남은 예산 header 및 server elapsed를 보존한다. UI click→응답 저장→render 시간도 따로 측정하며 screenshot 시간은 active phase에 포함한다. |
| Analyze | 기존 worker120초·입력/출력/분류 정책 유지. Java queue 대기·upload→run 종료 외부 시간은 별도로 기록한다. |
| Active | HTTP ready 후1500초. 네 분석과6/8답변뿐 아니라 모든 UI/ingestion/증거 저장 포함. 기한 후 새 POST 금지, 진행 중 실패/미완료 구분. |
| Cleanup | 전체5초. 기존 native 정리가 먼저 수행됐다면 해당 시간을 포함한다. Node/Chromium까지 모든 소유 자원의 외부 정리 시간을 합산하며 launcher 내부5초를 추가 허용으로 해석하지 않는다. |

Driver가 lifecycle의 단일 소유자다. Browser 자식의 완료 메시지를 무한 blocking으로 기다리지 않고 bounded polling으로 active deadline과 service 생존을 확인한다. 종료 시 browser에 새 요청 금지/close를 통보한 뒤 기존 `service.shutdown()`의 Java·CPU 차단→native stop→worker join→context exit 순서를 사용하고 browser 종료도 같은5초 안에 확인한다. 동시 `shutdown()` 호출을 만들지 않는다.

Browser companion은 자체 소유 Chromium handle/PID를 등록하고 finally에서 context/browser를 닫는다. 필요하면 기존 Playwright `launchServer`의 소유 process handle을 사용한다. Driver는 남은 시간만 기다리며 실패 시 등록한 Node/Chromium 자원만 정리한다. 이름으로 전체 Java/Chrome을 종료하거나 native를 소유한 Python을 terminate하지 않는다. 종료 불확실·남은 thread/process·오류·5초 초과는 실패이고 잔여 자원을 없는 것으로 쓰지 않는다.

첫 자원·입력/구조·인증/권한·revision·저장·브라우저/증거 무결성 실패에서 phase를 멈추고 이후 case는 `unexecuted`로 남긴다. 구조적으로 유효한 의미 실패는 당시 실행자가 판정/튜닝하지 않으며 원래 순서대로 phase를 마친 후 judge가 판단한다. 어떤 실패도 같은 phase 재시작이나 같은 질문 재생성으로 구제하지 않는다.

한 phase 수용 창은 최대1625초다. 최초 확인부터 최종 receipt까지 실제 wall time을 남기고, 정리 때문에 늦어진 경우에도 실패를 보존하면서 가능한 소유 정리를 계속한다. 120/1500/5가 실제 hard termination을 입증한다는 표현은 쓰지 않는다.

## 남길 증거와 독립 판정

Run directory 하나에 input bindings/단일 사용 상태, logical↔runtime 매핑, API 요청·응답, worker 입력/응답, native observer 이벤트, UI 화면/DOM, 소유 PID와 종료, per-case 상태·시간, 최종 artifact index와 안전 요약을 남긴다. Canonical 원본은 accepted source freeze를 참조하며 run이 수정하지 않는다. 실패로 생성되지 않은 파일·단계도 manifest에 명시한다. DB는 종료 후 안정된 파일만 hash하고 SQLite 임시 sidecar를 필수 영속 파일로 묶지 않는다.

검색 전 허용 corpus는 로그인 주체·membership·visibility·문서 revision과 전수 chunk 매핑으로 기록하고 selected contexts가 그 부분집합인지 확인한다. 두 사용자/두 workspace 및 private 문서의 허용/거부 GET, 인용 접근을 실제 경로로 확인한다. 공식 질문의 전체3문서는 해당 주체에게 허용되어 있어야 한다.

이 최소 driver는 CPU worker 내부 embed/rerank payload나 BM25 통계 자체를 새로 가로채지 않는다. 따라서 실제 선택 문맥·인용 접근 관측과 **ACL-before-candidate 코드/합성 CI 증거**를 구분한다. 권한 회수/수정·삭제 race, 오래된 인용, busy/timeout/이탈·늦은 응답은 기존 결정적 합성 transport 회귀 증거를 따로 연결한다. 실제 추가 답변 없이 확인되지 않은 운영·편집/결정 연결/작업 경로는 미검증으로 남기며 Phase1 완료에서 누락하지 않는다.

Driver는 최종 answer/status/claims/citations와 질문·논리적 source 참조만 담은 익명 answer packet도 만든다. Model 이름·속도·token/호출 수·reasoning·원래 순위/검색 진단·성공 집계·실행 오류 상세는 final judge의 답변 판단 lock 전에 제공하지 않는다. 별도 custodian이 기존 oracle/전체 허용 원문을 판정 근거로 전달하며 parent는 packet 의미를 읽지 않는다.

Judge lock 뒤에만 검색 상위5개가 충분한 근거 대안을 회수했는지와 생성의 사실성·완전성·언어·보류·인용을 결합 진단한다. `retrieval_miss`, `context_budget`, `generation_faithfulness/completeness`, `abstention`, `ACL/revision`, `deadline/cleanup/evidence`를 분리한다. 정보가 전체 corpus에는 있는데 검색되지 않은 보류를 올바른 end-to-end 답변으로 세지 않는다. 문장·인용의 mechanical 일치는 의미 정확성 판정이 아니다.

Cal6/6 및 운영 수용만 validation을 연다. Validation8/8이더라도 별도 locked test·사용자 검수·미검증 Phase1 요구를 완료로 바꾸지 않는다. 기존 locked test는 열지 않는다. 독립 판정·사용자 검수·실제 native·실제 Java/React+합성 transport·합성 단위검사의 증거 수준을 각각 표시한다.

## 후속 구현 검사의 한계와 이 설계의 노출

NEW 합성 검사에서는 gate 누락/기존 run 재사용, source-ID 매핑 불일치, fixture 주입 거부, 질문 이중 클릭/native 이중 시도, 자동분석 run 실패, observer 저장 실패, actor별 출력 경로, 진단 차단, 합산 시간과 browser 잔류를 검사한다. HTTP/clock/factory fake만 사용하며 실제 acceptance 데이터·GPU·다운로드는 일반 CI에 넣지 않는다. 기존 launcher29검사는 재작성하지 않는다. 변경 observer 연결과 browser 모듈의 import/구문·계약 검사는 그 구현 commit의 CI에 포함한다.

이번 설계 담당 `/root/source_discovery_decision`은 기존 Astra xhigh 역할이다. generic 계획·등록·서비스/브라우저 코드·고정 합성 코드 예시·집계 상태만 읽었다. 실제 source/question/oracle/output/semantic notes는 읽지 않았으며 독립 final judge나 사용자 검수자로 기록하지 않는다. 작성 파일은 이 문서1개, 실행 구현/테스트/네트워크/모델/토크나이저/서버/브라우저/Git0이다.
