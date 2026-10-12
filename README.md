# DocTrail

**소규모 개발 조직을 위한 권한 기반 문서 검색과 근거 확인 서비스.**

새 팀원이 온보딩·운영 문서에서 정보를 찾을 때, 볼 수 있는 문서의 어느 부분이 근거인지 확인하는 흐름을 만든다. 한국어·영어 문서를 대상으로 검색 기준선부터 임베딩·하이브리드·리랭킹·미세조정까지 비교하는 개인 AI Engineer 포트폴리오 프로젝트다.

## 현재 범위

첫 마일스톤의 문서 등록 → BM25 키워드 검색 → 원문 근거 확인을 로컬에서 구현·검증했다. 로그인·작업공간·나만 보기 권한, 수정·삭제·재처리, 검색 기록·피드백도 실제 API에 연결했다. 현재 검증 상태와 다음 작업은 [STATUS](docs/STATUS.md)에 기록한다. 임베딩 검색, 생성형 질의응답, 모델 학습 및 서비스 배포는 후속 단계이며 성과로 주장하지 않는다.

![로컬 검증 화면: 합성 온보딩 문서 검색과 원문 근거](docs/images/m1-desktop.jpg)

## 시작하기

Python 3.11, [uv](https://docs.astral.sh/uv/), Node.js 22 이상이 필요하다.

Windows에서는 저장소 루트에서 `./scripts/start.ps1` 한 번으로 설치·빌드·실행할 수 있다. 수동 실행은 다음과 같다.

```powershell
uv sync --frozen
cd web
npm ci
npm run build
cd ..
uv run uvicorn doctrail.app:app --host 127.0.0.1 --port 8000
```

브라우저에서 `http://127.0.0.1:8000`을 열고 계정과 작업공간을 만든다. Markdown, UTF-8 텍스트, 텍스트가 포함된 PDF를 등록하고 검색한다. 로컬 DB는 `var/`에 저장되며 Git에 포함되지 않는다. 기본 계정이나 고정 비밀번호는 없다.

개발 중에는 API 서버와 별도로 `web/`에서 `npm run dev`를 실행한다. 프런트엔드 개발 서버가 `/api`를 로컬 API 서버로 전달한다.

## 검증

```powershell
uv run pytest
cd web
npm run typecheck
npm run build
```

## 문서

- [제품과 사용자 문제](docs/product.md), [기존 서비스·채용 조사](docs/research.md)
- [구조](docs/architecture.md), [데이터·평가 설계](docs/data-evaluation.md), [단계별 완료 기준](docs/roadmap.md)
- [API 계약](docs/API-CONTRACT.md), [결정 기록](docs/DECISIONS.md)
- [Git 협업 규칙](CONTRIBUTING.md), [AI와 사용자 기여 기록](docs/CONTRIBUTIONS.md)
- [실험 실행·실패 분석](experiments/README.md), [운영·복구](docs/OPERATIONS.md), [시연·면접 준비](docs/DEMO.md)

## 라이선스와 사실 구분

프로젝트 코드는 MIT License다. 공개 문서·데이터셋은 각 원출처의 이용 조건을 따르며 코드의 MIT 라이선스로 재지정하지 않는다. 합성 예시와 공개 원문, 계획과 실측, 자동 검수와 사용자 검수를 구분한다. AI가 설계·구현·실험·문서 작성을 지원하며, 사용자의 직접 판단·검증은 별도로 기록한다.
