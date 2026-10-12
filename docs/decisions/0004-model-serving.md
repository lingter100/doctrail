# ADR-0004 · Java 검색에 로컬 모델 추론을 선택적으로 연결한다

- 결정일: 2026-10-12
- 상태: 구현을 위한 계약 채택. 실제 구현·검사·서비스 측정 결과는 [STATUS](../STATUS.md)에 별도로 기록한다.
- 범위: 기존 E5-small·BGE의 서비스 연결, 권한·변경·실패·캐시의 운영 정확성
- 선행 결정: [Java 서비스](0002-java-service.md), [React 화면](0003-react-frontend.md), [M3 후보 정책](../M3-CANDIDATE-DESIGN.md)
- 작성: AI가 작성한 설계다. 사용자 질문 검수·사람 코드 리뷰·검색 품질 검증을 대신하지 않는다.

## 결정과 이유

Java 21 + Spring Boot가 계정·세션·ACL·문서 저장과 추출·청크·검색 후보·BM25·cosine·RRF·이력·피드백을 계속 처리한다. 선택형 모델 경로만 별도 Python 3.11 추론 프로세스의 인증된 loopback HTTP를 호출한다. Python에는 사용자 API, 데이터베이스 연결, 문서 목록·ACL·검색 정책을 넣지 않는다. React는 Java에 검색 방법을 요청하며 모델 프로세스에 직접 연결하지 않는다.

Python 프로세스는 이미 고정한 `LocalE5Encoder`와 `LocalBGEReranker`를 가져와 사용한다. 동결 대상 `model_retrieval.py`, M2/M3 실행 코드·입력·결과·journal을 수정하지 않고 새 운영 모듈에서 요청 경계와 자원 수명을 관리한다. 기본 BM25에는 모델 프로세스·가중치·heavy dependency가 필요하지 않다. 모델 명령만 `uv run --group retrieval ...`로 실행하며 추론 중 의존성 동기화를 하지 않는다.

Java에서 직접 추론하는 대안도 가능하다. ONNX Runtime은 JVM API와 Windows/Linux CUDA artifact를 제공한다. 그러나 현재 보유한 고정 safetensors를 ONNX로 내보내고 tokenizer·pooling·precision·잘림·raw logit의 수치와 순위를 다시 검증해야 한다. Optimum도 export 결과와 원래 PyTorch의 수치 검증을 별도 단계로 제공한다. 이 단계에서는 이미 확인한 모델 경로와 운영 통합을 함께 검증하기 위해 Python 추론 경계를 선택한다. Java ONNX가 불가능하거나 성능이 나쁘다고 판단한 것은 아니다. [ONNX Runtime Java](https://onnxruntime.ai/docs/get-started/with-java.html), [Optimum export와 validation](https://huggingface.co/docs/optimum-onnx/en/onnx/package_reference/export)

| 대안 | 이번 판단 |
|---|---|
| Java가 기존 Python 서비스에 전체 검색을 전달 | 인증·ACL·DB·검색 정책의 Java 소유권과 전환 목적에 맞지 않는다. |
| 요청마다 Python subprocess 실행 | 모델 로드 비용·프로세스 수명·오류 경계가 요청과 뒤섞인다. 상주 추론 프로세스를 사용한다. |
| Java ONNX Runtime | 가능하지만 별도 export·tokenizer·수치 동등성 검증을 선행해야 한다. 후속 비교 대상으로 남긴다. |
| 원격 유료 추론·벡터 DB·새 학습 모델 | 현재 로컬 운영 검증에 필요하지 않으며 새 비용·데이터·평가 변수를 추가한다. |

이 연결은 학습·생성 답변·전체 공개 코퍼스의 온라인 품질 재평가를 포함하지 않는다. 사용자 검수와 test 개방 조건, 유료 자원·서비스 공개 승인 경계는 유지한다.

## 모델과 검색 정책

모델 파일·tokenizer·config는 [고정 manifest](../../data/models/m3-models.json)의 크기와 SHA-256을 검증한다. 로컬 snapshot만 읽고 `local_files_only=True`, `trust_remote_code=False`, safetensors를 유지한다. 장치는 명시적으로 지정하고 CUDA 오류를 CPU로 자동 전환하지 않는다.

| 항목 | 계약 |
|---|---|
| E5 | `intfloat/multilingual-e5-small`, revision `614241f622f53c4eeff9890bdc4f31cfecc418b3`, 384차원 |
| E5 입력·출력 | query/passage 접두어, attention-mask mean pooling, L2 normalization, FP32 |
| BGE | `BAAI/bge-reranker-v2-m3`, revision `953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e` |
| BGE 입력·출력 | query-passage 순서, 단일 raw logit, sigmoid 없음, CUDA FP16 / CPU FP32 |
| 토큰 한도 | 기존 512 유지. E5 query 초과와 BGE passage 예산이 없는 query는 거부한다. Passage 잘림은 기존 정책을 유지한다. |

E5 모델 카드의 비영어 입력에도 query/passage 접두어를 적용하라는 안내와 BGE 공식 raw logit 예제를 확인했다. 실제 운영 계약의 리비전과 해시는 위 manifest가 기준이다. 모델 카드 최신 내용으로 동결 설정을 자동 변경하지 않는다. [E5 모델 카드](https://huggingface.co/intfloat/multilingual-e5-small), [BGE Transformers 예제](https://huggingface.co/BAAI/bge-reranker-v2-m3#using-huggingface-transformers)

| 요청 방법 | Java가 수행하는 계산 |
|---|---|
| `bm25` | 기존 권한 필터 후 Java BM25. 생략 시 기본값. |
| `dense` | 허용된 모든 청크와 질문을 E5로 인코딩하고 Java에서 exact cosine 계산. |
| `hybrid` | 같은 허용 집합의 B50·D50을 동일 가중치 RRF `Σ 1/(60 + rank)`로 결합. |
| `hybrid_rerank` | `balanced_depth_rrf50_v1`로 최대 50개 선택 후 BGE 점수를 받아 Java에서 최종 정렬. |

`balanced_depth_rrf50_v1`은 B1,D1,B2,D2 순으로 각 분기를 읽고 처음 본 청크만 넣어 최대 50개를 모은다. 마지막 자리는 B 우선이다. 선택 후 순서는 선택 집합 안에서 새로 매긴 순위가 아니라 원래 전체 B50·D50의 RRF로 정한다. BGE raw logit 동점은 이 입력 순서를 유지한다. Dense·RRF 동점에 사용할 서비스 청크 순서를 고정하고 Java 검사로 보존한다. 서비스 문서 ID·적재 순서는 동결 실험의 코퍼스 순서와 같다고 가정하지 않는다.

추가 방식은 예비 실험 선택지다. `hybrid_rerank`의 응답에는 선택한 정책을 구분할 수 있는 metadata를 제공하고, BM25의 기본값과 기존 점수·정렬·원문 결과 계약은 유지한다. 각 방식의 점수는 서로 같은 척도가 아니며 답변 확률·정답률로 표시하지 않는다.

## Java의 권한 스냅샷과 완료 시점

모델 호출 동안 SQLite read/write transaction을 열어두지 않는다. 다음 세 구간을 분리한다.

1. 짧은 읽기 transaction에서 원래 cookie의 서버 세션을 인증하고 workspace membership을 확인한다. 현재 `ready` 문서 중 workspace 문서와 본인 private 문서의 청크만 읽는다. 이 시점부터 숨긴 청크는 BM25 IDF·dense·RRF·BGE·모델 cache 요청 어디에도 들어가지 않는다.
2. 읽기 transaction을 닫은 뒤 Java에서 후보를 계산하고 필요한 모델 HTTP를 호출한다. 요청 당시 허용 집합의 문서 ID·revision·청크 ID·정확한 원문·page/offset과 반환할 metadata를 스냅샷에 보존한다. Worker cache의 원문 hash와 별개로 Java는 보존한 원문 전체를 최종 비교한다. 모델 응답은 Java가 이미 가진 후보 ID에만 결합하며 새로운 문서·본문·제목을 신뢰하지 않는다.
3. `BEGIN IMMEDIATE` 쓰기 transaction에서 **같은 cookie**의 세션을 다시 인증하고 membership을 재확인한다. 현재 허용된 전체 ready 청크 집합과 최초 스냅샷을 비교한다. 같을 때만 검색 이력·결과를 저장하고 응답한다.

전체 집합을 비교하는 이유는 top-k에 없는 문서의 변경도 BM25 통계와 후보 선정을 바꿀 수 있기 때문이다. 새 문서 추가·수정·재처리·삭제·가시성 변경·청크 교체·원문 metadata 변경을 비교에 포함한다. 결과 ID만 재확인하거나 같은 청크 ID의 본문 변경을 놓치면 안 된다. 현재 접근 가능한 문서 집합과 revision이 같아야 한다. 세션 종료·만료는 `401 authentication_required`, 추론 중 membership·스냅샷 변화는 `409 search_context_changed`로 실패한다. 처음부터 membership이 없으면 기존 `404 workspace_not_found`를 유지한다. 실패한 검색은 history/feedback 근거가 되지 않는다.

빈 허용 집합은 모델 호출 없이 빈 결과를 만들 수 있지만 최종 권한 확인과 이력 저장 계약은 똑같이 지킨다. 재검증을 통과한 transaction commit이 이 요청의 일관성 시점이다. 그 뒤 발생한 별도 변경을 이미 반환된 응답에서 소급 회수한다는 뜻은 아니다. 원문 접근·이력·피드백은 계속 각 요청에서 현재 권한과 revision을 검증한다.

## 내부 HTTP 계약 v1

Worker는 `127.0.0.1` loopback에만 bind하고 서비스용 비밀을 `Authorization: Bearer ...`로 받는다. 비밀은 32자 이상이며 충분한 임의값으로 생성하고 저장소·브라우저·응답·로그에 넣지 않는다. Health도 같은 인증이 필요하다. Java의 대상 주소는 명시적 port가 있는 `http://127.0.0.1`만 허용하고 redirect를 따라가지 않는다. JVM 기본 proxy 설정을 상속하지 않고 직접 연결을 지정한다. 비밀을 외부 host·proxy로 보낼 수 있는 URL이나 사용자 입력 대상 주소를 허용하지 않는다. [Java HttpClient proxy 설정](https://docs.oracle.com/en/java/javase/21/docs/api/java.net.http/java/net/http/HttpClient.Builder.html#proxy(java.net.ProxySelector))

Java는 서비스 요청별 안전한 ID를 생성해 `X-Request-ID`와 내용 없는 운영 로그에 남긴다. Worker도 자체 요청 ID를 생성해 오류 응답에 넣는다. 두 ID는 독립적이며 Java에서 worker로 전파하는 분산 추적은 이번 구현에 없다. 원문 query string과 본문·Authorization·경로상의 개인 정보를 로그에 남기지 않는다. Worker의 오류는 원 예외나 tokenizer 입력을 노출하지 않는 `{ "error": "safe_code", "request_id": "..." }` 형식이다. Worker access log를 끄고 원 예외의 무가공 출력을 막는다.

### `GET /health`

인증된 요청에 모델 준비 상태와 고정 계약을 반환한다. `ready`는 파일 검증과 명시한 장치의 모델 로드가 완료된 뒤에만 사용할 수 있다. 다음은 구조 예시다.

```json
{
  "schema_version": 1,
  "status": "ready",
  "embedding": {
    "model": "intfloat/multilingual-e5-small",
    "revision": "614241f622f53c4eeff9890bdc4f31cfecc418b3",
    "dimension": 384,
    "max_length": 512
  },
  "reranker": {
    "model": "BAAI/bge-reranker-v2-m3",
    "revision": "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e",
    "max_length": 512
  },
  "limits": { "max_embed_items": 64, "max_rerank_items": 50 }
}
```

장치와 dtype 같은 runtime metadata를 추가할 수 있지만 모델 경로·비밀은 노출하지 않는다. Java가 health를 확인했다는 사실만으로 이후 모든 추론의 성공을 보장하지 않는다. 실제 검색도 실패를 처리해야 한다.

### `POST /embed`

```json
{
  "schema_version": 1,
  "kind": "passage",
  "items": [{ "id": "request-local-0", "text": "synthetic passage" }]
}
```

응답은 `{schema_version:1, model, revision, dimension:384, items:[{id, vector:[...]}]}`다. `kind`는 `query` 또는 `passage`이며 query는 정확히 1개, passage는 1~64개다. `id`는 해당 요청의 고유 상관키이며 worker에 문서·사용자·workspace ID나 revision을 보낼 필요가 없다. Cache와 무관하게 제공한 모든 ID가 응답에 정확히 한 번 있어야 한다.

### `POST /rerank`

```json
{
  "schema_version": 1,
  "query": "synthetic question",
  "items": [{ "id": "request-local-0", "text": "synthetic passage" }]
}
```

응답은 `{schema_version:1, model, revision, items:[{id, score:0.0}]}`다. 입력은 1~50개이며 worker는 모든 입력의 raw logit을 반환한다. 최종 top-k와 tie 정책은 Java가 정한다. 기존 `LocalBGEReranker.rerank`는 정렬한 복사본을 반환하므로 wrapper가 그 결과를 원래 ID에 정확히 연결해야 한다. 정렬된 점수를 원래 입력에 위치만으로 결합하지 않는다.

두 추론 응답에는 `telemetry` 객체로 `cache_hits`, `cache_misses`, `truncated_inputs`, `elapsed_ms` 같은 제한된 정보를 추가할 수 있다. 이것은 모델 과정의 계수·시간이며 Java 전체 응답 시간과 구분한다. Java는 schema version·모델 ID/revision·차원·행 개수·ID의 유일성과 정확한 집합·유한한 숫자·0이 아닌 벡터 norm을 모두 검증한다. 누락·추가·중복 ID나 NaN/Infinity를 부분 결과로 수용하지 않는다. Worker 원문 오류를 Java 클라이언트에 그대로 전달하지 않는다.

## 자원·캐시·오류 경계

| 경계 | 초기 제한과 실패 동작 |
|---|---|
| 입력 본문 | worker 최대 512 KiB. 헤더뿐 아니라 실제 수신 바이트도 제한한다. |
| 입력 문자열 | query 1~500 codepoint, passage 1~1,000 codepoint. Java 기존 청크 한도와 맞춘다. 토큰 한도는 별도 검증한다. |
| 검색 corpus | 모델 경로의 현재 허용 청크 최대 4,096개. 초과 시 `422 visible_corpus_too_large`로 실패하고 일부만 임의 검색하지 않는다. |
| 문서 인코딩 | HTTP batch 최대 64개. 모델 내부 batch는 기존 E5 8/BGE 1을 유지한다. |
| 동시 추론 | Java는 모델 검색 전체에 단일 진입 제한을 두고 이미 진행 중이면 `503 inference_busy`로 실패한다. Worker도 실제 추론을 직렬화하고 대기열을 무한히 쌓지 않는다. |
| 네트워크 | Java connect timeout 2초, 검색 전체 모델 작업의 초기 deadline 120초. 각 호출에 남은 시간을 적용한다. Worker 응답은 최대 4 MiB까지 읽는다. |
| 실패 | 미설정·worker 중단·장치 오류·OOM·timeout·불완전 응답은 명시적 실패. BM25/CPU로 묵시적 fallback하지 않는다. |

전체 deadline은 지연의 SLO가 아니라 현재 로컬 cold cache 준비를 제한하는 안전 상한이다. Timeout이 이미 실행 중인 GPU kernel을 즉시 중지한다는 보장은 없다. Java는 늦은 응답을 폐기하고 worker는 실제 추론 종료까지 lock을 유지한다. 모델 검색이 실패해도 별도로 선택한 기본 BM25는 사용할 수 있어야 한다.

Passage embedding만 worker 메모리의 LRU에 최대 4,096개 보관한다. Key는 protocol/cache version, model revision과 encoder 설정 fingerprint, 원문 UTF-8 SHA-256으로 만든다. Prefix·pooling·normalization·max length·dtype/device 등 결과를 바꾸는 설정을 구분한다. Query·rerank 점수·원문 text·문서 목록·ACL·사용자 세션은 cache에 보존하지 않는다. 디스크에 vector나 corpus를 저장하지 않는다.

이 cache는 hash에 대한 순수 함수 결과의 재사용이다. 검색할 corpus나 문서 ID 목록이 아니다. 문서 수정은 Java의 원자적 청크 교체·revision 증가로 이전 청크를 후보 집합에서 제거한다. 새 내용은 다른 hash가 되어 새 embedding을 사용한다. 삭제·ACL 변경 후 이전 vector가 LRU에 잠시 남더라도 Java가 새로 허용하지 않은 text는 요청되지 않고 결과 후보가 되지 않는다. 같은 내용의 새 revision에 vector를 재사용하더라도 최종 문서 revision 검증은 생략하지 않는다. Cache entry를 조회하는 외부 API는 없다.

기존 offline 모델 객체의 `telemetry_inputs`는 누적 list다. 상주 worker wrapper는 추론 lock 아래에서 요청별 telemetry를 수집한 후 list와 누적 counter를 비워 메모리 상한을 유지한다. 동결 offline 모듈 자체를 운영 편의로 수정하지 않는다.

Worker 오류 코드는 `401 unauthorized`, `413 body_too_large`, `422 invalid_request/query_too_long`, `503 model_busy`, `502 inference_failed`로 제한한다. Java는 장애를 `inference_unavailable`, `inference_invalid_response`, `inference_timeout` 같은 안전한 서비스 오류로 변환한다. 잘못된 worker 자격증명을 브라우저 사용자 로그아웃으로 오인하지 않고 서비스 추론 장애로 처리한다. 모델 실패와 실제 사용자 세션 만료를 구분한다.

## React와 공개 API의 동작

기존 검색 API에 `method=bm25|dense|hybrid|hybrid_rerank` 선택을 추가하고 생략하면 BM25로 처리한다. 알려지지 않은 방법은 거부한다. 인증된 `GET /api/search/capabilities`가 다음 계약으로 기본 방법과 선택 가능한 방법을 알려준다. `status`는 `disabled`, `ready`, `unavailable` 중 하나이고 `available_methods`는 준비 상태에 따라 BM25만 또는 네 방법을 반환한다. Capability는 host/token/path/cache 상태를 공개하지 않는다. 최종 설정 변수·상태 코드는 [API-CONTRACT](../API-CONTRACT.md)에 반영한다.

```json
{
  "default_method": "bm25",
  "model_enabled": false,
  "status": "disabled",
  "methods": ["bm25", "dense", "hybrid", "hybrid_rerank"],
  "available_methods": ["bm25"]
}
```

검색 응답의 `method`에는 실제 사용한 방법을 기록한다. 검색 이력은 별도 `search_metadata` 테이블로 방법을 보존하고 metadata가 없는 기존 이력은 BM25로 읽는다. 기존 v1 데이터·이력·동결 Python 서비스 참조를 덮어쓰는 스키마 변경을 피한다.

화면은 BM25를 기본으로 유지하고 모델 설정이 없는 상태에서 사용 가능한 것처럼 보이지 않게 한다. 실제 선택과 실제 응답의 방법을 표시한다. 선택 후 모델 연결이 끊기면 명시적 오류를 보여주며 조용히 다른 방법으로 바꾸지 않는다. 사용자가 다른 방법을 선택하면 별도 검색 요청을 한다. 오래된 검색 완료가 새 방법·다른 workspace·새 로그인 상태를 덮지 않도록 [React 요청 세대 계약](0003-react-frontend.md)을 유지한다.

원문 결과·codepoint 근거·revision 확인·수정·삭제 후 결과 정리·history·feedback을 보존한다. 모델이 뽑은 구절도 생성 답변으로 표시하지 않는다. UI 재설계나 다른 제품 기능을 이 milestone의 우선 작업으로 추가하지 않는다.

## 검증과 완료의 의미

아래는 요구되는 검증 범위다. 문서에 적었다는 사실은 검증 성공의 증거가 아니다.

| 구분 | 확인할 내용 |
|---|---|
| 기본 경로 | 모델 설정·heavy dependency 없이 BM25 기존 계약과 Java/Python 회귀 통과 |
| 수치·정책 | Java cosine/RRF/균등 깊이 후보/동점과 입력 순서, invalid vector·score·ID 거부 |
| ACL | 다른 사용자 private 청크가 실제 모델 요청에도 들어가지 않음. 숨긴 문서를 추가해도 허용 결과·점수 동일 |
| 변경 경합 | 추론 중 수정·삭제·재처리·ACL·새 문서·로그아웃·만료·membership 삭제 후 stale 응답/history 없음 |
| cache | cold/warm 동일 출력, 수정 후 다른 hash, 삭제·권한 철회 후 미노출, bounded LRU와 telemetry |
| worker 경계 | 무인증 health/추론 거부, 실제 body 상한, batch/string 상한, busy·모델 오류·timeout·잘못된 JSON 처리 |
| 실제 모델 | 새 합성 계정·문서로 실제 pinned E5/BGE 요청, warm cache, revision/delete와 세션 흐름 확인 |
| 브라우저 | production React와 실제 Java의 기본/모델 선택·원문·수정·삭제·이력·오류·세션 흐름 확인 |
| 연구 보존 | 동결 M2/M3 입력·코드·결과·journal 해시 유지. test 질문 품질 평가 없음 |

가벼운 CI의 fake model 검사는 운영 계약을 검증하며 실제 GPU 추론·모델 품질 증거가 아니다. 실제 로컬 모델 점검은 합성 자료·자동 실행임을 밝히고 장치·revision·요청 수·cold/warm·시간 범위를 별도 새 보고서에 남긴다. 기존 Python 단계 지연을 Java HTTP 시간으로 사용하거나 과거 시간을 새 측정과 더하지 않는다. 두 모델 동시 상주 메모리·cold 요청 지연·실제 Java HTTP는 필요할 때 실제 값으로만 기록한다.

이번 완료는 선택형 모델 경로의 권한·최신성·실패·원문 workflow를 검증한 상태다. 예비 dev 성과의 일반화, 사용자 검수, train 학습 대상 확정, 답변 생성·보류·신뢰도, 높은 동시성 운영, 서비스 인터넷 공개까지 완료했다는 의미는 아니다.
