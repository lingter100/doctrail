# C4 호환성 후속 구현과 고정

2026-10-15. [별도 등록 계약](MEETINGS-C4-COMPAT-PLAN.md)에 따라 새 launcher/probe/tests4파일을 만들고, 원본43을 포함한52파일을 고정했다. 아직 새 실제 tokenizer/native/품질자료는0이다. 원본 C4-P0 실패는 변경하지 않았다.

## 구현과 검증

고정 literal과 새 합성 입력은 새 probe에만 있다. 원래 `ThinkingGenerator`의 설정·응답 검증과 generation_protocol은 그대로 import한다. followup_id로 별도 실행을 구분하며 source52·원본실패·tokenizer asset·준비영수증·계획을 연결한다. 준비영수증을 실제 tokenizer load 전에 배타적으로 예약하므로 완성JSON≤928 등의 준비 실패도 재실행하지 않는다.

새 launcher는 합친 stdout/stderr를8192bytes 이하로 계속 읽고 내용을 바로 버린다. 전체byte수,EOF,시작/읽기/합류오류만 기록하며 native 원문 로그를 만들지 않는다. process 정리와 reader 합류를 합쳐5초로 제한한다. 부모 검토로 startup의 yield 이전 실패에도 telemetry를 남기고, 미시작 상태의 byte수는0이 아닌unknown으로 표시했다. EOF/오류0/byte0을 확인해야 통과한다. 임시 저장은 경로를 확인하고 배타적으로 생성해 symlink나 기존 임시파일을 덮어쓰지 않는다.

실제 Astra high 구현 역할의 최종 검사는 **새33 + 원본47 =80통과, Windows symlink권한1skip,35.19초**, Ruff통과다. 실제 소형 Python subprocess4개로 stdout/stderr drain을 검사했으며 모델 프로세스가 아니다. 처음 새28통과/3실패는 fake tokenizer의 JSON key순서가 계획 저장 후 달라지는 fixture 오류였고 fixture만 정렬했다. Ruff의 테스트 class mutablelist1경고도 수정했다. 실제 모델 계약과 상한을 완화하지 않았다.

[sourcefreeze52](../data/evaluation/meetings-c4-compat-source-freeze-v1.json) SHA256 `de8bfc6b92603b1cd5d999afb5788222c7b71ccda1e7a9a3c0aa5a7df36ef61e`, [tooling 영수증](../experiments/results/meetings-c4-compat-tooling-v1.json) SHA256 `585c9837a506ba3b1a0b5d8ac9986ebee42e76f2e77970b522b1d8c19efbf746`에 실제 설정·초기 실패·최종 검사·부모 검토를 남겼다. 부모가 NEW4해시/LF와 전체52binding·원본43불변을 확인했다. 원격 전체 CI는 별도 STATUS에 기록한다.

## 고정 뒤 실행 순서

source/freeze를 커밋하고 필수 CI가 통과한 뒤만 register를 한 번 실행한다. 새 완성JSON 재토큰>928과 입력 길이가 준비되면 plan 및 `.preparation.json`을 함께 커밋한다. 조건 미달은 실패로 닫고 literal을 늘리지 않는다. 실제 생성은 새 output에서 normal1/stress1만 허용한다. 아래 명령은 준비된 순서에 맞게 사용하며 한꺼번에 실행하지 않는다.

```powershell
uv run --locked --no-sync --group retrieval python -m scripts.probe_meeting_thinking_compat_resources register --source-freeze data/evaluation/meetings-c4-compat-source-freeze-v1.json --plan data/evaluation/meetings-c4-compat-neutral-plan-v1.json --output .local/meetings-c4-compat-resources-v1
uv run --locked --no-sync python -m scripts.probe_meeting_thinking_compat_resources check --plan data/evaluation/meetings-c4-compat-neutral-plan-v1.json
# plan/preparation 커밋 뒤에만 실행한다.
uv run --locked --no-sync --group retrieval python -m scripts.probe_meeting_thinking_compat_resources run --plan data/evaluation/meetings-c4-compat-neutral-plan-v1.json
uv run --locked --no-sync python -m scripts.probe_meeting_thinking_compat_resources replay --plan data/evaluation/meetings-c4-compat-neutral-plan-v1.json --report .local/meetings-c4-compat-resources-v1/report.json
```

실제 const 수용,928token 부하/공유90초,실제 메모리,정리/metadata복구는 미측정이다. 원본 정상 속도 기반94.875초 decode 추정 위험을 유지한다. 사용자검수0·자동채택0·일반Q&A 및새cal6/6→격리val8/8 미완료다.
