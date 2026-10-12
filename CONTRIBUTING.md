# Git과 검증 규칙

혼자 개발하므로 **GitHub Flow**를 사용한다. `main`은 검증한 통합 상태를 유지하고 짧은 기능 브랜치 → PR → 검증 → 병합 순서로 진행한다. 상시 `develop`이나 형식적인 팀 리뷰 기록은 만들지 않는다. 참고: [GitHub 공식 GitHub Flow](https://docs.github.com/en/get-started/using-github/github-flow).

## 브랜치와 커밋

- 브랜치: `feat/document-search`, `fix/permission-check`, `docs/evaluation-design`.
- Conventional Commits: `feat(search): add permission-aware BM25 retrieval`, `test(auth): reject cross-workspace reads`.
- 커밋은 동작·목적 단위로 나누며 관련 검증과 문서를 함께 갱신한다. 가짜 과거 날짜나 의미 없는 이력은 만들지 않는다.
- 작성자와 커미터는 저장소 소유자의 확인된 GitHub 계정으로 설정한다. AI 지원 여부는 `docs/CONTRIBUTIONS.md`에 명시한다.
- PR에는 문제, 변경 후 동작, 실행한 검증, 미완료·한계를 적는다. 혼자 확인한 것을 동료 리뷰로 표현하지 않는다.
- 첫 빈 저장소의 기반 문서 커밋은 `main`에 직접 생성한다. 이후 구현은 기능 브랜치와 PR을 사용한다.

## 병합 기준

관련 API 테스트, 프런트엔드 타입 검사와 빌드, 데이터·실험 변경 시 해당 재현 명령을 통과해야 한다. 공개 가능한 파일인지 확인한다. 로컬 검증과 원격 CI 결과는 각각 기록한다. CI가 실행되지 않으면 통과했다고 간주하지 않는다.

GitHub의 `main`에는 `backend`·`web` 검사 통과, 최신 기준 브랜치 반영, 선형 이력, 강제 푸시·삭제 금지를 설정했다. 관리자에게도 검사를 적용한다. 혼자 개발하므로 허위 승인 리뷰를 만들지 않으며 사람의 필수 승인 수는 설정하지 않았다.

PR의 실제 head SHA 검사가 통과하면 로컬 `main`을 검증된 기능 브랜치로 fast-forward한 뒤 사용자 계정으로 푸시한다. GitHub에서 PR의 merged 상태와 원격 main SHA를 확인한다. 이 방식은 별도의 봇 커미터를 추가하지 않고 각 커밋의 사용자 작성자·커미터를 유지한다. 파일은 `.gitattributes`의 UTF-8 텍스트 LF 규칙을 따른다.

서비스 인터넷 배포와 유료 자원 사용은 사용자 승인이 필요하다. GitHub 공개 저장소 생성·푸시는 사용자가 명시적으로 요청한 범위다.
