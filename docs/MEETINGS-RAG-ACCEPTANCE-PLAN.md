# 실제 문서 검색과 자연어 답변의 서비스 검증

2026-10-20. **설계만 완료했으며 구현·자료 확보·테스트·모델 실행은 시작하지 않았다.** 다음 목표는 사용자가 원문을 등록하고, 권한이 적용된 검색 결과로 복수 문서 답변을 받아 인용 원문을 여는 실제 Java/React 흐름이다. 무료·로컬·실험 기능이며 품질 승인·기본 채택·Phase1 완료·공개 배포를 주장하지 않는다.

## C7 종료와 유지할 목표

부모는 제품 완성을 우선해 현재 C7 source 경로를 닫는다. 상태는 `no_adopted_corpus / quality_not_executed`다. 과거 실제 source admission 거부와 공식 합성 진단은 실행된 기록 그대로 보존한다. 가장 최근 feasibility는 license·자료 본문을 읽기 전에 탐색 예산이 끝났으며, 이것을 source 의미 실패·접근 오류·공개 자료 부재·모델 실패로 바꾸지 않는다.

효율적인 추가 탐색이 가능하다는 판단과 그 탐색을 지금 수행할 가치가 있다는 판단은 다르다. C7의 세 문서 전체가 작은 prompt에 들어와야 한다는 조건은 제품 필수조건이 아니므로, 원문 전체를 보존·색인하고 질문에 필요한 근거를 검색하는 경로에 작업을 집중한다. C7 protocol·동결77·닫힌 자료·원본 결과·거부 기록은 수정·재실행·재제출하지 않는다. 새 결과는 C7 성공이나 이전 실험과의 통제 비교가 아니다.

Phase1의 자연어 완전답변, 일반 문서·복수 회의·혼합 근거 통합, 제안/확정/완료/미해결 구별, 충돌·시점·조건 해석, 정확한 보류, KO/EN·교차언어, 인용·권한·revision·삭제·복구 요구를 그대로 유지한다. 발췌문 나열이나 담당자 lookup으로 목표를 낮추지 않는다. 회의 추출·사용자 편집·결정 연결·후속 작업·전체 화면·운영·사용자 검수도 최종 완료 조건이다.

## 기존 코드에서 확인한 연결점과 간극

| 현재 연결점 | 확인한 코드와 다음 작업 |
| --- | --- |
| 실제 요청 | `MeetingController`: `/api/knowledge/search`, `/api/knowledge/answer`; `KnowledgeView.tsx`: 답변 요청 `limit=5`, 인용 열기와 이전 응답 무효화가 이미 있다. 새 화면/API 체계를 만들지 않는다. |
| 권한과 최신성 | `KnowledgeService.snapshot`은 membership·visibility·ready 문서를 먼저 제한한 corpus를 만든다. rank 뒤 모델 전송 전과 응답 직전 snapshot을 다시 비교한다. 이 순서를 유지한다. |
| 검색 | `Retrieval`은 보이는 corpus에서만 BM25 통계를 계산한다. `LearnedSearch.rank`는 기존 dense/hybrid/hybrid_rerank를 지원하며 요청마다 허용 corpus를 embed한다. 현재 비용도 시간 측정에 포함한다. |
| 온전한 chunk | `Retrieval.chunkContent`의 기존 1000-codepoint/150-overlap 처리 결과와 좌표를 재사용한다. 등록 원문을 작은 평가 family로 자르지 않는다. |
| 실제 답변 정책 | `QualityThinkingGenerator.answer`와 `meeting_answer_thinking.prepare_answer`·mapper를 재사용한다. 현재는 서비스 worker 등록이 없으며 `ThinkingGenerator`의 일반 generate/classify는 resource-only 오류를 낸다. 기존 worker에 객체만 바꾸어 연결하면 안 된다. |
| 시간과 오류 | `GenerationClient.call`은 최대120초를 별도로 시작하고 retrieval도 별도 deadline을 사용한다. 전체90초 예산 전파와 block/span/identity/cleanup 오류의 안전한 구분이 필요하다. |
| 회의 분석 | 기존 `/analyze`와 자동 분석 경로가 있다. 새 답변 연결이 이를 조용히 비활성화하거나 실제 추출을 mock으로 바꾸면 전체 흐름 통과가 아니다. |

## 다음 구현 묶음: 연결 하나와 실제 경로 검증

설계 커밋과 부모의 별도 구현 배정 뒤 아래 범위를 한 묶음으로 수행한다. 새 prepare/probe/audit/review 8파일 체계, 데이터베이스·스키마, 범용 helper framework는 만들지 않는다. 기존 frozen 파일은 수정하지 않고 import 가능한 primitive를 재사용한다.

1. 작은 opt-in 답변 worker 어댑터에서 기존 인증·body 제한·오류 경계·모델 identity·정책을 연결한다. `QualityThinkingGenerator.answer` 결과를 현재 `schema_version/model/revision/status/claims/citations` 계약으로 반환하고 reasoning·prompt·token ID는 일반 응답/로그에 넣지 않는다. 응답 언어 선택은 기존 KO/EN 판정 규칙으로 고정한다.
2. 기존 GPU28 launcher와 worker admission/owned cleanup을 호출해 연결한다. 필요한 새 entrypoint는 서비스 조립만 맡고 native launcher·decoder·정책 코드를 복사하지 않는다. 답변/분석을 같은 GPU lease 안에서 직렬화하며, `/analyze` 정책의 실제 호환 여부를 먼저 확인한다. 호환되지 않으면 명시적 미완료로 멈추고 별도 등록된 최소 호환 작업을 제안한다. 추출 생략·fallback·추가 모델 다운로드로 우회하지 않는다.
3. `KnowledgeService`·`GenerationClient`의 opt-in 경로에서 API 진입의 전체 deadline을 retrieval과 답변 worker에 남은 예산으로 전달한다. worker는 자체90초와 남은 예산 중 작은 값만 사용한다. 응답 검증·마지막 권한 확인·필수 기록까지 같은 요청 예산 안에서 검사한다. 사용자 입력으로 예산을 늘릴 수 없어야 한다.
4. 기존 `KnowledgeView`·오류 문구에 입력 초과, 검색 실패, 모델 실패, 보류를 구분한다. 질문/필터/워크스페이스 변경·이탈·권한 박탈 때 이전 답변과 인용을 숨기는 동작을 보존한다. 클라이언트 abort를 native 종료 완료로 간주하지 않는다.
5. 기존 Java/API·브라우저 검증 수단을 확장하는 한 개의 좁은 서비스 검증 경로를 둔다. 코드 계약 테스트와 실제 모델 실행을 명확히 선택하며, 일반 CI에서는 GPU·실제 자료·평가 질문을 실행하지 않는다. 새 실행 결과는 별도 등록 경로에 보존한다.

배정 시 파일 소유권과 기존 동결 포함 여부를 부모가 확인한다. 별도 UI 담당자의 소유 파일을 겹쳐 수정하지 않는다. 테스트용 상태도 기존 Store/SQLite 스키마와 격리 절차를 사용하며 사용자 자료를 초기화하지 않는다.

## 첫 서비스 후보의 검색·문맥·자원 계약

- 공식 서비스 후보의 검색은 기존 `hybrid_rerank`, `base` embedding profile, 기존 캐시된 검색 모델의 CPU 실행으로 고정한다. KO/EN 교차 근거도 검사한다. 캐시/호환성이 없으면 진행 불가로 기록하며 BM25로 조용히 대체하지 않는다. BM25는 별도 표시한 연결 테스트에만 쓸 수 있다.
- 첫 후보는 현재 UI와 같은 상위5개 온전한 authorized chunk를 보낸다. 순위·동점·metadata는 기존 구현을 유지하며 oracle·필수근거 위치·평가 정답으로 context를 주입하지 않는다. 이 선택 정책은 새 질문을 보기 전에 고정한다.
- 원문 전체·처리 결과·모든 색인 chunk를 보존한다. 요청 문맥만 상위5개로 제한한다. C7의 문서2048/family4096 bytes·family6 chunks·24 blocks·M0 조건을 제품 원문 admission으로 가져오지 않는다.
- 기존 block parser의 요청10 chunks/160 spans/각1024 codepoints, 실제 input≤5120 tokens/context6144, 기존 wire guard를 유지한다. 선택된 전체 문맥을 실제 formatter로 검증하며 초과하면 native 호출 전 `context_budget_exceeded`로 실패한다. 첫 후보에서는 잘라내기·요약·재분할·더 작은 top-k 재시도·질문별 context 구제는 하지 않는다.
- 캐시된 Qwen3.5-9B Q5_K_M·pinned build·GPU28 요청·greedy/seed0/cache off/parallel1, output928·요청 thinking512·최종 content 재계수384·EOS 조건을 그대로 사용한다. Thinking512는 확인된 독립 hard cap이라고 부르지 않는다.
- 모델 답변은 사용자 요청당 최대1회다. 자동 retry·repair·translation·self-review·다른 모델 fallback은 없다. 자원/입력 오류는 보류 성공이 아니다. 모델·90초·출력 정책 변경이 필요하면 별도 근거와 사전 등록 없이는 실행하지 않는다.
- 답변90초와 owned cleanup5초를 구분한다. 상시 서비스는 아래 수명 정정에 따라 startup/readiness와 개별 요청을 따로 제한한다. 최초 startup은 따로 측정하며 요청 지연에서 숨기지 않는다. hard preemption은 입증 전 주장하지 않는다.

이 첫 후보는 긴 원문을 허용하지만 긴 prompt를 보장하지 않는다. 상위5개가 예산을 넘거나 복수 문서 근거를 놓칠 수 있으며, 그 실패를 실제 서비스 결과로 드러내는 것이 이번 검증의 목적이다.

## 새 자료와 판정의 격리

자료 담당자는 cal/validation/test별 실제 역할·허용 경로·노출을 본문 전에 등록한다. 부모는 metadata만 받고 validation/test의 원문·질문·oracle·개별 근거·출력은 보지 않는다. 기존 모든 closed family/URL/revision/raw·normalized fingerprint 및 근접중복 제외를 유지하고 누락 metadata는 미확인으로 남긴다.

각 split은 공개 family1+새 합성 family1, family당 날짜가 다른 완료 회의2+관련 일반문서1을 유지한다. 공개 회의는 실제 완료 기록이어야 하며 원문 전체의 이용 조건·파일 적용 범위·고정 revision/URL·raw hash·수집 실패를 보존한다. 합성은 동일 구성의 허구·AI 작성·역할을 표시한다. 표본은 product ingestion 범위로 받아들이며 C7 크기에 맞는 자료를 찾지 않는다.

source 담당은 저장소·revision 예약과 license 확인 뒤 직접 전체 자료 준비로 진행한다. 별도 metadata-only feasibility 회차는 만들지 않는다. 구체적인 요청/저장소/시간 예산은 다음 dispatch에서 본문 전에 부모가 고정하고, 최대 공개 family 후보2개/split을 넘기거나 자동 연장하지 않는다. License·의미 적합성을 확인할 수 없으면 원인과 미실행을 반환한다.

순서는 **역할/제외 등록→license·원본/처리/색인 provenance→독립 source 의미·신선도 검토와 source freeze→질문/oracle→독립 item 검토와 item freeze→실제 서비스 실행**이다. Source freeze는 원문 전체와 ingestion/chunker 설정·chunk hashes를 묶는다. C7 admission을 통과한 것처럼 기록하지 않는다.

cal6(KO3/EN3·답변4/보류2), validation8(KO4/EN4·답변4/보류4)를 유지한다. 답변가능 항목은 일반 단독≥1·복수회의≥1·혼합≥1·모든 충분한 대안이 복수문서를 요구≥2·양방향 교차언어≥1씩·필수사실3~6을 만족한다. 충돌/제안과 확정/시점·조건 및 보류의 정보 부재는 전체 허용 원문을 기준으로 검토한다.

정답 근거는 retrieval로 정하지 않는다. Oracle은 전체 허용 corpus에서 충분한 근거 대안과 부재를 먼저 정하고, 실행 때 검색된 context와 별도로 보존한다. 숨겨진 비허용 자료를 정답 근거로 삼지 않는다. 최신 날짜만으로 결정을 덮어쓰거나 충돌을 임의 해결하지 않는다.

Source/item 작성·선정·검토·구현·실행·설계 담당은 독립 최종 answer judge에서 제외한다. 실제 judge 수락·노출을 출력 전에 등록하고 익명 final answer/인용/질문/필요 판정 근거만 제공한다. 모델·지연·reasoning·성공 집계는 판단 lock 전 공개하지 않는다. 사용자 검수와도 구분한다.

기존 locked test는 열지 않는다. 새 서비스 test는 새 출처·역할·문항으로 따로 잠그고, cal/validation에서 정책을 확정한 뒤 별도 실행 등록 전까지 미실행으로 남긴다. Validation 통과를 최종 test나 Phase1 전체 완료로 부르지 않는다.

## 검증 순서와 중단 조건

| 단계 | 실제 작업·계속 조건 | 중단/한계 |
| --- | --- | --- |
| A. 서비스 연결 | Generic synthetic 계약 테스트와 실제 Java/React+synthetic model transport로 업로드·색인·권한·인용·실패 UI·deadline을 확인한다. 연결/분석 호환성 해결 후 코드 검토·부모 커밋·필수 CI로 간다. | 모델 의미 품질 증거0. 이 단계에서 필요한 최소 adapter 수정만 하고 또 다른 평가 플랫폼을 만들지 않는다. |
| B. 새 source/item | 위 격리 순서로 양 split의 자료·문항을 준비한다. 원문은 실제 UI/API로 등록하고 전체 색인/좌표/provenance 일치를 확인한다. | License·source 의미·freshness·item 요구가 부족하면 자료 단계 미완료. 원문을 줄여 성공시키지 않는다. |
| C. 실제 cal6 | 실제 Java→검색→worker→native→React 경로를 각 질문1회 실행한다. 최종 질문 전체의 사실·근거·언어·보류와 운영 무결성이6/6이면 validation을 연다. | 첫 자원/계약/권한/저장 실패는 즉시 중단하고 이후 미실행을 보존한다. 구조 통과 후 의미 실패는 등록된 cal phase 판정까지 마치되 같은 질문 재생성은 없다. |
| D. 실제 validation8 | cal6/6 및 동일 코드·정책·자료 binding을 확인한 격리 담당만8개를 실행·판정한다.8/8, 미지원 사실·부적절 보류·언어·운영 오류0을 요구한다. | 미달 시 이번 후보 미통과. validation 피드백으로 동일 세트를 조정·재실행하지 않는다. 새 변경은 개발 근거와 새로운 평가 계획이 필요하다. |
| E. 서비스 수용 | 실제 브라우저 원문 인용, 복수 문서 통합, 접근 불가·revision/삭제·분석/연결/작업·오류 후 명시적 재요청, 화면·운영·새 환경 재현을 종합한다. | 별도 locked test와 사용자 검수 전까지 실험 상태. 화면/합성 테스트 성공만으로 모델 또는 Phase1 완료를 선언하지 않는다. |

운영 회귀는 두 사용자·두 workspace·private 문서로 비허용 chunk가 후보/BM25 통계/embed·rerank·generation payload에 들어가지 않음을 검사한다. 검색 중 권한 회수·문서 수정/삭제, 오래된 인용 열기, 빈 검색, 입력 초과, timeout/busy, 이탈 후 늦은 응답, 오류 뒤 명시적 재요청을 포함한다. 보안 race는 합성 transport로 결정적으로 재현하고 실제 모델 경로의 통과 범위와 별도로 보고한다.

이번 cal+validation native 답변 상한은14회이며 warmup/중립 추가 호출0이다. 기존 회의 추출은 별도 작업 종류·호출 수·실측을 기록해 답변14회에 숨기지 않는다. 실제 test 실행 횟수와 사용자 시연의 새 질문은 실행 전에 별도 등록한다.

## 남길 증거와 성공의 의미

한 서비스 실행 manifest에 코드 commit·실행 모듈 hashes·모델/설정 identity·source/item freeze·등록 역할·시작/종료·실제 명령 설정을 묶는다. 기존 파일 검증을 재사용하며 whole toolchain을 복제하지 않는다. 모델 identity는 startup, 코드 binding은 실행 묶음 시작/끝에서 확인한다. Production 요청마다 Git history/freeze77 증명을 돌리지 않되, 요청마다 ACL·revision·근거 좌표 검사는 유지한다.

각 요청은 전체 허용 corpus에 정답이 있는지, 검색 상위5개가 충분한 근거 대안을 회수했는지, 실제 보낸 문맥, generation의 사실/완전성/보류/인용, ingestion·검색·대기·모델·검증·전체 지연, 중단/정리 상태를 분리해 기록한다. `no_evidence`나 모델 보류만으로 전체 corpus에 정보가 없다고 판정하지 않는다. 충분한 자료를 검색하지 못한 보류는 사용자 관점의 실패이면서 generation의 신중한 행동일 수 있다.

정확한 quote/offset 검사는 인용 정합성 증거이며 문장 의미를 보증하지 않는다. 검색 누락·문맥 예산 초과·근거가 있는데 틀린 생성·잘못된 보류·권한/최신성·시간/저장 실패를 구분하고, 실패 후 성공한 합성 수정으로 원래 실측을 덮지 않는다.

원문/prompt/raw 결과는 역할별 허용된 로컬 경로에서 보존하고 public에는 안전한 counts/hash/status만 낸다. 합성 단위검사, 실제 Java/React+합성 transport, 실제 로컬 모델, 독립 의미 판정, 사용자 검수를 각각 보고한다. 완료 산출물은 실제 화면에서 따라 할 수 있는 실행 방법·전체 흐름 증거·실패 및 미확인 목록이어야 한다.

## 이 설계의 노출과 현재 상태

담당은 기존 `/root/source_discovery_decision`이며 부모가 수락한 Astra xhigh/fork none 역할을 유지한다. 프로젝트 집계·허용 계획4개와 위 generic Java/Python/React 코드·launcher·runtime 설정을 읽었다. 일반 코드의 고정 prompt/합성 예시 노출은 있으며 실제 평가 원문·문항·oracle·모델 출력·의미 리뷰는 읽지 않았다. 문체 skill만 읽고 외부 문체 자료는 조회하지 않았다.

작성 파일은 이 문서 하나다. 네트워크·source 확보·processor·테스트·tokenizer·native·Git 변경0이다. 독립 최종 judge 또는 pristine/blind 설계라고 주장하지 않는다. 부모가 C7 종료/root 상태·commit/CI·후속 구현 배정을 맡는다.

## 2026-10-20 서비스 수명 정정

위 최초 작성 상태는 설계 반환 시점의 기록이다. 이후 같은 실제 Astra xhigh 설계 담당의 generic 코드 재검토에 따라 부모가 이 절을 추가했다. 기존 단발 실험의 시작→정리120초를 상시 서비스의 전체 수명으로 해석하지 않는다. 과거 후보·실측·동결 정책은 변경하지 않는다.

- Startup 수용 기준120초는 native 준비·두 클라이언트 identity·인증된 HTTP health 준비까지 포함한다. 현재 launcher의 `native_adapter_startup_seconds`는 HTTP 준비 전 측정이므로 이 전체 기준의 통과 증거가 아니다.
- 답변은 Java 진입부터 최종 권한 재검사까지90초, 기존 회의 분석은 별도120초/input4096/output768/분류 label4 정책을 유지한다. 같은 pinned native instance/GPU28/공유 outer lock으로 두 기존 정책을 조립하며 실제 동작 호환성은 별도 검증한다.
- 정리5초 수용은 native/drain뿐 아니라 소유 worker/handler 종료를 외부 실행 주체가 확인해야 한다. 현재 callback·잠금 합성 검사는 실제 종료나 hard preemption의 증거가 아니다.
- 일반 사용 서비스는 종료 요청까지 유지할 수 있다. 공식 평가만 split별 startup120초 + active phase1500초 + cleanup5초의1625초 창으로 제한한다. Active phase에는 업로드/분석·검색/답변·브라우저·증거 저장을 포함한다. Validation의 회의4건×기존120초와 답변8건×90초가1200초이므로, 설계 역할의1200초 권고에 ingestion/화면/기록 여유300초를 명시적으로 더한 운영 창이다. 개별 요청·출력·호출 수는 늘리지 않는다.
- Cal 정리와 독립 판정 lock 뒤 원래6/6 조건을 통과해야 validation 서비스를 시작한다. 실패한 phase를 재시작하거나 추가 호출로 구제하지 않는다. 실제 실행은 source/item 준비와 별도 실행 등록 뒤이며 현재 허가된 모델 호출은0이다.
