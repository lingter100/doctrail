# 진행 상태

기준일: 2026-10-12 (Asia/Seoul).

현재 단계: **M1 서비스·M2 기준선을 유지하며 M3 첫 로컬 GPU 비교를 완료했다. M3 서비스 연동은 아직이다.** 전체 프로젝트 완료나 검색 품질 달성을 의미하지 않는다. 사용자 질문 검수는 0개이며 학습·생성 답변은 아직 없다. M3 원격 CI 상태는 아래 실행 기록을 따른다.

선행 확인: 빈 작업 폴더, 별도 상위 프로젝트 지침 없음, GitHub 사용자 인증 확인, Python 3.11·Node·uv 사용 가능, RAM 약 32GB·RTX 4050 6GB 확인. Docker 명령은 설치되어 있으나 엔진은 실행 중이지 않음. 첫 단계는 Docker 없이 실행한다.

## M1에서 구현·검증한 범위

- 계정·세션·작업공간, 워크스페이스/개인 문서 권한, TXT·MD·텍스트 PDF 업로드, 본문·청크 저장.
- BM25 검색 전에 권한 필터를 적용한다. 원문 구절·PDF 페이지·리비전 확인, 수정·삭제와 검색 반영, 실패 이유·재처리, 개인 검색 기록·피드백.
- 자동 테스트 36개 통과. 로그인·권한·변경·삭제·재처리·Unicode/PDF 근거·내용 없는 로그·백업 복구·평가 입력 드리프트·분할 누출 거부를 포함한다.
- 프런트엔드 타입 검사·빌드 통과. 실행 시점 npm audit 0 vulnerabilities.
- 브라우저에서 로컬 검증용 계정 생성 → 합성 문서 업로드 → 검색 → 원문 확인 → v2 수정 → 새 내용 검색 → 피드백을 실제 수행했다. 데스크톱과 390px 화면을 확인했고 모바일 가로 넘침은 없었다. AI가 수행한 점검이며 사용자 검수는 아니다.
- 실제 로컬 서버를 중지·재시작한 뒤 브라우저에서 v2 문서와 개인 검색 기록의 유지를 확인했다.
- 공개 Kubernetes 문서 8개와 AI 작성 smoke 질문 12개를 처리·평가했다. [실측·실패 분석](../experiments/README.md)을 참고한다. 사용자 검수 질문은 0개다.

## 원격·공개 상태

- [공개 저장소](https://github.com/lingter100/doctrail), [M1 PR](https://github.com/lingter100/doctrail/pull/1).
- GitHub API에서 커밋 작성자·커미터 계정이 모두 `lingter100`에 연결되는 것을 확인했다.
- main 필수 검사·선형 이력·강제 푸시/삭제 금지를 설정했다. 통합 규칙은 CONTRIBUTING을 따른다.
- GitHub Actions: 구현 커밋 `357be1a`의 backend/web 검사 모두 [원격 통과](https://github.com/lingter100/doctrail/actions/runs/38196203926). 이후 문서 커밋과 main 통합 상태는 GitHub의 해당 SHA 검사 결과를 기준으로 확인한다.
- 서비스는 로컬에서만 검증했다. 외부 서비스 배포·유료 API·클라우드·GPU 임대는 하지 않았다.

## M1 당시 한계

BM25의 한국어 bigram·어휘 일치는 의미와 답변 가능성을 판단하지 못한다. PDF OCR·원본 레이아웃 편집·파서 프로세스 격리는 없다. 파싱은 동기식이며 검색마다 허용된 코퍼스를 토큰화한다. 1,000문서 부하·GPU 실행·임베딩·리랭커·학습·생성 답변은 아직 검증하지 않았다. Starlette TestClient의 httpx 연동에 deprecation warning 1개가 있으며 현재 테스트는 통과한다.

## M1에서 정한 후속 작업

1. M2: 공개 자료 약 1,000문서를 검토하되 문서 계열·번역·버전 수량을 별도로 센다. 포함 정의·파싱 결함을 검수한다.
2. Train 문서 계열과 dev/test 계열을 먼저 분리하고 학습 질문과 평가 240질문 목표를 별도로 준비한다. AI 작성·자동 검수·사용자 검수 상태를 보존한다.
3. 실패 유형별 BM25 기준선을 고정한 뒤 임베딩·하이브리드·리랭킹을 비교한다. 로컬 GPU 메모리·시간을 확인한 뒤 학습 대상을 확정한다.

실행은 README와 [OPERATIONS](OPERATIONS.md), 이후 단계는 [roadmap](roadmap.md)을 따른다. 유료 사용 및 공개 서비스 배포는 미승인이다. M1 당시에는 자동화나 예약 실행을 설정하지 않았다.

2026-10-12 추가 위임에 따라 현재 채팅의 매시간 후속 실행을 ACTIVE로 등록했다. 예약 실행의 첫 성공은 아직 미확인이다. 실행 조건과 승인 경계는 [AUTONOMY](AUTONOMY.md)에 기록한다. 그 뒤 수행한 첫 M3 비교의 실제 결과를 아래에 기록한다.

## M2 실제 수행 결과

| 항목 | 확인한 결과 |
|---|---|
| 공개 코퍼스 | Kubernetes 고정 커밋, CC-BY-4.0. 2,287개 검사 목록 중 313개 적격 문서, 1,974개 제외 |
| 언어·분할 | EN 235 / KO 78. Train 180 / dev 65 / test 66 / smoke 2 문서 |
| 중복 처리 | canonical 계열 255개, 번역·정확 중복·유사 중복 연결 그룹 212개 |
| AI 질문 | 최초 240개. 검색 실행 전 다중 문서 조건이 불확실한 dev 1개를 별도 버전에서 제외 |
| 현재 활성 질문 | dev 79 / test 후보 160 = 239개. 사용자 검수 0개. Test 검색 평가는 실행하지 않음 |
| 데이터 검사 | 원문·정제 해시, 재정제, 중복 그룹 재계산, 분할, 정확한 근거 오프셋, 출처 검사 통과 |
| BM25 개발 평가 | 313문서·3,588청크. 양성 59질문 중 top-5 청크에 모든 필수 근거가 있는 질문 30개(50.85%) |
| 교차 언어 | 주석상 다른 언어의 근거가 필요한 23질문 중 완전 근거 적중 1개(4.35%) |
| 실제 HTTP | 임시 DB에 로그인·313문서 업로드. 32검색 성공/0실패, p50 255.991ms / p95 385.146ms |
| 검수 도구 | 질문·근거·주변 문맥·전체 코퍼스 탐색 HTML, 실제 검수 JSON 제출/검증. AI가 승인하지 않음 |

수집과 저장된 질문 초안의 재컴파일은 재현 가능하다. AI를 다시 호출해 동일 질문을 얻는 추론 재현은 아니다. 1,000문서 목표는 미달이며 파싱 결함을 통과시켜 수량을 늘리지 않았다. 범위·제외 원인·편향은 [DATA-CARD](DATA-CARD.md), 계약은 [M2-EVALUATION](M2-EVALUATION.md), 실제 수치·실패는 [실험 기록](../experiments/README.md)에 있다.

## M2 검증과 재현

```powershell
uv sync --frozen
uv run ruff check src tests scripts
uv run pytest -q
uv run python -m scripts.prepare_corpus replay
uv run python -m scripts.prepare_corpus verify
uv run python -m scripts.question_dataset --manifest data/manifests/kubernetes-v1.json --questions data/evaluation/m2-dev-v1.1.jsonl data/evaluation/m2-test-a.jsonl data/evaluation/m2-test-b.jsonl
cd web
npm run typecheck
npm run build
```

질문 초안 재컴파일·리비전까지 포함한 전체 명령은 [data/README](../data/README.md)에 있다. 최종 로컬 검증은 **93 tests passed**, Ruff·프런트엔드 타입 검사·production build 통과다. 313문서를 재현·재검증하고 최초 240질문과 활성 239질문의 해시·원문 span·분할 검사를 통과했다. Starlette TestClient 관련 deprecation warning 1개는 남아 있다. 두 측정 보고서의 모든 코드·잠금 파일·입력 해시가 기록된 Git 커밋의 blob과 일치함을 확인했다. 오프라인 평가 커밋은 `65338f2`, HTTP 성공 실행은 `76a20fc`다. `git_dirty=true`는 당시 미커밋 문서·결과가 있음을 그대로 드러낸다.

첫 HTTP 측정은 Windows 임시 DB 정리 시 파일 잠금 오류로 끝났다. 지연시간 결과가 보존되지 않아 인용하지 않는다. [실패 기록](../experiments/results/m2-http-attempt1-failed.json)을 남기고 제한된 정리 재시도를 추가했다. 두 번째 실행은 서버 종료·임시 DB 정리까지 성공했다. 잠금을 잡은 프로세스는 확인하지 못했다.

## M2 한계와 다음 작업

1. 사용자 검수 0개인 현재 점수는 AI 라벨에 대한 예비 회수 지표다. [검수 화면 생성 방법](../data/README.md#실제-사용자-검수)을 제공했다. 확정 정답률·실사용 품질로 말하지 않는다.
2. M3에서 동일 dev·코퍼스로 BM25→다국어 임베딩→혼합→리랭커를 비교한다. 현재 기준선을 유지하며 test 질문으로 튜닝하지 않는다.
3. 현재 청크에 전체 주석 span을 담을 수 없는 dev 질문 3개는 별도 청크 설정 실험으로 다룬다. 순위 모델과 청크 설정을 동시에 바꿔 개선 원인을 혼동하지 않는다.
4. 정제 범위를 넓히면 새 코퍼스 버전·분할 영향을 먼저 검토한다. 미해결 include 때문에 절차 문서가 많이 제외되어 참조 문서 편향이 있다.
5. 모델 라이선스·고정 리비전·로컬 6GB GPU 메모리·지연을 확인한 뒤 학습 대상을 결정한다. Train 문서는 예약만 했고 학습쌍·가중치는 아직 없다.

근거 없음 12질문에도 모두 결과를 반환했다. 답변 보류 기능은 없다. 공개 코퍼스 점수로 최신성 충돌·권한·수정·삭제의 의미적 QA를 검증하지 않았다. 해당 API 회귀 테스트와 검색 품질 평가는 별개다. 동기 파싱, 검색마다 재토큰화, OCR·파서 프로세스 격리 부재, 최고 메모리 사용량 미측정이 남았다. HTTP는 로컬 동시성 1·32건이고 캐시·전원·다른 부하는 통제하지 않았다. 공용 배포·부하 시험 수치가 아니다.

M2에서도 서비스 외부 배포·유료 API·GPU 임대는 하지 않았다. 면접에서 설명할 판단과 한계는 [M2-LEARNING](M2-LEARNING.md)을 참고한다.

## M2 원격 재현 확인

[M2 PR #2](https://github.com/lingter100/doctrail/pull/2)의 구현·결과 커밋 `21c6019`에서 backend/web 모두 [원격 CI 통과](https://github.com/lingter100/doctrail/actions/runs/38200944111)를 확인했다. 새 Linux 환경에서 93개 테스트와 빌드뿐 아니라 313문서의 실제 재수집·해시 검증, 질문 240개 재컴파일, 리비전·활성 239개 검증을 수행했다. 이후 이 확인 기록을 추가한 커밋도 필수 검사를 통과한 뒤 같은 사용자 계정으로 main에 fast-forward한다. 현재 통합 SHA의 최종 상태는 PR과 GitHub 검사에서 확인한다.

## M3 첫 비교 · 실제 로컬 GPU 실행

실행 커밋 `a8fb5a9`, 보고서 [m3-retrieval-dev-v1.json](../experiments/results/m3-retrieval-dev-v1.json), 완료 checkpoint [journal](../experiments/results/m3-retrieval-dev-v1.json.stages.jsonl). 코드·잠금 파일·입력 해시가 해당 Git blob과 일치하며 모델·코퍼스의 실행 전후 해시도 같았다. 질문·청크·라벨을 바꾸지 않았고 이전 BM25 top10 순위·점수·지표와 정확히 일치했다. Journal과 문서 파일 때문에 `git_dirty=true`를 그대로 기록했다.

| 방법 | 양성 59질문의 모든 필수 근거 @5 | 주석상 교차 언어 23질문 |
|---|---:|---:|
| BM25 | 30/59 (50.85%) | 1/23 |
| E5-small 다국어 임베딩 | 29/59 (49.15%) | 1/23 |
| BM25+E5 RRF | 27/59 (45.76%) | 0/23 |
| RRF+ BGE reranker | 36/59 (61.02%) | 6/23 |
| 후보 예산 진단 RRF 25+25 | 30/59 (50.85%) | 0/23 |

혼합+리랭커는 BM25 대비 7질문 개선·1질문 퇴보로 순증 6개다. 전체 원문 근거 회수의 예비 dev 비교이며 답변 정확도·사람 검수·최종 test 개선이 아니다. 단순 임베딩·혼합은 이 조건에서 개선되지 않았다. 리랭커 입력50 안에 모든 근거가 있는 질문도 37/59에 그쳐 후보 회수의 한계가 남았다. 질문별 원문·순위·후보 손실과 면접 설명은 [M3-ANALYSIS](M3-ANALYSIS.md)에 있다.

로컬 RTX 4050 6GB에서 E5 FP32·문서 batch8/query1, BGE FP16·batch1로 실제 실행했다. 문서 벡터 준비 45.08초. 따로 측정한 단계 시간의 합계 p50/p95는 BM25 424/516ms, dense 25/35ms, hybrid 457/542ms, hybrid+reranker 2,556/2,925ms다. 실제 HTTP나 모델 상주 서비스 응답 시간이 아니다. E5 38/3,588개 문서 청크, 리랭커 803/3,950쌍이 512토큰 한도를 넘어 잘렸다. 잘린 뒤 모델이 실제 본 span의 근거 회수는 아직 측정하지 않았다.

E5 문서 준비의 GPU allocator peak allocated/reserved는 794/1,808MiB, 리랭커 질의 단계는 1,123/1,138MiB였다. 리랭커 로드 중 CPU RSS 샘플 peak는 4,353MiB였다. 전체 장치 VRAM·전력·동시 모델 상주 서비스의 메모리 사용량으로 해석하지 않는다.

로컬 **129 tests passed**, Ruff, 프런트엔드 타입 검사·production build 통과. 기본 의존성만 있는 CI에서는 NumPy/Torch에 의존하는 검사 2개를 skip하며 GPU 모델 품질은 검증하지 않는다. 상세 명령은 [M3-RUNBOOK](M3-RUNBOOK.md). Starlette TestClient와 모델의 `torch_dtype` 인자 deprecation 경고가 남지만 실제 실행은 완료했다. 토큰 길이 진단에서 출력된 길이 경고는 실제 forward 전에 512로 자르는 경로와 구분한다.

다음 자동 실행에서는 실패 분석을 바탕으로 후보 회수·잘림의 후속 실험을 제한적으로 설계하고, 새 검색 방법을 명시적으로 선택할 수 있는 서비스 연결을 구현한다. 기본 BM25를 유지하며 ACL 선적용, 벡터의 revision·청크 해시, 수정·삭제·재처리·warm cache 회귀를 확인한다. 이것을 마치기 전 M3 전체 완료로 표시하지 않는다. Train 학습·생성 답변·유료 API·공개 서비스 배포는 하지 않았다.
