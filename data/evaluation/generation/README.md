# 질문 후보 작성 이력

`protocol.md`는 작성 에이전트에게 실제 읽도록 전달한 지침이다. `jobs.json`은 분할을 고정한 뒤 지정한 문서·문항 분포와 모델 설정을 기록한다. `.draft.json`은 AI가 실제 본문을 읽고 쓴 질문·답안·정확한 발췌의 원본이며, 상위 JSONL은 이를 결정적으로 컴파일한 후보 데이터다. 생성 모델 API를 같은 seed로 다시 호출해 재생성할 수 있다는 뜻은 아니다.

지침 hash는 이 파일이나 숨겨진 모델 문맥까지 포함하는 전체 대화 해시가 아니다. 서브에이전트 도구에 수락된 설정과 실제 기여 범위는 [CONTRIBUTIONS](../../../docs/CONTRIBUTIONS.md)에 기록한다. 모두 AI 초안이며 사용자 검수는 별도 이벤트가 실제로 제출되기 전까지 pending이다.

실행 중 발견한 경로 문제: 지침에 처음 적었던 `python scripts/build_questions.py` 방식은 Python이 저장소 루트의 `scripts`를 가져오지 못한다. 원래 지침과 해시는 기록으로 보존하고, 모든 작성 에이전트에게 아래의 올바른 모듈 실행법을 추가 전달했다. 데이터·분할·검색 결과를 바꾼 수정이 아니다.

```powershell
uv run python -m scripts.build_questions --job m2-dev
uv run python -m scripts.build_questions --job m2-test-a
uv run python -m scripts.build_questions --job m2-test-b
```

컴파일러는 원문과 일치하는 고유 구절의 위치를 계산하고 출처·작성 설정·사람 미검수 상태를 붙인다. 같은 구절이 여러 번 나오면 임의로 첫 위치를 고르지 않고 작성자가 위치를 지정해야 한다. 출력이 이미 있으며 내용이 달라지면 덮어쓰기를 거부한다. 라벨 수정은 새 데이터 버전에서 명시적으로 관리한다. 입력 코퍼스와 작성 지침 해시가 달라져도 중단한다.

원문 발췌의 저작자는 The Kubernetes Authors이며 CC-BY-4.0이다. 파일별 원출처·고정 버전·정제 변경은 `data/manifests/kubernetes-v1.json`을 따른다. 질문·참고 답안을 실제 사용자 질문이나 실제 서비스의 생성 답변으로 소개하지 않는다.

최초 세 작업은 각 80개씩 240개를 생성했다. 평가 전 별도 AI 의미 검토에서 dev 055의 두 문서 필요성에 이의가 나와 원본을 유지하고 [dev v1.1 리비전](../revisions/m2-dev-v1.1.json)으로 제외했다. 활성 후보는 dev 79 + test 160 = 239개다. `uv run python -m scripts.revise_questions --revision data/evaluation/revisions/m2-dev-v1.1.json`으로 동일 제외를 재현한다. 첫 순위 측정은 이 리비전 이후에 수행했고 test 순위는 측정하지 않았다. 사용자 검수는 0개다.
