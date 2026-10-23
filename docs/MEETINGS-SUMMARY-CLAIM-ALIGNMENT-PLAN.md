# 완전한 회의 요약과 주장별 근거 정렬의 다음 후보

2026-10-23. 공개 집계와 generic 코드에 근거한 **부모 설계 검토를 마친 후보**다. 구현은 부모의 별도 배정으로 시작하며 실제 실행은 별도 once 배정 전까지 허용되지 않는다. 목표는 핵심 내용을 충분히 담은 읽기 쉬운 한국어 요약과 각 문장 전체를 뒷받침하는 인용을 함께 만드는 것이다.

## 확인된 문제와 아직 모르는 것

- [v2 독립 결과](../experiments/results/meetings-grounded-summary-review-v2.json)(SHA `109d4d00…`)의 후보3·주장17은 원문전체 지원13/부분1/애매3, 선택인용 지원9/부분7/애매1, 핵심 충분1/불충분2다. 인용 위치34개는 모두 정확하지만, 모든 주장이 원문전체에서 완전히 지원된 후보는0이다.
- 중첩 가능한 이슈는 선택인용의 주장 구성요소 누락6·무관 인용4이며 제안/채택, 대상, 조건과 지시대상 혼동도 남았다. 따라서 인용 ID만 교체하거나 문장을 덜 말하게 만드는 것으로 완전한 요약 문제를 해결했다고 할 수 없다.
- [v1 독립 결과](../experiments/results/meetings-grounded-summary-review-v1.json)도 핵심 충분0/2였다. v1은 이미 evidence-before-text와 조건·예외·시점 보존 지시를 썼고, [v2 설계](MEETINGS-GROUNDED-SUMMARY-NEXT.md)는 같은 호출 안에 관계 graph를 추가했다. 표본·검토 맥락이 달라 v1→v2 개선율을 계산하지 않는다.
- [v1 자기검토 대비](../experiments/results/meetings-grounded-summary-self-review-v1.json)에 이어 [v2 비교](../experiments/results/meetings-grounded-summary-self-review-v2.json)(SHA `40a78c80…`)도 불일치를 확인했다. 동일 judge의 독립 판단 잠금 후 입력10개 불변 상태로 비교했으며 새 의미 판단·기준·인간 검수는0이다. 모델 supported15 중 선택인용 잠금과 지원 일치9/부분5/애매1이고, uncertain2는 잠금상 부분2다. 모델은 coverage3건 모두 sufficient였지만 독립 잠금은2건 insufficient였다. 부분·애매를 unsupported로 바꾸거나 거부 이유를 추정하지 않는다. 이 결과는 검토 accepted를 품질 증명으로 삼을 수 없음을 뒷받침하므로, 완전한 초안을 실제로 수정하는3회 후보와 독립 paired 평가 선택을 유지한다. 추가 재작성의 효과는 여전히 미확인 가설이다.
- [v2 비용 관측](../experiments/results/meetings-grounded-summary-performance-v2.json)(SHA `8208a4aa…`)에서 요약 생성3·검토3은 모두 EOS였다. 생성 출력335–408/상한768, 검토35–42/상한128, 분석 observer 구간61.000–68.281초다. 토큰·시간 상한 때문에 의미가 빠졌다는 증거는 없다.

## 선택: 기존 초안 → 원문 기반 재작성1회 → 최종 검토

- 새 명시 후보 `grounded-summary-v3`를 `batch-v2`에서만 선택한다. 기존 v1/v2와 실패 결과는 그대로 보존한다. **고정된 추가 재작성1회**로 생성과 대조·수정을 나누며, 최종 검토 거부 후 복구·재시도는0회다.
- 첫 초안은 기존 v1의 전체 원문 생성 prompt·flat grammar·`parse_draft`를 그대로 쓴다. 이미 있는 `{status,claims:[{evidence,text}]}` 형식을 재사용하므로 새 관계 enum·graph·계획 schema를 추가하지 않는다. 이 초안은 검토되지 않은 중간 산출물이며 저장/UI 성공으로 취급하지 않는다.
- 중간 `alignment`에는 모든 source unit과 gap, 제목, 초안의 문장과 정확한 unit ID를 전달한다. 초안과 원문 모두 untrusted data이며 초안 인용은 탐색 제한이나 사실 보증이 아니다. 전체 원문을 다시 대조해 **잘못되거나 애매한 주장 수정, 인용 교체·보충, 누락 핵심 추가, 필요시 문장 분할·통합·재정렬**을 허용한다.
- 재작성은 원문의 핵심 결정·제안·미결 상태·조건·예외·시점·범위를 보존한 완성 요약 전체를 반환한다. 불명확한 주체·대상을 문맥 없이 남기거나 제안을 결정으로 바꾸지 않는다. 자연스럽게 연결된 짧은 한국어 문장을 쓰며, 기계 필드나 관계 목록을 독자에게 노출하지 않는다.
- 사실이 아닌 초안 내용을 고치거나 없앨 수 있지만, 인용에 맞추려고 필요한 핵심 내용을 삭제해 통과하는 전략은 목표 위반이다. 원문이 불확실하면 그 불확실성을 요약한다. 충분하고 지원되는 최종본을 기존 한도에 표현할 수 없으면 기존 abstain/실패를 반환한다. 보존·충분성은 의미 판단이며 코드가 자동 증명한다고 하지 않는다.
- 중간 출력도 기존 flat grammar·`parse_draft`로 새 최종 claims를 만든다. 초안의 개수·ID·인용을 강제로 유지하지 않는다. 각 최종 문장에 필요한 실제 근거1–4개를 원문 순서로 연결하며, 인용하지 않은 원문이 문장 일부를 지지한다는 이유로 지원 판정을 대신하지 않는다.
- 마지막 호출은 기존 v1 `REVIEW_PROMPT`·`REVIEW_GRAMMAR`·`parse_review`를 그대로 사용한다. 전체 원문과 **최종본만** 입력하고 초안·수정 이유·관계 계획을 주지 않는다. 선택 인용만으로 문장 전체가 supported이고 전체 원문 대비 coverage가 sufficient일 때만 기존 `grounded-review-v1` accepted gate를 통과한다.
- final review의 unsupported/uncertain/insufficient, 중간 abstain, schema/입력/EOS/시간 실패를 덮지 않는다. 최종검토 없이 초안 또는 재작성본을 저장하는 fallback, 거부 후 다른 초안 선택, 성공까지 반복은 없다. 단계별 입력·출력·첫 실패는 기존 observer로 보존한다.

## 대안과 이 후보의 한계

- 인용만 재선택하는 별도 호출은 선택 근거의 누락을 겨냥하지만 원문전체 부분/애매4건과 핵심 불충분2건을 고칠 수 없어 제외한다. 단순 prompt 강화는 기존 지시와 겹치며, graph 확대는 표현·검사 비용을 늘릴 뿐 의미 정합성의 증거가 없다.
- 검토만 엄격하게 하는 수정은 불완전한 요약의 출력을 막아도 충분한 요약을 만들지 않는다. 독립 모델·더 큰 로컬 모델은 추후 가능하지만 이번에는 모델·추론 방식·예산 변수를 함께 바꾸지 않는다. 발췌만 하는 요약이나 빈 답변 증가를 대체 성과로 세지 않는다.
- 이 후보도 같은 모델이 같은 오해를 반복하거나 초안에 끌릴 수 있다. 후행 재작성의 효과는 아직 가설이며, 호출을 추가했다는 사실이나 final review의 accepted만으로 품질 개선을 주장하지 않는다. 다음 실험은 같은 요청의 초안과 최종본을 독립적으로 비교해 이 가설을 구분한다.

## 사전 명시 예산과 구현 경계

- 새 후보만 요약 completion 상한을2→3으로 바꾼다: `generation`768 + `alignment`768 + `review`128, 최대1664 output token(기존896). metadata의 `extra_completion_cap=3`, `repair_calls=1`과 alignment prompt/grammar hash·출력 상한·단계 순서를 고정한다. 기존 v1/v2 metadata와 prompt/grammar 계약은 바꾸지 않는다.
- 각 호출은 실제 template 포함 입력4096 이하, 분류를 포함한 분석 전체는 **같은120초 deadline**을 공유한다. 최종 claims1–6/문장240/합1200/인용4, 공개 `summary_version=2`, answer90초, 전체 원문과 기존 분류·answer 정책은 유지한다. 단계마다 남은 시간과 전체 입력을 검사하며 truncation이나 deadline 재시작은 없다.
- 관측된 v2 생성 transport22.922–27.766초를 분석 구간에 한 번 더 더하는 단순 가정은 약83.9–96.0초다. 이것은 추가1회 시험의 비용 근거일 뿐 예측·상한·SLO가 아니다. 새 alignment는 더 긴 입력과 다른 출력을 가지며, 생성 cap을 모두 쓰면120초를 넘을 수 있다. 시간·입력·출력 cap을 실패 후 늘리지 않는다.
- 1차 구현 경계는 기존 `src/doctrail/meeting_grounded_summary.py`와 `tests/test_meeting_grounded_summary.py` 두 파일이다. 후보 분기, alignment 메시지 작성, metadata, runtime 단계 연결만 추가하고 기존 parser/projection·full-span→unit-ID 대응을 재사용한다. 새 module·validator·runner는 만들지 않는다.
- 직접 연결점은 `_summary_contract`/`summary_metadata`, `GroundedSummaryGenerator.summary_complete`, `GroundedSummaryRuntime.analyze`다. 현재 `summary_complete`의 generation 이외를 review로 보내는 분기를 **명시적인 단계→cap/grammar 매핑**으로 바꿔 alignment가128-token review grammar로 실행되는 사고를 막고 미등록 단계는 호출 전에 거부한다.
- runtime은 기존 분류 후 generation→alignment admission/completion/parse→review admission/completion/parse 순서를 수행한다. 모든 admission·completion·observer에 같은 deadline을 전달한다. normal과 observed generator가 같은 경로를 쓰고 `grounded_summary_alignment` telemetry, `last_assembly.stage`, 실제 completion 수와 최종 projection을 함께 확인한다.
- 독립 코드 검토 후 연결 범위는 기존 `src/doctrail/meeting_service_rag.py`, `scripts/serve_meeting_service_rag.py`, `scripts/serve_meeting_rag_service.py`, `scripts/run_meeting_rag_acceptance.py` 및 대응 `tests/test_meeting_service_rag.py`, `tests/test_meeting_service_rag_launcher.py`, `tests/test_serve_meeting_rag_service.py`, `tests/test_run_meeting_rag_acceptance.py`까지다. 후보 allowlist·identity/hash·health·manifest·telemetry 전달만 다루고 이미 공통 분기로 전달되는 파일은 불필요하게 수정하지 않는다.
- Java/React·DB·coverage·분류·frozen77·공식 cal/val/test·과거 원본은 수정하지 않는다. 공개 저장/근거 이동/편집은 기존 summary v2 흐름으로 검증한다. 실제 호환 문제가 드러나면 원인과 추가 경계를 별도로 검토한다.

## 합성 검사와 한 번의 구분 가능한 실제 실험

1. generic 합성 입력으로 초안의 틀린 제안/결정·주체·조건을 재작성 출력에서 수정하고, 다른 unit의 빠진 핵심과 근거를 추가하는 흐름을 검사한다. 문장 분할·통합·개수 변경 후 최종 ID/인용/legacy projection 일치, 반복 문구의 서로 다른 offset, 원문과 gap의 모든 단계 보존을 확인한다. mock 응답은 흐름 증거이며 의미 추론의 성공 증거가 아니다.
2. 단계별 잘못된 ID/schema/길이·입력 초과·비EOS·abstain·timeout·검토 거부를 검사한다. final review 없이는 저장0, 실패 이후 completion0, 성공 경로 요약 호출3/재작성1/최종검토1, 같은 deadline·observer/normal 동등성, v1/v2의 기존2call 및 prompt/metadata 회귀를 확인한다. 불완전한 재작성에 fake final review가 insufficient를 주는 경우도 포함한다.
3. 두 파일→독립 읽기→연결 파일/회귀→정확한 source CI→기존 형식의 코드·모델·JAR/UI·입력 binding을 순서대로 완료한다. 기존 runner/browser/generic regression을 원본 보존 후 최소 연결하고 새 후보명 `grounded-summary-development-v3`와 새 출력 경로 `run-grounded-summary-v3`를 사전 등록한다. 이 문서가 실제 실행 권한은 아니며 **부모의 별도 once 배정 전에는 경로·프로세스를 만들지 않는다.**
4. 배정되면 기존 무료 로컬 모델·같은 개발 입력 순서로 신규 후보를 한 번 실행한다. 과거 v1/v2 재실행이 아니다. 예정된 요약4건의 저장·인용 UI와 기존 QA6·ACL·편집/링크까지 연결하고 첫 실패에서 중단한다. 미실행·실패·cleanup을 원래 상태로 남긴다.
5. 기존 custody 방식으로 같은 요청의 **초안과 재작성 최종본을 모두** 분리한다. 기존 source-only 잠금 기준으로 각각 원문 지원·선택인용 지원·핵심 충분성을 판단하고 잠근 뒤 stage/자기검토/성능을 비교한다. 가능하면 판단 때 단계 표지를 가리고 노출은 기록한다. 새 정답·criterion·개발 원문 기반 prompt 예시를 만들지 않는다.
6. 추가1회가 원문/선택인용의 부분·애매와 핵심 누락을 실제로 고쳤는지, 반대로 맞던 내용의 손실이나 새 문제를 만들었는지 문서별 쌍으로 보고한다. claim 수가 달라질 수 있으므로 단순 분모율 상승을 개선으로 삼지 않는다. 예정된4건이 모두 완료되고 각 최종 요약이 기존 지원성·충분성 기준을 함께 충족해야 후보 수용 근거가 생기며, 핵심을 덜 말해 통과하거나 비용만 늘면 수용하지 않는다.

합성 개발 자료와 AI 판단·human0, 과거 집계 노출 한계는 그대로다. 읽기 쉬움은 실제 최종 문장을 확인해야 하며 이번 설계나 합성 검사로 인간 수용을 주장하지 않는다. 요약만 좋아져도 QA/분류/actor·공식 평가·서비스 완료를 대신하지 않는다. 현재 실행은 여전히 실패·소비 상태이며, 이번 산출물은 이 설계 문서1개다.
