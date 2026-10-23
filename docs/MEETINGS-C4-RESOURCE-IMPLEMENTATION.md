# C4-P0 자원 연결 코드와 실행 경계

2026-10-15. [등록 설계](MEETINGS-C4-RESOURCE-DESIGN.md)에 따라 새5파일을 구현했다. **이 문서 등록 시 실제 native 호출·tokenizer load·다운로드·새 품질 자료는0이다.** 합성 검사 통과를 모델 연결이나 답변 품질의 실측으로 해석하지 않는다.

## 구현과 검토

`ThinkingGenerator`는 기존 안전 HTTP·artifact identity 검사만 재사용한다. 비사고 전용 Qwen 어댑터를 상속하지 않고 chat completion의 사고/최종 내용과 원시 응답, native 설정·종료·토큰을 대조한다. Native parser가 허용하는 JSON fence를 비교할 때만 해석하며 최종 `message.content`를 수정하지 않는다. 미완성 fence는 강제 length 종료 부하에서만 허용한다. 정상 요청은 정확 JSON·자연 종료·최종 재토큰화384 이내를 모두 요구한다.

새 launcher는 인증된 loopback, 기존 GPU lease·고정 모델 검증, 소유 프로세스 종료를 사용한다. 자원 probe는 register/check/run/replay를 제공하고 새 output directory를 한 번만 사용한다. 실패하면 다음 생성과 재시도를 하지 않고 failed_closed 보고서를 남긴다. 성공 경로에서만 동일 identity metadata 재시작1회·추가 생성0을 확인한다. 마지막 요청 시작부터 정리까지120초, 요청마다90초, cleanup5초와 전체phase1200초는 별개다.

설계 역할의 pinned-source 검토에서 정상 fenced JSON과 부하의 미완성 fence를 오거절할 수 있음을 찾아 실제 실행 전에 보완했다. 부모 검토에서는 중복 cleanup 호출의 시간 덮어쓰기와 relative-import 누락을 확인했다. 첫 cleanup 측정/실패를 보존하며, `.db`, `from . import helper`, `..` 및 package initializer를 source closure에 포함한다. 동결 대상은43파일이다.

## 합성 검증과 고정

실제 Astra high 구현 역할의 최종 targeted 검사 **47통과/1.63초**, Ruff 통과다. Native 설정·split·종료·입력/출력 제한·deadline·중복 실행·source drift·정리 경합을 합성 응답과 프로세스로 확인했다. 처음43통과, Ruff5경고 보정, 상대 import 수정 전46통과를 최종47과 구분한다. 부모의 일회성 동결 helper는 첫 import 경로 설정 누락으로 파일 생성 전에 실패했고, 저장소 경로를 명시한 뒤 성공했다. 모델이나 실험 실행 실패로 세지 않는다.

[소스 고정43](../data/evaluation/meetings-c4-resource-source-freeze-v1.json) SHA256은 `2ba79c7fba2ad52090392f9256396dc8a1813b6bfae31d6b06a7ba2dd9f2d701`이다. 새5코드/테스트와 재사용 helper, package initializer, model manifest·lock·설계·protocol을 묶는다. [검증 영수증](../experiments/results/meetings-c4-resource-tooling-v1.json) SHA256은 `4badfc8047aea8175613296b70f70188515253ddcfd9cb5479d783ed3bef7ea5`다. 원격 전체 CI는 별도로 STATUS에 기록한다.

## 실행 순서

1. 이 source/freeze를 커밋하고 필수 CI를 확인한다.
2. 캐시 tokenizer만 사용해 새 합성 두 입력의 길이·prompt hash를 한 번 준비한다. 기계적 padding 길이 선택은 품질 질문 선택이 아니다.
3. 생성된 plan을 커밋한 뒤 한 번 실행한다. 기존 output을 지우거나 다른 이름으로 동일 실행을 반복하지 않는다.
4. 원본을 보존하고 모델 없는 replay로 확인한다. 자연어 Q&A 후보·자료 작성은 실제 자원 결과 이후 별도 계약이다.

```powershell
uv run --locked --group retrieval --no-sync python -m scripts.probe_meeting_thinking_resources register --source-freeze data/evaluation/meetings-c4-resource-source-freeze-v1.json --plan data/evaluation/meetings-c4-neutral-plan-v1.json --output .local/meetings-c4-resources-v1
uv run --locked --group retrieval --no-sync python -m scripts.probe_meeting_thinking_resources check --plan data/evaluation/meetings-c4-neutral-plan-v1.json
# plan 커밋 뒤에만 실행한다.
uv run --locked --group retrieval --no-sync python -m scripts.probe_meeting_thinking_resources run --plan data/evaluation/meetings-c4-neutral-plan-v1.json
uv run --locked --no-sync python -m scripts.probe_meeting_thinking_resources replay --plan data/evaluation/meetings-c4-neutral-plan-v1.json --report .local/meetings-c4-resources-v1/report.json
```

정확한 installed-native template/tokenization 일치,928token 부하와90초 여유, RSS 표본·정리·복구는 아직 측정하지 않았다. 512사고 예산은 요청값이며 native 설정에 직렬화됐다고 주장하지 않는다. 최종384는 재토큰화 수용 기준이다. C0~C3·M5-B·최종test는 그대로 닫혀 있고 사용자검수0·서비스 연결0이다.
