# 데이터 구분

- `manifests/`: 출처, 고정 커밋, 이용 조건, 원문 체크섬. 공개 저장소에 포함한다.
- `raw/`, `processed/`: 재현 스크립트로 받은 공개 문서. Git 제외.
- `fixtures/`: AI가 작성한 합성 업무 문서. 실제 회사 문서·사용자 피드백이 아니다.
- `evaluation/`: 질문 생성 주체, 자동 검수, 사용자 검수 상태를 별도 기록한다.

초기 파일럿은 Kubernetes 공식 문서 8개(4개 주제의 한·영 번역 쌍)다. 파일럿은 파이프라인 점검용 `smoke` 집합이며 학습·개발·최종 테스트 성능의 근거가 아니다. M2의 고정 코퍼스는 2,287개 검사 목록에서 정제 기준을 통과한 **313개 문서**다. 약 1,000개 목표에 미달한 이유와 편향은 [데이터 카드](../docs/DATA-CARD.md)에 공개한다.

## M2 재현과 검사

저장소 루트에서 실행한다. `discover`는 새 데이터 버전을 만드는 수집 단계이며 기존 동결 파일의 덮어쓰기를 거부한다. 일반 재현에는 `replay`를 사용한다.

```powershell
uv sync --frozen
uv run python -m scripts.prepare_corpus replay
uv run python -m scripts.prepare_corpus verify
uv run python -m scripts.build_questions --job m2-dev
uv run python -m scripts.build_questions --job m2-test-a
uv run python -m scripts.build_questions --job m2-test-b
uv run python -m scripts.question_dataset --manifest data/manifests/kubernetes-v1.json --questions data/evaluation/m2-dev.jsonl data/evaluation/m2-test-a.jsonl data/evaluation/m2-test-b.jsonl
uv run python -m scripts.revise_questions --revision data/evaluation/revisions/m2-dev-v1.1.json
uv run python -m scripts.question_dataset --manifest data/manifests/kubernetes-v1.json --questions data/evaluation/m2-dev-v1.1.jsonl data/evaluation/m2-test-a.jsonl data/evaluation/m2-test-b.jsonl
```

raw·normalized checksum, 재정제 결과, 제목, 문서 계열·중복 분할, 질문과 근거의 동일 분할, 정확한 원문 구간을 확인한다. 위 명령은 test 질문의 **구조 검사**를 포함하지만 test 검색 성능은 측정하지 않는다. `--metadata-only`는 원문 없는 환경에서 더 제한된 메타데이터만 확인하므로 전체 검증을 대체하지 않는다.

질문 작성 지침·허용 문서·AI 초안은 [generation](evaluation/generation/README.md)에 보존한다. 저장한 초안을 같은 JSONL로 컴파일하는 과정이 재현 가능하다는 뜻이며, AI를 다시 호출해 같은 문장을 생성한다는 뜻이 아니다. 참고 답안은 AI 라벨링 자료이고 서비스의 답변 생성 기능이 아니다.

첫 검사는 최초 240후보, 두 번째 검사는 활성 239후보를 확인한다. `m2-dev-055`는 다중 문서 조건이 불확실하다는 평가 전 AI 검토에 따라 dev v1.1에서만 제외했다. 이전 JSONL과 이유를 보존한다. 현재 비교에는 **m2-dev-v1.1.jsonl(79개)**을 사용한다. Test 160개는 구조·출처만 검사했고 검색 성능은 측정하지 않았다.

## 실제 사용자 검수

```powershell
uv run python -m scripts.review_questions --manifest data/manifests/kubernetes-v1.json --questions data/evaluation/m2-dev-v1.1.jsonl --output .local/review/review-dev-v1.1.html
```

생성한 HTML을 브라우저에서 열어 질문·근거·주변 문맥과 원문을 확인한다. 실제 검수자가 질문별 판단과 필요한 이유를 입력하고 JSON을 다운로드한다. 페이지를 닫거나 새로고침하기 전에 다운로드해야 한다. AI가 사용자를 대신해 승인하지 않는다. 파일이 실제 제출되면 다음처럼 별도 영수증으로 보존한다.

```powershell
uv run python -m scripts.review_questions --manifest data/manifests/kubernetes-v1.json --questions data/evaluation/m2-dev-v1.1.jsonl --review .local/submitted-review.json --output .local/review-receipt.json
```

작성된 질문 JSONL의 `human_review`를 임의로 바꾸지 않는다. 자기 기입 검수자 정보는 인증된 전문가 신원을 증명하지 않으며, 영수증 생성만으로 최종 test 평가가 열리지 않는다. 새 검수 파일·화면 이름을 사용해야 기존 결과를 덮어쓰지 않는다. 검수자의 이름과 메모는 검토 없이 공개 저장소에 올리지 않는다.

파일을 직접 열기 어렵다면 `uv run python -m http.server 8765 --bind 127.0.0.1 --directory .local/review`로 로컬 서버를 띄우고 `http://127.0.0.1:8765/review-dev-v1.1.html`을 연다. 이 서버는 중지하면 접근할 수 없으며 공개 서비스 배포가 아니다. 실제로 사용 중인 포트가 있으면 중복 실행하지 않는다.

## M1 점검 자료 재현

```powershell
uv run python scripts/prepare_pilot.py
```

다운로드 재시도는 최대 3회다. 원문 SHA-256이 다르면 중단한다. `hugo-light-v2` 정제는 YAML frontmatter·HTML 주석·Hugo 태그를 제거하되 용어 툴팁의 표시 문구를 보존한다. v1에서 태그와 함께 용어가 사라지는 문제를 발견해 수정했다. 문장·코드·링크는 유지한다. 외부 정의·포함 파일은 완전히 렌더링하지 못하므로 미해결 태그를 provenance에 기록하고 사용자 검수를 pending으로 둔다. 정제 완료가 의미 보존 검수를 뜻하지 않는다.

Kubernetes Authors의 원문은 [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)이며 [원본 LICENSE](https://github.com/kubernetes/website/blob/4b10551a8c6f0a3f100356d8fc3c6fb5cfde1448/LICENSE)를 따른다. 원출처·고정 버전·변경 사항은 manifest와 생성되는 provenance.json으로 유지한다. Kubernetes의 프로젝트 승인이나 제휴를 의미하지 않는다. 프로젝트 코드의 MIT License는 이 문서들에 적용되지 않는다.
