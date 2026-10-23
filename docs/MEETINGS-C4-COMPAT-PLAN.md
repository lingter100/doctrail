# C4-P0 별도 호환성 후속 — 같은 자원 예산의 최종 판정

2026-10-15. 실제 Astra xhigh `free_qa_candidate_review`의 고정 native source 검토를 따른다. 원본 C4-P0는 [실패 종료](MEETINGS-C4-RESOURCE-RESULTS.md) 상태로 보존한다. 이번 것은 새 resource followup ID `meeting-thinking-c4-compat-resource-v1`이며 품질 후보나 서비스 채택이 아니다. 등록 시 새 source/tokenizer/native/품질 자료는0이다.

## 확인한 원인과 선택

고정 native parser의 반복 최소값 한도는2000이다. 원본의 `minLength:10000` 변환은 이 한도를 넘었고 parser가 전체 grammar를 직접 stderr로 출력했다. 앞선 설계 검토는 schema 변환까지만 확인하고 parser 한도를 놓쳤다. `--log-disable`는 공통 logger에 적용되므로 직접 `fprintf`를 막지 못한다. [반복 한도](https://github.com/ggml-org/llama.cpp/blob/d81235049384534c167caea52b85a694f6103d14/src/llama-grammar.cpp#L13), [거부 조건](https://github.com/ggml-org/llama.cpp/blob/d81235049384534c167caea52b85a694f6103d14/src/llama-grammar.cpp#L656-L662), [직접 출력](https://github.com/ggml-org/llama.cpp/blob/d81235049384534c167caea52b85a694f6103d14/src/llama-grammar.cpp#L719-L722).

정상 실행의 native decode521tokens/53.162초는 약9.781tokens/s였다. 동일 속도 단순 적용 시928decode만94.875초로90초보다 길다. 이는 위험 추정이며 미측정 stress 시간이나 불가능성 증명이 아니다. 입력5050의 prefill도 미측정이다. 총672/요청사고256으로 줄이는 대안은 계산량뿐 아니라 사고 공간을 바꾸므로 이번 호환성 실패만을 근거로 선택하지 않는다. **원래928/512/90초를 유지해 별도 한 번의 자원 게이트로 판단한다.** 실패 뒤 예산을 단계적으로 바꾸며 재시도하지 않는다.

## 새로운 입력과 구현

부하는 공백 하나로 연결한 `z`2048개의 고정 문자열을 `padding.const`로 쓴다. 값4095 ASCII bytes, 최소 완성 JSON4109bytes다. `minLength`, `pattern`, 큰 반복 수를 사용하지 않는다. 고정 converter는 const를 literal로 변환한다. 실제 바이너리의 수용은 아직 확인하지 않았다. [const 변환](https://github.com/ggml-org/llama.cpp/blob/d81235049384534c167caea52b85a694f6103d14/common/json-schema-to-grammar.cpp#L824-L826), [const 분기](https://github.com/ggml-org/llama.cpp/blob/d81235049384534c167caea52b85a694f6103d14/common/json-schema-to-grammar.cpp#L888-L889).

새 짧은 정상 합성 문구와 새 기계 padding 부하 문구를 코드에서 고정한다. source 커밋/CI 뒤 캐시 tokenizer로 두 입력과 고정 완성 JSON을 한 번 준비한다. 완성 JSON의 정확한 재토큰 수는 아직 미측정이며 **928초과**여야 한다. 이 조건을 못 채우면 준비 실패로 종료하고 literal을 늘려 재탐색하지 않는다. 완성 JSON 재토큰 수를 실제 생성 구간 수로 해석하지 않으며 native 부하는 정확928출력/length종료를 별도로 요구한다.

기존43파일과 `ThinkingGenerator`는 수정 없이 재사용한다. 원래 generation_protocol은 그대로 두고 새 followup ID를 구분한다. NEW launcher/probe와 합성 테스트만 작성해 새 freeze에 모든 의존 파일을 포함한다. 일반 Q&A policy,Java,서비스 worker는 변경하지 않는다.

새 launcher는 stdout/stderr 합친 PIPE를 전용 drain으로 EOF까지 계속 읽되 작은 고정 chunk를 읽자마자 버린다. 원문 내용이나 예외 원문을 파일/console에 기록하지 않고 전체 emitted byte 수·EOF·read/join상태만 남긴다. 일정 크기에서 읽기를 멈추거나 오류를0으로 취급하지 않는다. 통과는 **emitted0bytes + EOF + read/join오류0**이다. 파일이 없다는 사실로0로그 조건을 대신하지 않는다. process 정리와 drain join은 기존 cleanup5초 안에 완료해야 한다.

## 실행 계약과 한계

- 같은 캐시 가중치/runtime, GPU24,context6144,input≤5120,greedy/seed0/cacheoff/parallel1.
- 전체 생성928, 요청사고512, 정상 최종재토큰384, 공유요청90초/정리5초/요청부터정리120초/phase1200초. 512/384는 독립 native hardcap이 아니다.
- NEW source/CI → 공식 offline 준비 → 새 plan 커밋 → 새 output에서 normal1/stress1 한 번. warmup/retry/fallback/download/품질0.
- 두 요청이 모두 통과하면 동일 identity metadata 재시작1회와 재정리, 추가생성0. 첫 실패에서는 다음 호출/복구를 진행하지 않는다.
- 원본2dispatch/1완성 + 새최대2dispatch = 누적최대4dispatch/3완성. 원본 실패의 재실행이나 소급 성공이 아니다.
- 성공해도 새 full-scope 품질 policy와 freshcal6/6→격리val8/8은 별도다. 일반 문서·복수 회의·한영 질문·인용/보류 범위를 좁히지 않는다. 설계/구현 역할은 독립 품질 judge에서 제외한다.

유료0·사용자검수0·공개서비스배포0이며 전체goal active,Phase1/PR14 미완료/draft를 유지한다.
