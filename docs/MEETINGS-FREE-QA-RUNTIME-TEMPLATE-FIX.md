# 원본 template와 서버 반환 표현의 검증

후속 실측: 수정 소스의 [새 v2 시작 진단](MEETINGS-FREE-QA-STARTUP-V2-RESULTS.md)은 health·props1회 검증·종료·전체 보존 확인을 통과했다. 원래 실행의 응답 해시를 소급 확정하지 않으며 생성·QA 품질 평가는 아직 수행하지 않았다.

2026-10-29. [실제 시작 진단](MEETINGS-FREE-QA-STARTUP-RESULTS.md)의 설정 오류를 조사하면서 **고정 런타임의 표현 변환과 현재 해시 검사의 불일치**를 확인했다. 실제 응답 본문은 보존하지 않아 그 실행에서 받은 정확한 해시는 여전히 미확정이다. 이 문서의 변환 해시는 공개 소스로 계산한 기대값이다.

## 확인한 코드 경로

실행 커밋2bda334의 어댑터는 서버가 반환한 template의 UTF-8 해시를 승인된 원본 GGUF template 해시와 직접 비교한다. 실행기는 내장 template와 `--jinja`를 선택하며 별도 template를 덮어쓰지 않는다.

고정된 llama.cpp `d81235049384534c167caea52b85a694f6103d14`에서는 [내장 template 선택](https://github.com/ggml-org/llama.cpp/blob/d81235049384534c167caea52b85a694f6103d14/common/chat.cpp#L697-L757) 뒤 [lexer가 처리한 source를 저장](https://github.com/ggml-org/llama.cpp/blob/d81235049384534c167caea52b85a694f6103d14/common/chat.h#L48-L66)하고 [props로 반환](https://github.com/ggml-org/llama.cpp/blob/d81235049384534c167caea52b85a694f6103d14/tools/server/server-context.cpp#L4505-L4537)한다. [lexer 처리](https://github.com/ggml-org/llama.cpp/blob/d81235049384534c167caea52b85a694f6103d14/common/jinja/lexer.cpp#L30-L53)는 CRLF/CR 변환과 끝 LF 하나 제거를 포함한다. 승인된 이번 Qwen 원문에는 CR이 없고 끝 LF가 있으며, 다른 조건부 source 변경은 적용되지 않는다.

| 표현 | 바이트 | SHA-256 |
| --- | ---: | --- |
| 승인된 원본 | 2509 | `d5495a1e5db0611132a97e46a65dbb64a642a499421228b9c8b93229097fa9a4` |
| 고정 소스에서 계산한 서버 기대값 | 2508 | `4e9918361c284a93880606d182d64da6a9fe97cdc1f5c5a78c1c8840444246fc` |

따라서 원본 해시만 기대하는 검사는 이 런타임이 만들 것으로 계산되는 정상 표현을 거부한다. 이것이 이번 응답의 실제 바이트였다는 주장은 하지 않는다. 이전 중립 실패의 정확한 원인도 여전히 미확정이다.

## 좁은 보완과 검증 기준

원본 메타데이터·모델·런타임 핀은 유지한다. 정확한 Qwen 모델, 런타임 tag/전체 commit, 원본 template 해시·크기 조합에만 위 서버 기대값을 적용한다. 받은 응답은 그 기대값의 크기와 해시에 엄격히 비교한다. 알 수 없는 조합에 변환 수용을 확대하거나 응답의 공백을 임의로 정리하지 않는다. 다른 모델의 기존 검증과 실행 제한도 유지한다.

수정 범위는 어댑터와 기존 QA 테스트 파일이다. 공개 template fixture를 테스트 안에 두어 CI가 로컬 모델 파일에 의존하지 않게 한다. 올바른 표현, 원본 LF가 붙은 표현, 추가 LF·CRLF·내용/공백 변경·잘못된 자료형·다른 조합을 구분하고 기존 별칭·빌드·설정 오류와 시작 진단 경로를 회귀 검사한다. 구현·검사·독립 변경 검토·게시 소스 CI 뒤에 새 실제 측정을 판단한다.

두 소스 파일의 보완을 완료했다. 신규 집중 검사19개와 이를 포함한 QA/시작 진단273개가30.90초에 통과했고 최종 Ruff도 통과했다. 최초 Ruff의 빈 줄1개 오류와 검사 당시 원본을 보존했으며 최종 공백 수정은 AST 동일성을 확인했다. [검증 기록](../experiments/results/meetings-free-qa-runtime-template-repair-v1.json)의 독립 변경 검토는 차단 0·권고 0이다. 새 게시 소스 CI는 다음 단계다. 새 native 실행·등록·once·비공개 질문은 없으며 소비된 진단은 재실행하지 않는다. 관련 검사가 통과해도 실제 props 수용·토큰화·생성·회의 답변 품질을 검증한 것은 아니다.

분석은 Astra xhigh가 수행했고 부모는 최종 기록 6참조와 근거의 25참조를 확인했다. 원본 진단 영수증은 `01375965a109d7fa0c15b99ca434a68a9084b9e63f92378df15c4013d99e4a54`다. 실제 사용자가 template를 검수했다고 기록하지 않는다.
