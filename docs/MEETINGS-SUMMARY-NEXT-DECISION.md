# 회의 요약·답변의 다음 결정

2026-10-26 · 제안만 작성 · 기존 Astra xhigh · qualified-summary-v1 HOLD 유지

**다음 행동 하나: 공식 Ministral 3 3B Instruct Q5_K_M로 개발 원문 4개의 완전한 요약·자연어 답변을 소규모 오프라인 측정한다.** 다른 계열의 생성 능력을 확인하는 제안이며, 9B보다 우수하다는 결론은 아니다. 다운로드·구현·모델 실행은 부모 수용·공개 후 별도 배정한다.

[기존 계획](MEETINGS-SUMMARY-CONTENT-NEXT.md)의 qualified 4/4 선행조건은 **그 표현 후보에 대한 HOLD**다. 새 모델의 기존 flat 경로 능력 측정에 4/4 사전 합격 조건으로 옮기지 않는다. [source-only feasibility](../experiments/results/meetings-summary-qualified-feasibility-v1.json)는 flat 가능 2/미확인 2, qualified 가능 1/미확인 3이며 미확인≠불가능이다. 같은 AI의 8회 witness는 서비스 모델 출력이나 독립 검증이 아니며 다시 작성·재채점하지 않는다.

안전한 집계에서 flat은 구조 문제 1건·의미 문제 1건(겹침 0), qualified는 구조 1건·의미 3건(겹침 1)이다. 최대치는 각각 6 claims/5 evidence/621 chars, 7/5/557이며 원래 한도는 6/4/1200이다. 문자 길이 부족은 관측 원인이 아니다. 한도 초과 witness의 부분 통과를 전체 통과로 승격하지 않는다.

[실제 mode 결과](../experiments/results/meetings-summary-mode-review-v2.json)는 유효 초안 1개·핵심 충족 0/1인데, [자체 검토](../experiments/results/meetings-summary-mode-self-review-v2.json)는 5개 주장 모두 supported·coverage sufficient였다. 생성 오류와 검토 과신을 분리해야 한다. 한 사례로 모드 우열·일반 오류율을 계산하지 않으며 [정렬 실패](../experiments/results/meetings-summary-mode-structural-diagnosis-v2.json)는 당시 계약 위반으로 보존한다.

| 대안 | 판단 |
|---|---|
| flat evidence 4→5 등 prospective 조정 | 구조 문제 1건의 근거는 있으나 의미 문제 해결 근거가 없어 보류 |
| 독립 무료 로컬 근거 검토 모델 | 과신 측정에 유용하지만 완전한 생성본 부족을 직접 해결하지 못해 다음 우선순위로 보류; 다른 계열도 정답 판정기는 아님 |
| 다른 무료 로컬 생성 모델 1개 | **선택**. 같은 완전성 요구에서 새 내용·시간·메모리 증거를 얻으며 프롬프트 미세변형 반복을 피함 |

후보는 [Mistral 공식 GGUF](https://huggingface.co/mistralai/Ministral-3-3B-Instruct-2512-GGUF)다. 카드에 Apache-2.0과 한국어·영어 지원이 명시돼 있다. 한국어 회의·영문 용어 혼합의 Q5 정확도는 미확인이고, 작은 모델이 기존 9B보다 의미 성능이 낮을 가능성도 있다.

- 파일: `Ministral-3-3B-Instruct-2512-Q5_K_M.gguf`, revision `fc774f009f0c62a186f48e870fd6295b36f63779`.
- [공식 파일 metadata](https://huggingface.co/mistralai/Ministral-3-3B-Instruct-2512-GGUF/blob/main/Ministral-3-3B-Instruct-2512-Q5_K_M.gguf): 2,474,178,720B / SHA-256 `e23dd88b0e0951d3f5784d6d4092210cda2b006b251f33b226b283a6c9d1f6bb`.
- 런타임: 현재 [문서화된 b11429](../data/models/meetings-generation-qwen35-v1.json), commit `d81235049384534c167caea52b85a694f6103d14`. [해당 소스의 mistral3 구현](https://raw.githubusercontent.com/ggml-org/llama.cpp/d81235049384534c167caea52b85a694f6103d14/src/models/mistral3.cpp)은 지원 근거이며 Windows 바이너리 로딩 성공은 미확인이다.
- 제안 설정: 텍스트 전용, GGUF 내 tokenizer/template, ctx 6144·parallel 1·FP16 KV·greedy·GPU layers 99(전체 offload 요청, 실제 배치 별도 기록). vision projector·다른 tokenizer 혼합·자동 quantization/CPU fallback은 사용하지 않는다.
- 자원: 6GB GPU 한 대, 시작 직전 가용 RAM ≥10GiB와 모델 단독 소유 확인. [공식 config](https://huggingface.co/mistralai/Ministral-3-3B-Instruct-2512/blob/main/config.json)의 26 layers/8 KV heads/head_dim 128이면 KV는 이론상 624MiB다. 가중치와 합쳐 시도할 근거는 있으나 CUDA·연산 버퍼·다른 앱 메모리는 별도여서 **실제 적합성은 미확인**이다.

구현은 **기존 소유 런타임의 명시적 후보 프로필 seam과 작은 요청 어댑터**로 한정한다. 현재 `probe_meeting_summary_mode.py` launcher는 Qwen manifest/28 layers/argv에 고정돼 있으므로 단순 파일 교체는 불가하다. 후속 opt-in에서 기존 Qwen 등록·기본 동작을 보존하고 lease·소유 핸들·cleanup을 재사용한다. runner/수명 관리 복제나 새 validator를 만들지 않는다. 순수 `source_payload/summary_messages/parse_draft/parse_review`와 QA `grounded_answer_refs`를 그대로 사용한다. QA ID mapping은 원문 unit의 정확 span으로 고정한다.

제안하는 실행 범위는 다음 다섯 항목이다.

1. 이미 허용된 개발 원문 **4개 모두**(관련 프로젝트 2계열)를 사용한다. 기존 source/summary criteria는 유지한다. 출력 전 별도 원문 검토자가 질문 1개/원문과 정답 근거를 고정하며, private witness는 모델 예시로 주지 않는다. 질문 작성자·설계·실행과 판정 역할을 분리한다.
2. 후보·template·지시문을 하나씩 고정하고 원문별 요약 1회와 답변 1회를 생성한다. 요약은 기존 flat 1–6 claims·claim당 1–4 evidence·240/1200 chars·정확 span/ID·정렬 계약 그대로다. 정렬 보정도 섞지 않는다.
3. 요약 생성 768+필수 자체 검토 128 tokens·공유 120초·template 포함 입력 4096을 유지한다. QA는 **새 오프라인 측정의 제안 한도**로 답변 256 tokens/60초·입력 4096이며 질문·원문 전체·근거 인용을 사용한다. 최대 8회 생성+4회 요약 자체 검토다. 전체 원문 QA 능력 측정이며 검색·권한·서비스 QA 통과 증거가 아니다.
4. 원문이 입력 한도에 안 들어가거나 로딩·자원 조건이 맞지 않으면 기록하고 축약·샘플 교체·자동 설정 변경·재생성을 하지 않는다. 내용/형식 실패는 보존하고 다른 고정 항목을 측정하되 자원·실행 안전 실패면 남은 항목은 미실행으로 끝낸다.
5. 원문 접근을 배정받은 독립 판정자는 모델 정체·자체 검토·성능을 보기 전 개별 판정을 잠근다. 전체 원문 지지, 선택 근거 지지, 핵심 누락, 한국어 가독성 및 QA의 정확성·충분성·인용 지지를 평가한 뒤 자체 검토와 비교한다. 기계 거부 출력은 별도 진단으로 보존하며 서비스 유효 초안으로 세지 않는다.

결과는 **요약 4개·답변 4개 고정 분모**로 기계 유효성/의미 충족, 실패·미실행, 토큰·지연·최대 VRAM/RAM을 보고한다. 기존 9B와 소스가 달라 A/B 우열·개선율을 주장하지 않는다. 4개 모두 내용과 자원 요구를 충족하면 서비스 통합 후보로 검토하고, 일부 실패면 원인을 구분해 반환한다. 자동 프롬프트 순환이나 모델 연속 시도를 시작하지 않는다.

무료 로컬만 제안한다. 추가 파일 약 2.47GB, 준비·측정 **30–60분 예상**(네트워크/호환성에 따른 추정), 로딩 후 호출 한도 합계 최대 12분이며 독립 내용 검토 시간은 별도다. 유료 API·클라우드·배포는 0이다.

최종 목표는 완전한 요약·자연어 답변, 권한에 맞는 근거, 저장·수정·복구, 실제 UI와 사람 검토까지다. 이 개발 측정으로 일반화·배포·Phase1 완료를 선언하지 않는다. [source 검토](../experiments/results/meetings-summary-qualified-source-review-v1.json)와 [mode 분석](MEETINGS-SUMMARY-MODE-ANALYSIS.md)의 HOLD·실패·기준 및 원래 8회 witness는 불변이다.
