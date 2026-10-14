# C2 새 자료 준비와 실행 경계

2026-10-14. 현재는 입력 준비 단계다. 생성 답변 비교와 Java/React 서비스 채택은 아직 수행하지 않았다. 변하는 진행 상태는 [STATUS](STATUS.md), 고정된 실험 조건은 [비교 계획](MEETINGS-C2-COMPARISON-PLAN.md)을 따른다.

## 고정 순서

1. 출처 계열을 `8a424be`에 먼저 등록했다.
2. 비교 구현41파일은 `8582e60`의 source-freeze-v2로 고정했다. 첫 v1의 Linux fixture 실패와 수정 이력은 보존한다.
3. 출처 처리18파일은 `f952d95`까지의 source-processing-v2로 고정했다. 원래 RST 출처를 그대로 두고 명시적으로 txt 처리한다.
4. Calibration 공개2+합성3 원문을 별도 검토하고 실제 Java/Python 전체55청크를 대조한 뒤 `65f3358`에 고정했다.
5. 새 질문8개·필수 사실29개·전체 청크 선택을 작성하고 부모가 별도로 검토했다. `c9c6514`의 item-freeze-v1은 공식 tokenizer 실행보다 앞선다.
6. 원래 질문·context payload를 그대로 두고 공식 로컬 tokenizer 입력 준비를 수행했다. 모델 생성과 추가 다운로드는0이다.

`65f3358`과 `c9c6514`는 각각 push/PR의 backend·java-service·web 검사를 모두 통과했다. 이것은 문항이나 모델 답변의 의미적 정확성을 증명하지 않는다.

## Calibration 준비 결과

| 항목 | 확인 결과 |
|---|---|
| 질문 출처 | 공개 정책4·AI 합성 조직4 |
| 질문 언어 | 한국어4·영어4 |
| 답변 가능성 | 답변가능6·필수 정보 부족2 |
| 복수 사실 / 필수 복수 문서 | 답변가능6 / 2 |
| 원문 context | 청크20회·고유15개, 항목당2~4개 |
| 별도 AI 문항 검토 / 사용자 검수 | 8 / 0 |
| 줄 단위 기준 입력 | 1,180~3,140 tokens |
| 문단 단위 후보 입력 | 1,290~3,730 tokens |
| 공통 입력 상한 | 4,096 tokens, 16개 모두 통과 |
| 실제 생성·품질 판정 | 0 |

작성 당시 `AI_DRAFT_PREREVIEW_PENDING`과 검토0 영수증은 변경하지 않았다. 뒤에 수행한8건 검토는 별도 파일이다. 작성자는 generic 비교 계약의 정책 차이를 보았고 부모 검토자는 후보 구현에 참여했다. 따라서 작성자와 다른 검토라는 사실과 후보를 모르는 독립 출력 판정은 구분한다. 두 역할 모두 후속 독립 출력 scorer에서 제외한다.

누락 정보는 선택한 몇 청크뿐 아니라 채택한 전체 계열 원문에서 확인했다. 질문에 답이 있는데 일부러 해당 청크를 숨겨 보류 문제를 만들지 않았다. 여러 청크를 같은 문서의 여러 source로 세지 않았다. 다만 목적에 맞춰 고른 작은 표본, 공개 문서의 사전학습 가능성, 합성 문서의 명확한 상태 표현과 AI 간 공통 편향은 남는다.

## 모델을 실행하지 않는 재현

저장소 루트에서 잠긴 Python3.11 환경과 이미 준비한 공식 tokenizer cache를 사용한다. 출력 폴더는 존재하지 않는 새 경로여야 한다. 다운로드나 생성 모델 호출을 허용하는 명령이 아니다.

```powershell
uv run --locked --group retrieval --no-sync python -m scripts.prepare_meeting_blocks_inputs --draft data/evaluation/meetings-c2-calibration-v1/draft.json --output .local/c2-calibration-inputs-replay --phase calibration
```

[저장 입력](../data/evaluation/meetings-c2-calibration-v1/input.json)과 [token 영수증](../data/evaluation/meetings-c2-calibration-v1/token-receipt.json)은 실제 준비 원본의 바이트 사본이다. 원문·질문·metadata·순서를 고치지 않고 input/receipt hash와 pinned tokenizer 식별을 대조한다. 입력 상한에 실패하면 청크를 자르거나 문항을 교체하지 않는다.

원문 수집·정규화·전체 Java 대조는 [source 처리](MEETINGS-C2-SOURCE-PROCESSING.md), [literal RST 처리](MEETINGS-C2-PLAINTEXT-SOURCES.md), split별 manifest와 출처 고지를 따른다. 원래 helper receipt의 미검증 flag를 사후 수정하지 않고 별도 실제 Java receipt를 연결한다.

## 남은 실행 조건

격리 validation 원문·문항·oracle·별도 검토·동일한 token 준비가 필요하다. 부모와 후보 구현자는 그 본문을 읽지 않는다. 양 split의 입력과 oracle, 검토 역할, 익명화 seed, 출력 경로, runtime 식별을 하나의 실행 계획으로 고정하기 전에는 품질 추론을 시작하지 않는다.

Calibration은 같은8문항에 두 방식16회, 검증은 선택 조건을 만족한 후보만12회다. 동일 자료에서 수정·재시도하지 않는다. C2의 완전 적합8/8·개선1개 이상·퇴보0 및 실행 무결성 조건이 충족돼야 검증으로 진행한다. 실제 검증12/12 이후에도 별도의 Java/React 운영 검사가 남는다. 유료 사용·공개 서비스 배포·사용자 검수는 수행하지 않았다.
