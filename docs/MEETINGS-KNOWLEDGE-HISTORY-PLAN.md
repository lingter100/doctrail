# 통합 검색·질문 기록과 결과 피드백 — 최소 구현 계획

2026-10-27 · 설계만 완료. 구현·테스트·DB/모델 실행0.
기본 요구인 개인별 질문 기록·조건 복원·검색 결과 평가를 통합 화면에서도 제공한다. AI 품질과 독립적인 제품 흐름이며 기록 성공은 의미 정확성을 뜻하지 않는다.

## 유지와 범위
- 기존 searches/search_results/feedback, /workspaces/{id}/history, /searches/{id}/feedback 계약·데이터·동작을 유지한다.
- 기존 Java/SQLite·React만 확장한다. 공유 로그·대화·답변보관·새 아키텍처·모델·STT는 제외한다.
- 회의는 기존 document_id를 재사용한다. workspace_id=null의 전체 범위를 특정 작업공간으로 치환하지 않는다.

## 저장 계약
- Store의 user_version=1 additive 방식으로 CREATE TABLE/INDEX IF NOT EXISTS를 추가한다. 기존 열/데이터를 변경하지 않으며 기존·새 DB에서 반복 시작을 허용한다.
- knowledge_history: id PK, user_id FK users CASCADE, operation(search|answer), query, workspace_id nullable FK workspaces CASCADE, kind(all|meeting|document), filters_json, method, embedding_profile_json nullable, generation_model_json nullable, status(searched|answered|abstained), reason nullable, model_called, created_at; 사용자·시각 인덱스.
- filters_json은 meeting_id/date_from/date_to/participant/assignee/item_type/limit의 정규화된 필드만 저장한다. Filter 검증을 재사용하며 operation·kind·workspace-null·limit을 복원한다.
- embedding_profile은 실제 검증된 id/model/revision만 저장하고 BM25는 null이다. generation_model은 실제 검증된 model/revision만, 모델 미호출은 null이다. 기대 profile을 실행 모델로 기록하지 않는다.
- knowledge_history_results: id PK, history_id FK CASCADE, document_id FK CASCADE, revision, chunk_id, start_offset, end_offset, evidence_sha256; UNIQUE(history_id,chunk_id). chunk_id는 과거 식별자를 보존하되 현재 chunks를 다시 대조한다.
- evidence_sha256은 반환한 청크 원문의 UTF-8 SHA-256이다. revision·chunk·범위·hash로 근거를 묶고 응답에 result_id를 추가한다. 원문·청크본문·인용문·생성답변·제목은 복제하지 않는다.
- knowledge_feedback: result_id PK/FK knowledge_history_results CASCADE, relevant boolean, updated_at. 소유자는 history에서 확인하며 사용자 ID를 클라이언트에서 받지 않는다.

## 완료 저장과 오류 정책
- KnowledgeService의 검색 전 snapshot·생성 전 재검증을 유지한다. 검색/생성 호출 중 DB 트랜잭션은 닫는다.
- 응답 검증 후 최종 store.write 안에서 세션·사용자·멤버십·전체 허용 corpus/revision·회의 필터 상태를 기존 snapshot과 비교하고 기록/근거를 함께 삽입한다. 변경 시409와 전체 rollback; 인증 실패도 기록하지 않는다.
- 트랜잭션 내부·응답 전 기존 deadline 검사를 유지한다. 저장 실패는 rollback하고 성공 응답으로 대체하지 않는다. commit 뒤 deadline/통신 실패·취소에는 완료기록이 남을 수 있다. status는 서버검증완료이지 전달성공이 아니다.
- searched(0건 포함)·answered·abstained(미호출 포함)만 저장하며 reason은 허용 enum이다. commit 이전 4xx/5xx·timeout·생성오류·busy·문맥변경은 미기록이다.
- 전체 시도/장애 로그는 아니다. 실패 질문은 현재 폼에만 유지하며 새로고침 보존을 보장하지 않는다. 질문/raw 응답을 운영 로그에 추가하지 않는다.

## 신규 API와 현재 권한
- POST /knowledge/search|answer 요청은 유지하고 성공·보류 응답에 history_id와 results[].result_id를 추가한다.
- GET /knowledge/history → {items:[{id,operation,query,workspace_id,kind,filters,method,embedding_profile,generation_model,status,reason,model_called,created_at,result_count}]}; 현재 사용자만, created_at DESC,id DESC, 100개.
- GET은 지정 workspace/meeting 접근이 없으면 기록을 제외한다. 전체범위의 본인 질문·조건은 유지하되 원문·제목·답변은 반환하지 않는다. result_count는 현재 멤버십/ACL·ready·revision·chunk·범위/hash가 맞는 근거만 센다.
- POST /knowledge/history/{id}/feedback {result_id,relevant:boolean} → {ok:true}; write 트랜잭션에서 기록 소유권, 결과 소속, 지정 workspace/meeting 접근 및 해당 문서의 현재 멤버십/ACL·상태·revision·chunk·범위/hash를 검사한다.
- 타인/없는 기록·미소속/삭제 결과·접근불가는404, 형식오류422, 변경된 근거409 knowledge_result_stale. 오류에 원문/권한 밖 제목을 넣지 않는다.
- result_id 기준 UPSERT로 중복은 한 행, 반대 평가는 최신 입력으로 교체한다. 다른 청크는 별도 평가하며 기존 문서단위 feedback은 유지한다.

## 화면과 구현 소유 범위
- HistoryView에 ‘문서 검색’/‘통합 검색·질문’ 선택을 추가한다. 문서 기록은 현재 workspace, 통합 기록은 개인 전체에서 검색/답변·종류·범위·보류를 구분한다.
- 통합 기록은 KnowledgeView에 질문·필터·scope·mode·method·limit만 복원한다. 결과는 비우고 버튼으로 명시 재실행한다. 자동 모델호출·접근이 없어진 scope/meeting의 임의치환은 금지한다.
- profile 불일치/정보없음을 안내하고 현재 설정의 명시 실행만 허용한다. 이동/로그아웃/작업공간 변경은 늦은 응답을 무효화한다. 결과 카드에 관련 있음/없음·저장중·완료·명시 재시도를 제공한다.
- Java: Store.java, KnowledgeService.java, MeetingController.java, 신규 KnowledgeHistoryService.java 및 Java 테스트. 기존 ApiController/LearnedSearch 계약은 회귀 대상으로 둔다.
- React: types.ts, meetings.ts, useDocTrail.ts, App.tsx, ContentViews.tsx, KnowledgeView.tsx, 기존 스타일, 신규 knowledge-history.spec.ts. 문서: API-CONTRACT.md의 Q&A 미구현 문장/신규 API, MEETINGS-RUNBOOK.md의 저장정책/운영 안내를 갱신한다.

## 완료 조건과 후속
- 실제 Java/SQLite 검사: legacy DB 시작·재시작 보존, 기존 history/feedback, search0/answered/abstained 저장, 실패 미저장, 두 사용자·두 workspace·private 격리, 최종 저장 직전 권한/원문/필터 변경 rollback, 삭제/revision/chunk 변경·위조 결과·중복/변경 평가. 생성/검색 transport 합성과 실제 모델 품질을 구분한다.
- 실제 Java+React 검사: 검색→피드백→기록→새로고침/재로그인→조건 복원→명시 재실행, 여러 workspace/null/회의·문서 필터, 자동 호출0, profile 변경 안내, 두 계정/접근 철회·삭제, 늦은 응답, 1440/390px 및 키보드. 기존 문서 등록/검색/기록/피드백·원문·회의 편집/작업/연결 회귀를 유지하고 타입/build·필수 CI를 확인한다.
- 통과하면 이 흐름만 완료한다. AI 품질·사람검수·배포 완료로 확대하지 않는다. 항목 추가/삭제/근거 편집 UI는 별도 후속이다.
