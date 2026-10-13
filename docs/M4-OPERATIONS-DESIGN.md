# M4 · 고정 저장본의 로컬 운영 검증

기준일: 2026-10-13. 상태: **설계, 실제 실행 결과는 별도 기록한다.** [Main-dev 분석](M4-MAIN-DEV-ANALYSIS.md)의 `eligible_for_separate_operational_validation` 판정을 받아, 성공한 학습 v2의 마지막 저장본 하나를 Java 서비스에 명시적으로 연결해 검증한다. 기본 BM25·기존 base 모델 실행 경로를 유지한다. 이 단계의 통과는 기본 모델 채택, 검색 품질의 추가 개선, 최종 test 또는 사용자 승인을 뜻하지 않는다.

## 1. 범위와 변경 경계

- 새 Python worker·실행기·검증기와 합성 회귀 검사를 추가한다. `src/doctrail/inference.py`, `scripts/serve_models.py`, `scripts/verify_model_service.py`는 기존 base 실행과 증거를 위해 보존한다. Java는 서버 설정으로 선택한 모델 식별과 검색 시점 이력 저장만 확장한다. React는 현재 연결 모델과 과거 이력의 모델 상태를 표시한다.
- `src/doctrail/model_retrieval.py`와 완료된 M2/M3/M4 실행·평가 계획의 바인딩 대상은 수정하지 않는다. 특히 [main-dev 계획](../data/evaluation/m4-main-dev-evaluation-v1.json)의 `source_sha256_lf`·`input_bindings`·`design_binding`, M4 실행/준비/수치 후속 계획의 `source_sha256_lf`·`frozen_source_sha256_lf`, 기존 M2/M3 보고서의 `source_sha256`가 보호 범위를 정한다. 새 코드를 기존 평가 실행기에 끼워 넣지 않는다.
- 학습, calibration/main-dev 추론, test 질문 접근, 새 데이터·하이퍼파라미터·후보 정책 탐색을 하지 않는다. 기존 실패와 회귀를 보존한다. 운영 검증기는 평가 질문·학습 pack·공개 코퍼스를 읽을 필요가 없다.
- Java가 인증·권한·문서/청크·순위·DB·이력·피드백을 소유한다. Python은 모델 추론만 수행한다. Java가 Python subprocess로 핵심 서비스를 대신 구현하지 않는다.
- 로컬 기존 GPU와 잠긴 retrieval 환경만 사용한다. 실행 전 활성 작업과 포트를 확인하고, 추론 중 의존성 동기화·중복 worker·중복 모델 작업을 금지한다. 유료 자원·클라우드·공개 서비스 배포는 범위 밖이다.
- 실제 검증 실행은 기존 모델 작업과 공유하는 `.local/m4-execution/active.lock`의 소유권을 먼저 확보한다. 남의 실행 lock을 지우거나 실패한 작업으로 추정해 빼앗지 않는다. 검증기는 자신이 확보한 lock과 자식 프로세스만 정리한다.

## 2. 모델 식별 계약

서버 환경변수 `DOCTRAIL_EMBEDDING_PROFILE`은 `base`가 기본이며 `m4-terminal-v1`만 추가 허용한다. 브라우저 요청이나 업로드 파일로 profile을 지정하지 않는다. 이름의 `v1`은 [저장본 manifest](../data/models/m4-terminal-v1.json) 버전이고, 실제 가중치는 성공한 **학습 v2의 16회 갱신 결과**다.

| 항목 | Base | M4 terminal |
|---|---|---|
| Profile ID | `base` | `m4-terminal-v1` |
| Model ID | `intfloat/multilingual-e5-small` | `doctrail/multilingual-e5-small-m4-terminal-v1` |
| Revision | `614241f622f53c4eeff9890bdc4f31cfecc418b3` | `62e530d3094e98b336d039f10956c8e0e2a39d24d66b07818e92a46f0aac10fb` |
| Revision 의미 | 원래 저장소 commit | 동결 checkpoint manifest의 SHA-256 |

Terminal 가중치 `model.safetensors`의 SHA-256은 `cfbb2be999370a594f36ceffefaaf9696b865e8f4a46df77841853b5a3a907c7`이다. Model ID는 로컬 실험 식별자이며 외부 모델 저장소 주소나 공개 배포를 뜻하지 않는다.

새 `src/doctrail/terminal_inference.py`는 기존 runtime을 확장하되 base manifest의 공유 객체를 덮어쓰지 않고 독립된 E5 spec을 사용한다. Health의 `embedding.model/revision`과 모든 `/embed` 응답에 위 terminal identity를 반환한다. 기존 BGE ID·revision·설정은 그대로 유지한다. 내부 HTTP schema v1의 기존 필드를 재사용하며 임의 모델 ID·revision을 환경변수로 받아 신뢰하지 않는다.

Java는 서버 profile의 allowlist에서 기대 identity를 정하고 health와 **매 query/passage 응답**을 검사한다. 중간에 base 응답·다른 checkpoint·잘못된 dimension·누락/중복 ID가 오면 전체 요청을 실패시키고 이력을 쓰지 않는다. 시작 시 health만 확인해서는 query와 passage가 다른 모델로 계산되는 것을 막을 수 없다.

공개 API의 모델 표현은 `embedding_profile: {id, model, revision}`로 통일한다. Capabilities에서는 설정된 profile과 준비 상태를 분리하고, 성공한 learned search에는 실제 검증한 profile을 넣는다. BM25는 모델을 사용하지 않았으므로 profile을 생략하거나 null로 둔다. 미기록 이력을 현재 profile로 추정하지 않는다.

브라우저가 마지막으로 확인한 모델과 실제 서버 모델 사이의 교체를 막기 위해 learned 요청은 `expected_embedding_profile`을 보낼 수 있다. 이는 모델 선택 권한이 아니라 서버의 현재 profile과 일치하는지 검사하는 조건이다. 불일치는409로 실패하고 모델 호출/검색 이력을 만들지 않는다. UI가 과거 이력을 현재 모델로 새로 검색할 때는 현재 profile을 사용한다.

## 3. 시작 검증과 cache

새 worker는 모델을 로드하기 전에 다음을 모두 검증한다.

1. 고정 checkpoint manifest·M3 base manifest·main-dev 계획/결과 및 terminal이 참조한 실행/준비/probe/train 보고서의 정확한 hash를 확인한다. 공개 영수증에서 성공한 학습 v2, 실제16회 갱신, 동일 checkpoint, main-dev의 운영 검증 자격을 확인한다. Manifest에 적힌 hash를 검증 없이 그대로 신뢰하지 않는다.
2. Terminal의 허용 파일은 manifest의5개다. 파일명 집합·size·hash·일반 파일 여부·경로 경계를 검사하고 symlink나 임의 추가 모델 파일을 허용하지 않는다. 명시적 경로 재정의가 있어도 같은 동결 bytes만 허용한다. 외부 다운로드·pickle 가중치·원격 코드는 사용하지 않는다.
3. 원래 base snapshot도 고정 hash로 검증한다. Tokenizer는 저장본에 재저장된 사본으로 바꾸지 않고 원래 검증한 base snapshot을 쓴다. Fast/right truncation, query/passage prefix, masked mean pooling, normalization, FP32, eager attention, 512토큰, passage batch8/query1을 유지한다. CPU는 명시적 선택일 때만 허용하고 GPU 검증과 구분한다.
4. 로드 완료 후에만 ready를 반환한다. 검증/로드 실패는 안전한 오류 코드로 종료하고 launcher가 소유한 프로세스만 정리한다. 내부 token·개인 경로·원문·질문을 오류나 로그에 넣지 않는다.

기존 passage cache key의 `(revision, 설정 fingerprint, 정확한 UTF-8 본문 hash)`에서 revision을 terminal manifest identity로 바꾸어 base와 구별한다. 재시작 시 메모리 cache를 비우고 런타임 hot swap을 지원하지 않는다. 같은 본문을 다른 document/revision에서 재사용해도 Java의 최신 ACL·청크 스냅샷만 결과가 될 수 있다. Cache 적중은 문서 접근 허가가 아니다. 삭제/수정된 과거 vector가 LRU에 남는 것과 과거 근거가 검색되는 것을 구별한다.

## 4. 이력·UI·복구

- 검색 완료 transaction 안에서 method와 profile identity를 같이 저장한다. 기존 `search_metadata`는 두 값 positional INSERT를 사용하므로 새 저장 테이블을 추가하거나 모든 관련 INSERT를 명시적 컬럼 방식으로 함께 고쳐야 한다. 기존 DB·검색 이력을 버리거나 초기화하지 않는다.
- 새 learned 이력은 저장된 profile을 그대로 반환한다. 기존 learned 이력의 미기록 identity는 알 수 없음으로 표시한다. Metadata가 없는 기존 BM25 이력은 기존 해석을 유지한다. Worker 재시작이나 서버 profile 변경으로 과거 이력을 새 모델로 바꾸지 않는다.
- UI에는 현재 연결 모델과 검색 결과/이력의 모델 상태를 알아볼 수 있게 표시한다. 과거 이력 선택은 현재 서비스에서 새로 검색하는 동작이다. 다른/미기록 profile 이력을 같은 모델의 재현처럼 표시하지 않으며 현재 모델로 재검색된다는 설명을 제공한다. 원래 method와 검색어는 유지한다.
- 롤백은 terminal Java/worker를 종료한 뒤 원래 base launcher와 동일 DB로 다시 시작하는 절차다. 상속된 terminal profile 설정을 제거하거나 `base`로 명시한다. 새 base 검색의 identity와 과거 terminal 이력의 identity가 동시에 올바른지 확인한다. DB 복원이나 이력 삭제가 필요 없어야 한다.
- Worker 중단 시 learned 요청은 명시적으로503, deadline 초과는504로 실패한다. 검색 기록·피드백 근거를 생성하지 않고 BM25로 자동 전환하지 않는다. 사용자가 키워드 검색을 명시적으로 선택하거나 기본 BM25 요청을 보내는 경로는 계속 동작한다.

## 5. 사전에 정한 운영 통과 조건

새 검증기 `scripts/verify_terminal_service.py`는 격리된 임시 DB·새 합성 계정/문서/질문만 사용한다. 기존 실제 사용자 DB를 검증 대상으로 쓰지 않는다. 최소 두 사용자, 다른 workspace, 소유자 private 문서와 shared 문서로 아래 조건을 점검한다. `dense`, `hybrid`, `hybrid_rerank` 모두 같은 terminal을 사용하되 순위 품질의 우열은 채점하지 않는다. BM25는 호환성 대조다.

| Gate | 요구하는 증거 |
|---|---|
| 고정 모델 | 실제 terminal health·embed·Java capabilities·검색·저장 이력이 정확한 identity로 이어짐. 잘못된 profile/manifest/file/응답은 거부 |
| 권한 | 미로그인401, 비회원 workspace404, 타인 private 문서가 검색·목록·직접 접근·수정·재처리·삭제·이력/피드백에서 노출되지 않음. Shared→private 전환 뒤 기존 member의 접근·결과 수·피드백도 차단. 합성 worker 요청 검사로 scoring 전 제외도 확인 |
| 근거 | 반환 document/revision/chunk/page/offset과 현재 원문이 일치하며 Unicode 포함. UI에서 같은 근거·원문을 열 수 있음 |
| 수정·재처리 | 원자적 revision 증가와 chunk 교체. 과거 chunk ID/본문이 결과에서 제거되고 과거 피드백은409. 동일 본문 재처리에서도 revision 검사는 유지 |
| 삭제 | cache가 따뜻한 상태에서도 삭제 문서가 모든 방식에서 제거되고 원문·피드백은404. 이력의 현재 접근 가능한 결과 수도 반영 |
| Cache | 실제 terminal passage 호출에서 같은 본문의 miss→hit, 변경 본문의 miss를 관측. 별도 합성 검사에서 profile identity/설정 변경이 적중을 재사용하지 않음 |
| 경합 | Terminal 기대 identity를 사용하는 결정적 Java 합성 worker 검사로 추론 중 수정·삭제·private 전환·문서 추가·membership 변경은409, 로그아웃은401. 실패 이력 없음 |
| 고장 | 실제 terminal worker 종료 후 learned503·이력 불변·기본 BM25 성공. 예상 profile 불일치는409·이력 불변. 합성 worker로 deadline·busy·malformed·identity 변경을 검사. 자동 fallback/재시도 없음 |
| 브라우저 | 실제 Java+terminal로 learned3방식 검색·근거·피드백·이력 재검색과 현재 profile 표시. 데스크톱/390px 가로 넘침·미처리 오류 없음. 모델 불일치 이력 표시는 별도 회귀 검사 |
| 롤백 | 동일 임시 DB에서 terminal 종료→원래 base 시작, base 검색 성공, terminal 이력·피드백 접근 규칙 보존 |
| 기밀·정리 | 로그에 원문/질문 sentinel·비밀번호·세션·내부 token 없음. 성공/실패 모두 소유 프로세스 종료·임시 DB 정리 |

실제 모델에 의한 순차 HTTP 확인과 합성 worker의 결정적 경합/오류 검사를 보고서에서 구분한다. 합성 응답을 실제 terminal GPU 실행이라고 기록하지 않는다. Terminal+BGE의 운영 통과를 main-dev에서 평가하지 않은 hybrid/rerank 검색 품질의 개선으로 확대하지 않는다.

모든 필수 gate와 관련 Python/Java 회귀, 프런트 타입·production build, Chromium 회귀, 정확한 PR head의 필수 원격 CI가 통과해야 통합한다. 무거운 모델은 일반 CI에 설치하지 않는다. 로컬 terminal 실행, 모델 없는 CI, 공개 영수증 검사, 사용자 검수는 별도 상태로 기록한다. 완료된 평가 재실행은 검증 조건이 아니다.

## 6. 결과 보존과 해석

실행 전에 설계·구현·합성 fixture와 검사 목록을 커밋으로 고정한다. 검증기는 명시한 새 output directory를 배타적으로 생성하며 기존 directory/성공 보고서/단계 journal을 덮어쓰지 않는다. 실패해도 완료 단계와 안전한 실패 코드·시각·수정 이유를 남기고, 수정 후 실행은 새 attempt로 구분한다. 운영 결함 수정은 허용하되 실패를 이유로 모델·검색 정책·fixture를 유리하게 바꾸지 않는다.

보고서에는 Git commit/dirty, 새 검증 소스와 Java JAR·프런트 artifact hash, terminal/base/BGE identity, 실행 장치/dtype, 공개 영수증 검증, 합성/자동 provenance, 각 gate 결과, 종료·정리 결과를 남긴다. Model load/startup과 Java HTTP/서버 elapsed를 분리하고 first/repeated 요청의 cache 상태와 순서를 기록한다. 소수 합성 요청의 시간은 원시 관측으로 보존하며 부하 성능·p95 우위·배포 SLA로 주장하지 않는다. Python 오프라인 시간과 Java 서비스 시간은 합산하거나 대체하지 않는다.

본 설계 시점의 사용자 질문 검수0·UI 직접 검수0·test 잠금·외부 서비스 배포0을 유지한다. 설계/코드/합성 검사/사례 분석은 AI 기여다. 이번 설계 담당 도구 수락 설정은 `terminal_ops_design`: `gpt-6-astra/xhigh`이며 부모 채팅 모델 변경의 증거는 아니다. 결과와 남은 한계는 [STATUS](STATUS.md)·[DECISIONS](DECISIONS.md)·[CONTRIBUTIONS](CONTRIBUTIONS.md)에 실제 실행 후 기록한다.
