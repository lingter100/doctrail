# C4-P0 — 단일 사고 호출의 연결·자원 사전 검증

2026-10-15. 실제 `gpt-6-astra`/`xhigh`를 수락한 `free_qa_candidate_review`의 읽기 전용 설계와 부모의 실행 범위 결정이다. **품질 후보를 채택하거나 품질 자료를 여는 계약이 아니다.** 이 기록 시점 새 모델 실행·다운로드·품질 질문 작성은 0이다. [기계 판독 계약](../data/evaluation/meetings-c4-resource-protocol-v1.json)을 함께 따른다.

## 문제와 선택

닫힌 C3는 정확 인용30/30에도 완전 정답2/6, 답변 가능한 질문0/4였다. 요구 해석, 근거 분류와 최종 재서술에서 모두 오류가 있었다. 같은 자료에 비슷한 프롬프트를 반복하지 않는다. 일반 문서·복수 회의·한국어/영어 자연어 답변이라는 원래 범위도 좁히지 않는다.

다음은 캐시된 Qwen3.5-9B의 사고 모드와 최종 JSON 분리를 **단일 native 호출**에서 확인한다. 현재 동결 구현은 비사고 모드를 명시적으로 검증한다. 전체 근거를 최종 답변까지 유지하는 단일 호출은 C3의 계획에서 답변으로 넘어가는 정보 손실을 줄일 가능성이 있다. 사고 모드와 호출 구조가 함께 바뀌므로 사고 모드만의 인과 효과를 입증하는 비교는 아니다. 짧은 사고 예산이 의미 오류를 해결한다는 증거는 아직 없다.

다른 계열인 Gemma3-12B IT QAT Q4_0도 검토했다. 추가 가중치 약8.07GB, 새 template 검증과 Gemma 조건 동의가 필요하고 이 장비의 속도·한국어 근거 답변은 미검증이라 이번에는 보류한다. 모델 파일을 받거나 조건에 동의하지 않았다. [Google 공식 저장소·조건](https://huggingface.co/google/gemma-3-12b-it-qat-q4_0-gguf), [파일 목록](https://huggingface.co/google/gemma-3-12b-it-qat-q4_0-gguf/tree/main).

설계 역할의 장비 조회는 Ultra7 155H, RAM31.51GiB, RTX4050 Laptop6141MiB였다. 캐시 가중치6,577,841,376bytes와 기록된 llama.cpp b11429/d812350을 재사용한다. 설계 단계에서는 가중치 해시를 재계산하지 않았으며 실제 실행기는 기존 검증기로 파일 해시·runtime·alias를 다시 검사해야 한다.

## 공식 구현에서 확인한 것과 미확인 경계

Qwen3.5는 기본 사고 모드와 `enable_thinking=false` 전환을 제공한다. Apache-2.0 원 모델을 기존 manifest의 고정 revision으로 사용한다. 공식 권장 출력 길이와 sampling은 이번 짧은 greedy 실험과 다르다. 공식 카드의 일반 성능을 이 서비스의 품질로 인용하지 않는다. [공식 카드](https://huggingface.co/Qwen/Qwen3.5-9B), [고정 template](https://huggingface.co/Qwen/Qwen3.5-9B/blob/c202236235762e1c871ad0ccb60c8ee5ba337b9a/chat_template.jinja).

고정 llama.cpp의 `response_format` 경로는 reasoning parser 뒤에 JSON content parser를 구성한다. 이 경로는 `grammar_lazy=false`이며 자동 tool-call용 lazy trigger를 수동으로 추가하지 않는다. raw `/completion`에 기존 grammar와 flag만 더하지 않고 새 `/v1/chat/completions` 어댑터를 만든다. `verbose`/`return_tokens` 응답으로 설정·토큰·종료를 확인할 수 있지만 설치된 바이너리에서의 정확한 조합은 아직 실행 전이다. [고정 parser](https://github.com/ggml-org/llama.cpp/blob/d81235049384534c167caea52b85a694f6103d14/common/chat-auto-parser-generator.cpp), [요청 변환](https://github.com/ggml-org/llama.cpp/blob/d81235049384534c167caea52b85a694f6103d14/tools/server/server-common.cpp), [요청 schema](https://github.com/ggml-org/llama.cpp/blob/d81235049384534c167caea52b85a694f6103d14/tools/server/server-schema.cpp), [응답 구현](https://github.com/ggml-org/llama.cpp/blob/d81235049384534c167caea52b85a694f6103d14/tools/server/server-task.cpp).

## 이번 구현·실행의 한도

- loopback 전용, 기존 인증·GPU lease·소유 process 정리와 가중치 검증 재사용. 서비스 worker/Java/UI에는 연결하지 않는다.
- 기존 GGUF/runtime, GPU24층·context6144·input≤5120, greedy/seed0·동시1·cache off. warmup/retry/fallback/download 모두0.
- **전체 생성 hard cap928tokens와 요청 준비·추론·후처리 공유90초**를 유지한다. 정리5초, 요청부터 정리까지120초, 전체 phase1200초를 넘기지 않는다. 뒤늦게 시간·token 상한을 늘려 같은 실행을 성공으로 바꾸지 않는다.
- `enable_thinking=true`, `reasoning_format=deepseek`, `reasoning_budget_tokens=512`를 명시한다. 계산상512사고+384최종+32framing이지만 각각의 엄격한 native 구간 제한을 뜻하지 않는다. budget 종료의 UTF-8 처리·태그 삽입과 설정 직렬화 한계를 기록한다. [고정 budget 상태 기계](https://github.com/ggml-org/llama.cpp/blob/d81235049384534c167caea52b85a694f6103d14/common/reasoning-budget.h).
- 최종 `message.content`는 native tokenizer의 `add_special=false, parse_special=false`로 다시 세고384초과면 수용하지 않는다. 이는 최종 문자열의 **재토큰화 수치**이며 생성 구간의 토큰 수라고 부르지 않는다. 원시 반환 token IDs·native tokens_predicted·종료 태그 관측을 별도로 기록하고 모호한 분할은 검증 성공으로 표현하지 않는다.
- JSON 자르기·수선·재질문은 없다. raw 응답은 공개 가능한 합성 자원 실험 artifact에만 제한적으로 보존하고 운영 로그에는 쓰지 않는다. 향후 의미 판정자는 최종 답변만 보고 사고 내용·mapping을 보지 않는다.

기존 C3 부하 metadata를 단순 적용한928token 예상은 약81~86초다. 새 경로의 실측치도, 지연 보장도 아니다. 여유가 작으므로 품질 자료보다 이 자원 검증을 먼저 한다.

## 고정 뒤 한 번만 실행할 neutral2

1. 새 짧은 합성 정상 요청1회: 사고/최종 분리, 정확한 template, 유효 JSON과 최종 수용 한도, 자연 종료, 실제 greedy/cache/identity 확인.
2. 새 합성 부하1회: 상한 근처 입력과928출력 부하 확인. 강제 length 종료는 부하에서만 허용하고 품질 성공으로 세지 않는다. 목표 부하를 소비하지 못하면 최대 부하 검증 미완료다.

두 요청 뒤 소유 process 종료, 동일 identity metadata 재시작1회·추가 생성0, 재종료와 로그0bytes를 검사한다. 같은 결과 디렉터리의 중복 실행은 거절한다. 실패·미실행은 그대로 남긴다. 새 source/tooling과 입력 계약을 검토·커밋한 뒤에만 actual 실행하며, 기존 C0~C3·M5-B·최종test는 사용하지 않는다.

## 다음 단계의 조건

이번에는 얇은 새 어댑터·launcher·resource probe와 합성 계약 검사를 구현한다. 기존 동결 helper를 읽기 전용으로 재사용하되 수정하지 않고 새 평가 플랫폼을 만들지 않는다. 자원 통과 뒤에만 별도 full-scope 품질 policy와 새 자료를 고정한다. 새 calibration6 완전 적합6/6 뒤 격리 validation8을 열고8/8을 요구한다. 현재 이 계약의 품질 호출은0이며 단일 호출 품질14회의 실행 계획도 아직 등록하지 않았다. 서비스 자동 채택·사용자 검수 대행은 없다.
