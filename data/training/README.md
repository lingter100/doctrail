# M4 학습 자료와 준비 검증

현재는 원래78개를 보존한 새 `m4-pilot-v2`에 **AI 질문80개(fit64·calibration16)**가 있다. v1 음성 부족·잘림 실패를 보존하고 추가4후보·잘린12입력의 독립 AI 검토와 실제 tokenizer 검사로 v2 준비를 통과했다. 첫 GPU 수치 실패와 고정 배율 후속 성공을 기록한 뒤 실제16회 가중치 갱신을 완료했다. 사용자 검수는0개다. [결과·해석](../../docs/M4-READINESS-RESULTS.md), [재현·복구](../../docs/M4-RUNBOOK.md), [v1 설계](../../docs/M4-READINESS-DESIGN.md), [v2 설계](../../docs/M4-READINESS-V2-DESIGN.md)를 따른다.

아래 원래 pilot의 수치와 생성 이력은 과거 snapshot으로 보존한다. 원본의 pending 상태를 나중의 검토 결과로 덮어쓰지 않는다. 학습 가설·조건은 [M4-DESIGN](../../docs/M4-DESIGN.md)에 있다.

## 자료와 구분

| 산출물 | 역할 |
|---|---|
| `m4-plan-v1.json` | 분할·질문·음성 검토·조건부 학습 계약 |
| `generation/protocol-v1.md`, `selection-v1.json` | 작성 지침과 결과를 보기 전 정한 문서 목록 |
| `m4-inventory-v3.json` | train 180문서의 fit 150 / calibration 30 분할·출처·해시 |
| `generation/m4-*.draft.jsonl` | 원문을 읽고 AI가 작성한 질문·참고 답안·인용 |
| `m4-pilot-v1/questions.jsonl` | 정확한 원문 오프셋·출처와 기존 청크를 연결한 질문 |
| `m4-pilot-v1/positive-pairs.jsonl` | 양성 후보 80쌍. 78질문 중 2개가 중첩 청크 2개에 들어감 |
| `m4-pilot-v1/negative-candidates.jsonl` | BM25 상위20 후보 1,560개. 아직 음성 라벨이 아님 |
| `m4-pilot-v1/report.json` | 구조·해시·분할 검사, 자동 격리와 부족한 조건 |
| `reviews/` | 작성자와 다른 AI의 의미 검토 이벤트와 해시 검증 보고서 |
| `generation/receipt-v1.json` | 도구가 수락한 역할별 모델 설정과 생성물 식별 정보 |

Fit은 64질문/16계열, calibration은 14질문/4계열이다. 한국어 59·영어19질문이며 주석상 한국어 질문·영어 근거51개다. 모든 인용이 원문에 정확히 존재하고 기존 청크가 전체 인용을 포함한다. 질문 중 자동 중복·청크 경계 격리 대상은0개다. 이것이 문장 의미의 정확성이나 독립성을 증명하지는 않는다.

음성 후보는 같은 partition에서만 채굴했다. 양성 계열·알려진 인용·정확/유사 청크로 판정한328개를 격리했고 나머지1,232개도 `unreviewed`다. 확인한 음성 라벨은0개이며 모든 양성·음성 후보의 `eligible_for_training`은 false다. 타당한 대체 답이 섞일 수 있으므로 순위나 낮은 점수만으로 음성을 확정하지 않는다.

Calibration의 링크 모음 문서에는 독립적인 실용 질문 두 개만 있어서 목표16개에2개 부족하다. 자료를 추가할 때는 선택 목록·초안·검수·컴파일 결과를 새 버전으로 남긴다. 원래 질문을 삭제하거나 평가 점수로 고쳐 목표를 맞추지 않는다. 사용자 검수는0개다.

Compiler 보고서는 의미 검토 **전** snapshot이다. 독립 AI 검토는 `reviews/m4-semantic-report-v1.json`에 추가 기록하며 원본 초안의 `semantic_review: pending`을 소급 덮어쓰지 않는다. 수정이 필요한 질문은 원본과 검토 이유를 남기고 별도 revision으로 처리한다. 구조 검사·AI 검토·사람 검수·학습 준비 상태를 서로 바꾸어 표현하지 않는다.

## 출처와 이용 조건

원문은 [The Kubernetes Authors](https://github.com/kubernetes/website)의 공개 실제 문서, revision `4b10551a8c6f0a3f100356d8fc3c6fb5cfde1448`이다. 문서별 고정 URL·저자·원문/정제 해시가 inventory에 있으며 근거에도 출처를 보존한다. 문서와 원문 인용은 [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/)을 따른다. 질문·참고 답안·작성 이유는 AI가 작성한 파생 학습 자료로 제공한다. 코드의 MIT License로 원문 라이선스를 대체하지 않는다.

원본·정제 전체 문서와 author pack은 Git에서 제외한 로컬 캐시에만 저장한다. 공개 파일에는 짧은 근거 인용과 메타데이터가 있다. 질문은 실제 사용자가 남긴 검색 로그가 아니다. Kubernetes 한 도메인과 AI 작성자의 표현에 치우쳐 있고, 운영 조직의 실제 질문 분포를 대표하지 않는다.

## 재현

Python 3.11과 저장소의 잠금 의존성을 사용한다. 이 경로에는 모델·GPU·유료 API가 필요하지 않다. 새 환경에서 다음을 실행한다. 기존 로컬 pack이 있으면 `author-pack`에 `--verify`를 붙인다. 명령은 기존 결과 덮어쓰기를 거부한다.

```powershell
uv sync --frozen --python 3.11
uv run python -m scripts.prepare_corpus replay
uv run python -m scripts.prepare_training author-pack --inventory data/training/m4-inventory-v3.json --partition fit --selection data/training/generation/selection-v1.json --output .local/m4-author-fit-v3.json
uv run python -m scripts.prepare_training author-pack --inventory data/training/m4-inventory-v3.json --partition calibration --selection data/training/generation/selection-v1.json --output .local/m4-author-calibration-v3.json
uv run python -m scripts.prepare_training replay --inventory data/training/m4-inventory-v3.json --author-packs .local/m4-author-fit-v3.json .local/m4-author-calibration-v3.json --drafts data/training/generation/m4-fit.draft.jsonl data/training/generation/m4-calibration.draft.jsonl --output-dir data/training/m4-pilot-v1
uv run python -m scripts.validate_training_reviews --drafts data/training/generation/m4-fit.draft.jsonl data/training/generation/m4-calibration.draft.jsonl --reviews data/training/reviews/m4-fit-semantic-v1.jsonl data/training/reviews/m4-calibration-semantic-v1.jsonl --author-packs .local/m4-author-fit-v3.json .local/m4-author-calibration-v3.json --output data/training/reviews/m4-semantic-report-v1.json --verify
```

Corpus loader는 기존 동결 코퍼스 전체의 바이트·정제·중복 그룹을 확인한 직후 train만 남긴다. M4 author pack·청크·채굴에는 dev/test/smoke가 포함되지 않으며 M4 도구는 평가 질문 파일을 열지 않는다. CI의 기존 M2 질문 재컴파일은 별개의 무결성 검사다. 최종 test 검색 평가를 개방하는 명령이 아니다.

저장된 초안에서 결과 파일을 같은 바이트로 재현한다. AI에게 질문 생성을 다시 요청해 같은 문장을 얻는 재현성을 주장하지 않는다. 코드·입력 해시가 바뀌면 새 결과 디렉터리를 사용한다. 현재 pilot을 다시 만들려면 `replay` 대신 `compile`과 **새** `--output-dir`를 사용한다.

## 면접에서 설명할 내용

- 문제: 최종 순위보다 후보 누락이 큰 병목이라 E5 후보 생성 학습을 먼저 검토했다. 청크 경계 실패까지 모두 학습으로 해결할 수는 없다.
- 방법: 이미 train으로 지정한 공개 문서를 중복·번역 계열 단위로 다시 나누고, 문서 전체를 읽어 독립 질문과 근거를 작성했다. 검색된 다른 문서는 관련성 미확인 상태로 남긴다.
- 실제 결과: 질문·근거·후보·검토 이력을 재현 가능한 파일로 연결했다. 보정 질문 수 미달과 의미 검토 결함도 보존한다. 모델 학습·성능 개선은 아직 결과가 없다.
- 직접 확인할 부분: 질문이 실제 업무에서 쓸 법한지, 인용만으로 답이 충분한지, 후보 문서가 정말 다른 답을 제공하지 않는지다. 사용자 확인이 없었다면 AI 검토라고 설명해야 한다.
