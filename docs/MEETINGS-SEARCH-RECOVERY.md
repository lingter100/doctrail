# 답변 오류 이후 원문 검색

AI 응답의 언어가 요청과 다를 때 Java는 알려진 worker 502 오류에 한해 `generation_language_mismatch`를 안전한 503 코드로 전달한다. worker의 상세 본문은 전달하지 않고, 알 수 없는 코드나 잘못된 HTTP 상태는 기존 `generation_unavailable`을 유지한다. 실패를 정상 답변 보류로 기록하지 않는다.

지식 검색 화면은 이 오류의 원인을 한국어로 설명한다. 답변 오류 배너의 **원문 검색으로 확인**을 누르면 질문, 검색 범위, 자료 종류, 회의 조건과 검색 방식을 유지하여 검색한다. 답변용 상위 5개 대신 검색용 10개를 요청한다. 사용자에게 보이지 않는 자동 재시도나 추가 생성 호출은 없다. 새 검색 또는 조건 변경이 이전 요청을 무효화하며 원문 보기와 접근 권한 처리는 기존 경로를 사용한다.

## 실제 검증

[운영 검사 영수증](../experiments/results/meetings-search-recovery-v1.json), [브라우저 원본](../experiments/results/meetings-search-recovery-browser-v1.json)을 보존한다.

- Java 전체 131개 중 130통과, 기존 선택적 외부 inventory 검사 1skip. 새 HTTP 오류 경계 4개와 기존 의미 오류 경계 1개는 모두 통과했다.
- production build 및 화면/검사 TypeScript 검사를 통과했다.
- 브라우저 4개 통과: 언어 오류 후 같은 질문·필터로 실제 검색·원문 열기, 검색 중 조건 변경의 이전 결과 차단, 기존 회의 텍스트/PDF 등록·실패 표시·검색, 작업공간/회의 필터 회귀.
- 가입·원문 저장·검색·원문 보기는 실제 격리 Java 서비스다. 언어 오류 응답은 합성 실패 주입이다. AI 생성 품질을 테스트한 것이 아니며 모델 호출0·사용자 검수0이다. 사용한 Java 프로세스가 종료되고 화면이 JAR의 production build와 같았음을 실행기가 확인했다.

## 실행

저장소 루트에서 `npm --prefix web run build` 후 `./server/mvnw -B -q -f server/pom.xml verify`를 실행한다. Windows에서는 `./server/mvnw.cmd`를 사용한다. 이어 `npm --prefix web run typecheck`, `npm --prefix web run test:e2e -- knowledge-recovery.spec.ts meeting-unavailable.spec.ts`로 재현한다. 기존 pinned wrapper/lockfile과 Java21/설치된 Playwright Chromium을 사용한다. 테스트 DB는 `.local`의 별도 임시 디렉터리에 생성한다.

이 복구 동작은 실험 C2의 서비스 채택이나 자연어 답변 기능 완성을 뜻하지 않는다. Phase 1의 자연어 답변 품질은 계속 개선 중이다.
