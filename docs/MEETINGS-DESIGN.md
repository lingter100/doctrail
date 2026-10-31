# 회의록과 문서의 통합 지식 검색 — Phase 1

설계일: 2026-10-13. 이 문서는 새 사용자 요청의 구현 계약이며 완료 증거는 아니다. 기존 M5-A 실행과 M5-B 18파일 동결은 변경하지 않는다. M5-B 예정 비교는 별도 상태로 보존한다. STT, 녹음, 실시간 처리, Meet/Zoom 연결은 Phase 1 완료 전 구현하지 않는다.

## 기존 구조와 확장 범위

현재 React/TypeScript 화면은 Java 21/Spring MVC API를 사용한다. Java의 SQLite 트랜잭션이 사용자·세션·멤버십·문서·청크·검색 이력을 관리한다. `DocumentService`는 TXT/MD/텍스트 PDF를 파싱하고 원문과 Unicode code point 오프셋을 가진 청크를 저장한다. DOCX·OCR는 현재 지원 형식이 아니므로 이 단계의 지원 목록에 넣지 않는다.

BM25가 기본이며 선택적으로 고정 E5, RRF, BGE를 사용한다. 별도 Python worker는 인증된 loopback HTTP로 벡터와 재정렬 점수만 계산한다. 새 생성 worker도 모델 실행만 맡는다. Java가 원문 선별, 접근 권한, 검색 정책, 검증, 저장과 상태 변경을 맡는다. 새 DB, 벡터 DB, 메시지 브로커 또는 Python 서비스 로직 대행을 추가하지 않는다.

회의는 **기존 문서에 연결된 메타데이터**다. `meeting.id == document.id`로 하고 원문·업로드 파일·검색 청크를 복제하지 않는다. 기존 일반 문서 API도 보존한다. 등록·원문 편집·삭제·재처리는 기존 `DocumentService` 경로를 재사용한다.

## 저장과 출처

추가 테이블은 다음 책임을 갖는다. 실제 열 이름과 API의 최종 차이는 구현 후 API 문서에 반영한다.

| 개념 | 책임 |
|---|---|
| `meetings` | 문서 FK, 추출 날짜·참석자·목적·요약, 분석 상태와 안전한 오류 코드, 원문 revision, 편집 version, 활성 분석 JSON, AI/사용자 수정 구분 |
| `meeting_analysis_runs` | 원문 revision마다 실제 시도 상태, 변경하지 않는 AI 결과, 모델 식별자·설정·시간, 안전한 실패 코드. 재시도는 새 run이며 기존 결과를 덮어쓰지 않는다. |
| `meeting_items` | 논의·제안·결정·미해결·작업 항목과 정확한 원문 구절·오프셋. 담당자·마감일·우선순위는 nullable. 작업 상태는 사용자가 수정한다. |
| `decision_links` | 이전/현재 항목과 양쪽 원문 revision, 명시적인 관계 종류, 변경 이유와 이를 뒷받침하는 원문 구절, 만든 사용자·시각 |
| 별도 질의 기록(구현 시) | 전체 작업공간 검색을 기존 단일 workspace 검색 이력에 임의 귀속하지 않는다. 질문 저장은 기능 데이터이며 운영 로그와 분리한다. |

모든 테이블은 `documents`에 cascade 연결한다. 원문 교체 시 분석을 stale로 만들고 활성 항목과 해당 revision의 링크를 검색·최신 이력에서 제외한다. 이전 AI run은 비교용으로 남기되 현재 근거로 쓰지 않는다. 같은 본문의 재처리도 청크 ID가 바뀌므로 revision 변경으로 취급한다. 회의 삭제 뒤 메타데이터·할 일·링크·검색에서 접근할 수 없어야 한다.

AI 원본 결과와 사용자 수정본은 분리한다. 사용자 수정은 `expected_revision`과 `expected_version`을 검증하는 CAS다. 새로운 AI 분석으로 사용자가 수정한 요약·작업 상태를 조용히 덮어쓰지 않는다. 재분석은 새 AI 초안을 만들고 사용자가 적용할 수 있게 한다. UI에서 AI 초안, 사용자 수정, 원문을 구분한다. 사용자 수정 요약을 원문인 것처럼 RAG 근거로 넣지 않는다.

## 공통 분석 DTO

다음은 구현 역할 사이의 최소 공통 계약이다. nullable 필드는 원문에 없을 때 `null`, 배열은 `[]`를 사용한다.

```typescript
type Span = { quote: string; start_offset: number; end_offset: number };
type ExtractionItem = Span & {
  id: string;
  type: 'topic' | 'proposal' | 'decision' | 'unresolved' | 'action';
  text: string;
  assignee: string | null;
  due_date: string | null;
  priority: 'low' | 'medium' | 'high' | null;
  status: 'needs_confirmation' | 'confirmed' | 'todo' | 'doing' | 'done';
};
type Analysis = {
  meeting_title: string | null;
  meeting_date: string | null; // ISO date only if explicitly supported
  participants: string[];
  purpose: string | null;
  summary: string;
  summary_evidence: Span[];
  items: ExtractionItem[];
  metadata_evidence: Array<Span & {
    field: 'meeting_title' | 'meeting_date' | 'participants' | 'purpose' | 'summary';
  }>;
};
type MeetingDetail = {
  document: Detail; // existing document DTO, including raw content/chunks
  meeting: {
    meeting_date: string | null;
    participants: string[];
    analysis_status: 'queued' | 'running' | 'ready' | 'failed' | 'stale';
    analysis_error: string | null;
    source_revision: number;
    version: number;
    ai_analysis: Analysis | null;
    analysis: Analysis | null;
    provenance: 'ai' | 'user_edited';
  };
};
```

`quote == document.content[start_offset:end_offset]`를 code point 기준으로 검증한다. 생성된 문자열을 유사 매칭하거나 원문을 고쳐 일치시키지 않는다. 항목 ID는 Java가 정규화·발급하며 모델이 만든 ID를 신뢰하지 않는다. 날짜와 담당자는 인용 구절에 존재해야 하며 로그인한 사용자를 자동 담당자로 삼지 않는다. 출처 문자열 일치는 의미 정확도 증명이 아니다. 확정 결정은 명시적 확정 근거가 있어야 한다. 모호한 의견은 `proposal` 또는 `needs_confirmation`으로 남긴다. 작업이 아닌 항목의 assignee/due_date/priority는 null이다.

요약도 원문 근거가 있는 AI 초안이며 `summary_evidence`의 정확한 원문 구절과 함께 표시한다. 구절 검사를 통과해도 요약 의미의 지지가 검증됐다고 표시하지 않는다. 사용자 수정으로 근거와 문구가 달라지면 사용자 작성 상태를 표시하고 AI가 검증했다고 하지 않는다. UI 저장 요청은 item ID를 유지해 작업 상태와 링크 참조를 보존한다. 작업 편집도 같은 analysis CAS를 사용한다.

## API 경계

기존 세션 쿠키와 Origin/요청 방어를 그대로 적용한다. ID를 알고 있어도 매 요청에서 현재 멤버십과 문서 ACL을 확인한다. 기존 규칙에 따라 수정·분석·삭제는 문서 소유자만 수행한다.

| API | 요청 / 응답 |
|---|---|
| `POST /api/workspaces/{id}/meetings` | multipart `file,title,visibility`; 기존 허용 파일 파서. `201 MeetingDetail`, 분석은 등록 후 enqueue |
| `POST /api/workspaces/{id}/meetings/text` | `{title,content,visibility}`; 직접 입력도 실제 문서로 저장. `201 MeetingDetail` |
| `GET /api/workspaces/{id}/meetings` | 현재 작업공간의 접근 가능한 회의 목록 `{items:[MeetingDetail]}`. 전체 작업공간·기간·사람 조건은 knowledge 검색에서 제공 |
| `GET /api/meetings/{id}` | `MeetingDetail`; stale 결과는 명시적으로 표시 |
| `POST /api/meetings/{id}/analyze` | `{expected_revision}`; `202 MeetingDetail`; 진행 중 같은 revision은 중복 호출 금지 |
| `PUT /api/meetings/{id}/analysis` | `{expected_revision,expected_version,analysis}`; 원문은 변경하지 않는 사용자 편집, `MeetingDetail` |
| `GET /api/tasks` | 선택적 `workspace_id,assignee,status`; 현재 원문과 접근 권한의 활성 작업만 반환 |
| 작업 수정 | `PUT /api/meetings/{id}/analysis`의 동일 CAS를 사용해 해당 action item만 변경한 전체 활성 분석을 저장 |
| `GET /api/meetings/{id}/links` | 현재 양쪽 회의에 접근 가능한 명시적 결정 연결과 원문 근거 |
| `POST /api/meetings/{id}/links` | target_meeting_id, source_item_id, target_item_id, 양쪽 expected_revision/expected_version, relation, quote/start_offset/end_offset. source는 현재 회의; 양쪽 확정 결정과 권한 확인 |
| `DELETE /api/meetings/{id}/links/{linkId}` | source 회의 소유자에 제한; 양쪽 현재 접근 권한 재확인 |
| `GET /api/meetings/{id}/runs` | revision별 분석 실행 상태·모델 식별·실패 코드·시각 |
| `POST /api/knowledge/search` | 아래 검색 요청, 기존 순위·출처 결과 재사용 |
| `POST /api/knowledge/answer` | 같은 검색 요청, 근거 검색 후 실제 생성·검증·권한 재확인 |

정확한 서버 status code와 필드명은 구현 계약 검증으로 맞춘다. HTTP 200의 실패 객체로 모든 오류를 감추지 않는다. 문서 미존재와 권한 없음은 기존 404 정책을 따른다. 수정 경합은409, 모델 미설정/장애는503, 모델 deadline은504, 과도한 입력은422/413을 사용한다. 입력·원문·raw 모델 출력을 오류 본문이나 로그에 넣지 않는다.

```typescript
type KnowledgeRequest = {
  query: string;
  workspace_id?: string | null; // null/omitted = all CURRENT accessible workspaces
  kind?: 'all' | 'meeting' | 'document';
  meeting_id?: string | null;
  date_from?: string | null;
  date_to?: string | null;
  participant?: string | null;
  assignee?: string | null;
  item_type?: 'decision' | 'action' | 'unresolved' | null;
  method?: 'bm25' | 'dense' | 'hybrid' | 'hybrid_rerank';
  limit?: number;
  expected_embedding_profile?: string;
};
type Citation = {
  document_id: string; revision: number; chunk_id: string;
  title: string; meeting_date: string | null; page: number | null;
  start_offset: number; end_offset: number; quote: string;
};
type Answer = {
  status: 'answered' | 'abstained';
  reason: string | null;
  claims: Array<{ text: string; citations: Citation[] }>;
  results: Hit[]; // extended with workspace_id, document_kind and meeting_date
  model_called: boolean;
  experimental: true;
};
```

작업공간·권한·기간·참석자·담당자·항목 종류 필터를 **후보 생성 전에** 적용한다. 전체 결과를 top-k로 자른 뒤 필터링하지 않는다. 일반 문서는 날짜/참석자처럼 회의 전용 조건이 있는 질의에서 제외되며 이 동작을 UI에 밝힌다. 자동 자연어 날짜 해석을 구현하지 않은 경우 필터 UI로 조건을 명시한다. 이름 문자열은 사용자 ID와 같다고 간주하지 않는다.

새 검색은 `Retrieval.rankChunks`와 기존 모델 순위 계산을 재사용한다. 모델 검색·생성 동안 DB 트랜잭션을 열어 두지 않는다. 시작 시 사용자, 세션, 관련 멤버십, 필터 조건, 전체 허용 후보와 revision을 캡처하고 끝난 뒤 재확인한다. 원문/권한/메타데이터 필터 상태가 바뀌면409로 폐기한다. 접근권한을 잃은 문서를 요약·인용·건수·이력·모델 요청에 남기지 않는다.

원문 인용은 chunk와 현재 document revision에 연결하고 Java에서도 검증한다. 인용을 눌렀을 때 문서를 다시 조회해 revision을 확인한다. 후보가 비어 있으면 모델을 호출하지 않고 근거 부족을 반환한다. 후보가 있다는 이유로 답변 가능하다고 판단하지 않는다. 구조 오류, 잘못된 quote, 잘린 JSON은 생성 실패이며 근거 부족 보류와 구분한다. 답변을 단순 검색 구절 나열로 대체하면서 실제 생성 성공으로 기록하지 않는다.

## 실제 모델과 비동기 분석

인증된 내부 worker 계약은 다음과 같다. worker에는 DB/사용자 세션이 없으며 Java가 보낸 승인된 현재 원문만 처리한다. `model`과 `revision`은 서비스 생성 모델의 실제 식별자다.

```typescript
// POST /analyze
type AnalyzeInput = {
  schema_version: 1; document_id: string; revision: number;
  title: string; content: string;
};
type AnalyzeOutput = {
  schema_version: 1; model: string; revision: string; analysis: Analysis;
};
// POST /answer
type AnswerInput = {
  schema_version: 1; query: string;
  contexts: Array<{
    document_id: string; revision: number; chunk_id: string; title: string;
    meeting_date: string | null; page: number | null;
    start_offset: number; end_offset: number; text: string;
  }>;
};
type AnswerOutput = {
  schema_version: 1; model: string; revision: string;
  status: 'answered' | 'abstained'; reason: string | null;
  claims: Array<{text: string; citations: Array<{
    chunk_id: string; quote: string; start_offset: number; end_offset: number;
  }>}>;
};
```

worker 인용은 전달된 chunk 범위에 속하는 문서 절대 code point 오프셋이다. Java가 현재 문서와 대조한 뒤 title/date/page 등 사용자 응답 metadata를 붙이며 모델이 생성한 제목이나 문서 ID를 신뢰하지 않는다.

기존 고정 Qwen3-1.7B 가중치는 새 운영 경로에서 재사용할 수 있지만 기존 v1/v2 프롬프트·실행기·계획은 수정하지 않는다. 새 프롬프트, 운영 runtime, worker와 launcher를 별도 파일로 만든다. 서비스 통합은 사용자가 승인했으며 품질 기본 채택이나 M5 검증 통과와는 다르다. UI와 결과 기록에 실험 모델임을 표시한다.

분석 job은 SQLite 상태와 bounded executor로 처리한다. 기본 한 개만 실행하고 대기 한도를 둔다. 업로드 성공과 모델 분석 성공은 별개다. 모델 장애에도 원문 등록·조회·키워드 검색이 가능해야 한다. job은 revision, 요청 사용자, run ID에 바인딩하고, 실행 전/완료 저장 전 소유권·멤버십·현재 revision을 재확인한다. 다른 사용자의 권한으로 일을 이어받지 않는다. 프로세스 재시작에서 남은 running은 명시적 중단 실패로 바꾸고 사용자 재시도만 허용한다. 자동 무제한 재시도·중복 모델 호출을 금지한다.

Qwen 기존 입력 cap1536/output384를 긴 회의에 그대로 적용해 조용히 잘라서는 안 된다. 새 모델 경로에서 토큰 기반 유한 분할과 각 원문의 절대 오프셋을 유지하고 분할 수·최대 출력·deadline·메모리 상한을 선언한다. 일부 분할 실패 시 전체 완성 요약으로 표시하지 않는다. 긴 입력은 명시적 상한 오류 또는 부분 완료 범위를 표시한다. 파서의5MiB 업로드 지원과 모델이 그 전체를 분석할 수 있다는 주장을 구분한다.

6GB GPU에서 retrieval과 generation 동시 상주를 가정하지 않는다. 검증 전 기본 실행은 직렬화하고 모델을 단계별 load/unload하거나 실제 메모리로 검증한 배치를 사용한다. 다른 실행의 GPU lock을 삭제하지 않는다. 실제 적용 greedy 설정과 model revision, 입력/출력 token, memory, HTTP latency를 남기되 Python 모델시간을 Java 서비스 시간으로 대체하지 않는다.

## 결정 이력

유사 문장·같은 주제·나중 날짜는 변경 관계의 증거가 아니다. AI가 자동으로 supersedes를 확정하지 않는다. AI 제안 관계를 제공하면 확인 필요 상태로 두고 사용자의 명시적 확인 전까지 결정 변경 이력에 포함하지 않는다. 검색된 관련 논의는 날짜순으로 표시하되 연결되지 않은 논의라고 구분한다. 변경 연결은 사용자가 양쪽 항목을 선택하고 현재 원문의 변경 이유 근거를 제공할 때 저장한다. 서버가 양쪽 현재 revision·원문 구절·접근권한을 확인하며, 사용자 연결이라는 출처를 표시한다. 구조적 quote 검사만으로 관계의 의미가 입증됐다고 하지 않는다.

구현한 링크 종류는 `supersedes`, `related`다. `supersedes`는 명시적 변경 근거가 필수다. 원문 revision 또는 연결된 결정 자체가 바뀌면 최신 연결 목록에서 제외한다. 관계와 무관한 작업 상태·담당자·요약 편집은 연결을 없애지 않는다. 링크 탐색이 접근 불가 프로젝트의 제목·담당자·관계 존재를 노출하지 않게 한다. 끝 노드를 최신 결정이라고 자동 명명하지 않는다.

## 검증과 완료 조건

완료 보고는 구현, 합성 회귀, 실제 공개 자료, 실제 모델 호출, 의미 검토, 사용자 검수를 각각 센다. 기존 test 잠금과 M5-B validation 격리를 유지한다. 새 실제 자료 실험은 이전 평가셋과 분리한다.

1. 실제 공개 회의 최소 두 날짜와 같은 프로젝트의 일반 문서로 등록→AI 분석→수정 저장→통합 검색→실제 생성→원문 열기를 검증한다. 고정 출처 URL·revision·라이선스·원본/정제 hash·변환을 기록한다.
2. 제안/확정 구분, 명시적 담당자/날짜, 없는 필드 null, 미해결, 여러 문서 통합, 존재하지 않는 답변의 보류를 의미 단위로 검토한다. 생성 오류와 의미 오류를 그대로 보존한다.
3. 두 사용자/두 작업공간/개인 문서로 목록·직접조회·검색 후보·모델 payload·이력·작업·결정 링크 누출을 검사한다.
4. 생성 중 세션 종료·권한 회수·원문 편집/삭제·메타데이터 필터 변경을 주입해 오래된 결과 저장/응답을 막는지 확인한다.
5. 분석 중복, queue 포화, malformed JSON, 인용 불일치, token 초과, worker unavailable/timeout, 서버 재시작 실패, 수동 재시도를 확인한다.
6. Java/Python 검사, React 타입·production build, 실제 브라우저 등록/상세/답변/출처/수정/작업 상태/빈 상태/모바일 회귀를 수행한다. 기존 BM25·문서 수정·PDF·권한·이력·feedback 회귀를 유지한다.

실제 채택한 자료는 Jupyter의 BSD-3-Clause 공개 회의록 2건과 일반 운영 문서 1건이다. 원문 revision·라이선스 보존·접속 정보 행 제거·원본 및 가공 hash는 [자료 기록](MEETINGS-DATA.md)을 따른다. 회의 운영 상황을 통제한 별도 합성 문서와 실제 공개 자료를 섞어 집계하지 않는다.

설계 에이전트 실행 설정은 부모가 도구에 전달해 수락된 `gpt-6-astra / xhigh`다. 부모 모델 변경이나 서비스 모델 변경을 뜻하지 않는다. 사용자 검수는0이며 이 문서는 AI 작성이다.
