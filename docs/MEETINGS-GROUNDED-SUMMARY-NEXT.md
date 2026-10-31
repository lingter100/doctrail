# 근거 연결 요약의 최소 후속 후보

2026-10-23. 안전 집계에 근거한 다음 설계 제안이다. 구현·모델 실행 배정이 아니며, 소비된 `grounded-summary-development-v1`을 재시작하지 않는다.

## 현재 확인된 문제

- 실제 v1은 15회 completion 응답 후 두 번째 분석의 검토 거부로 실패했다. 저장/UI 연결1건, 답변0건이며, 깨끗한 cleanup은 원래 실패를 바꾸지 않는다. [실행 결과](../experiments/results/meetings-grounded-summary-development-v1.json).
- 독립 AI 판단의 후보2·주장12에서 원문 지원8/부분1/애매3, 선택 인용 지원6/부분3/애매3, 핵심 충분0/2다. 조건·예외와 적용 시점 누락, 조건 범위 모호함, 같은 원문 안 대체 근거2건이 보고됐다. 유형 수는 중첩될 수 있다.
- 부모가 전달한 자기검토 대비 안전 집계에서 모델은12주장 중11supported/1unsupported, 두 후보 coverage 모두sufficient였다. 선택인용 기준의 잠금과는 model-supported 중 지원5/부분3/애매3, model-unsupported 중 지원1이다. 원문전체 기준 지원7 일치는 별도 보조 집계다. partial/ambiguous를 확정 오류로 바꾸거나 제공되지 않은 거부 이유를 추정하지 않는다.
- 이 관측에서 다음 수정의 우선순위는 생성 의미, 관계별 근거 선택, 핵심 포괄이다. 지연을 늘리거나 검토 거부를 풀어 해결할 근거는 없다. 다른 문서·모델 일반화나 지연 문제가 항상 없다는 결론은 아니다.
- 근거는 `safe-aggregate-v1.json` 4,588B/SHA `2ebca8c6dd4a55f84984b8c59f8ec3627c3028b52c7a3f4d52606a51d569fa39`다. private 원문·판단·자기검토 packet은 열지 않았다.

## 추천과 대안

- **추천: `batch-v2` + 새 명시 후보 `grounded-summary-v2`에서 관계를 연결한 근거 계획을 같은 생성1회 안에 넣는다.** 기존 모듈·검토1회·저장 v2·Java·React·runner를 재사용한다. 새 모델이나 별도 planning 호출은 추가하지 않는다.
- 현재 v1도 evidence ID를 text보다 먼저 출력하며, prompt에 조건·예외·시점·범위를 이미 요구한다. 따라서 evidence-first 순서 재배치나 문구 추가만을 개선으로 주장하지 않는다.
- 실질 차이는 평평한 인용 목록 대신 **관계 유형과 양끝 원문 unit ID를 명시**하고, 문서 전체에서 선택한 근거 묶음을 최종 주장에 빠짐없이 연결하는 내부 생성 계약이다. 조건의 대상·변경의 전후·시점의 적용 대상을 특정할 수 있어야 한다는 가설이다.
- 문구만 수정하는 대안은 가장 작지만 이미 있는 지시의 반복이다. 추가 planning completion이나 다른 로컬 모델은 가능한 대안이나 비용·지연·변수를 늘리므로 이번 최소 후보에 섞지 않는다. 기존 발췌 경로는 호환용으로 보존하며 충분한 요약의 대체 성과로 세지 않는다.

## 내부 wire만 바꾸는 범위

- 생성 결과는 먼저 `bundles`, 뒤에 `claims`를 둔다. 각 bundle은 연속 `id`, 현재 원문의 `anchor` unit ID, `links`의 `[relation, from_unit, to_unit]` 목록이며, 각 claim은 `bundle` ID와 최종 `text`만 가진다. abstained 계약은 유지한다.
- 관계 enum은 정확히 `support`, `condition`, `exception`, `effective_time`, `status_change`, `attribution`, `cause`의7종이다. 없는 유형을 채우거나 단어·문서명·날짜별 규칙으로 관계를 만들지 않는다.
- bundle마다 `links`는0–4개다. 단일 anchor의 독립 사실은0개를 허용한다. 같은 unit 안의 관계도 허용하며 `from_unit == to_unit`인 self-link는 다른 unit과의 연결을 만들어 주지 않는다. 이 상한은 비용을 제한하는 후보 선택이며 충분한 표현력 보장이 아니다. 필요한 내용을 한도 안에 표현할 수 없으면 기존 abstain/실패를 유지한다.
- 연결성은 link의 방향을 무시한 graph에서 anchor로부터 모든 endpoint unit에 도달 가능한지로 검사한다. anchor와 양끝의 합집합을 원문 순서로 정렬해 citations를 **한 번만 파생**한다. links0이면 합집합은 anchor 하나다. 별도의 중복 evidence 목록이나 새로운 quote/offset은 모델이 출력하지 않는다.
- `from_unit → to_unit`의 의미는 condition=조건→적용대상, exception=예외→적용대상, effective_time=시점→적용대상, status_change=과거→현재, attribution=화자→진술, cause=원인→결과, support=근거→대상으로 고정한다. endpoint를 ID 크기나 원문 순서로 뒤집지 않는다. 이는 citations 정렬과 별개이며, 역할·관계의 의미가 실제 맞는지는 기계 연결성 검사로 검증하지 않는다.
- bundle과 claim은 각각1–6개이며 정확한 일대일 대응을 요구한다. bundle ID 누락·중복·미사용, 미등록 endpoint, anchor로부터 연결되지 않은 근거, links4개 초과, 동일 `(relation, from_unit, to_unit)` triple 중복, 파생 인용1–4개 위반은 기존 parser 경계에서 거부한다. grammar와 parser에 같은 상한을 적용하며 새 검증 체계는 만들지 않는다.
- 생성은 전체 원문에서 중요 관계를 선택한 뒤 문장을 작성하도록 한다. 선택된 조건·예외·시점을 압축 단계에서 버리는 경로를 드러내지만, **애초 선택하지 않은 핵심 내용까지 기계적으로 발견한다는 뜻은 아니다.** 모든 source unit과 gap은 계속 입력에 남는다.
- 검토에는 전체 원문, 위 관계 묶음, 그것을 참조하는 문장을 중복 근거 목록 없이 전달한다. 연결의 의미, 최종 문장 전체의 지원, 원문에 남은 핵심 누락을 각각 보게 하되 출력의 supported/unsupported/uncertain 및 sufficient/insufficient/uncertain 거부 조건은 유지한다.
- 관계 필드가 존재하거나 graph가 연결됐다는 사실은 의미 지원 증명이 아니다. 잘못된 인과·화자·상태·조건 범위는 모델이 여전히 생성할 수 있으며 같은 모델 검토도 같은 오류를 공유할 수 있다. 기존 독립 지원성·충분성 기준을 그대로 적용한다.
- 공개 `summary_version=2`, `summary_claims={id,text,citations}`, summary/evidence 투영과 outer `grounded-review-v1` accepted gate는 유지한다. 내부 plan은 기존 private observer에 남기며 DB/UI에 중복 저장하거나 검증 배지를 추가하지 않는다.
- 생성768/검토128, 실제 template 포함 입력4096, 전체 분석120초, claims6/각240/합1200, 인용4, batch 정책, answer90초를 유지한다. 새 wire·review 입력 증가로 EOS/입력/시간 실패가 늘 수 있으며, 그 경우 그대로 실패다. 성공을 위해 cap을 늘리거나 plan·원문·검토를 몰래 생략하지 않는다.

- 기존 후보2의 숫자 관측은 생성 입력2244/2486·출력421/359, 검토 입력2606/2786·출력40/40 token(모두EOS), analyze observer 구간62.797/68.188초였으며, 이는 새 wire의 입력·출력·120초 여유나 성공을 보장하지 않는다(`token-budget-metadata-v1.json`, 13,494B/SHA `68464d560c8ca5eb6bb2b86763042cfd8a738a057333c0208eb474ce3d7ebeb2`).

## 정확한 수정 경계와 검사

- 핵심은 기존 `src/doctrail/meeting_grounded_summary.py`와 대응 test1: v2 prompt/grammar/parser/파생/검토 입력 분기를 추가하고 v1 함수·prompt·grammar의 기존 동작은 회귀로 보존한다. 새 validator 서비스·module·wrapper는 만들지 않는다.
- 기존 Python 연결8개(service, 두 launcher, acceptance driver와 대응 test4)는 v2 선택·metadata/hash·관측 연결만 바꾼다. normal/observer가 같은 알고리즘을 쓰게 하며 잘못된 조합은 native 전에 거부한다. coverage·분류·frozen77·answer 구현은 수정하지 않는다.
- Java/React의 공개 계약 변경은 계획하지 않는다. 기존 v2 저장·근거 이동·편집 회귀를 재사용한다. 호환 실패가 실제로 발견될 때만 원인을 보고하고 수정 경계를 다시 결정한다.
- 기존 runner/browser 및 generic regression1을 재사용하되, 원본 보존 후 새 후보명·새 binding·새 once 출력 경로와 관계→파생 citation→검토→저장 연결 확인만 추가한다. 기존 cleanup/첫 실패/exit/seal 규칙과 actor 조건은 유지한다.
- 합성 회귀는 여러 unit에 흩어진 조건·예외·시점, 동일 인용의 반복 위치, bundle 누락·중복·잘못된 endpoint, links0/4/5와 self-link·무방향 연결성·중복 triple, endpoint 방향 보존, 잘못된 파생 및 full-source 누락 입력을 검사한다. 상태 전환·화자·인과의 의미 오판은 fake 검토 거부 경로로 확인하며, 이 검사로 실제 의미 추론이나 핵심 선택의 정확성을 주장하지 않는다.
- 길이·입력 거부, EOS, 같은120초 소진, 검토 거부/불확정 및 실패 뒤 completion0의 제어 계약은 기존 fake HTTP/clock 접점으로 검사한다. 실제 template/token 비용과 남은 여유는 다음 once의 관측으로 확인하며 사전에 충분하다고 단정하지 않는다. 개발 원문이나 질문별 정답 문구로 prompt·테스트를 조정하지 않는다.

## 다음 실제 증거와 완료 조건

1. 위 최소 구현과 독립 코드 읽기, 해당 변경의 정확한 source CI를 마친 뒤 기존 binding 형식으로 후보·코드·JAR/UI·원래 입력을 고정한다. 새 실행용 이름은 `grounded-summary-development-v2`, 경로는 `run-grounded-summary-v2`로 사전 명시한다. 이는 별도 부모 once 배정 전 실행 권한이 아니다.
2. 기존 무료 로컬 real factory와 같은 입력 순서로 새 후보를 한 번 수행한다. 성공한4회의 저장·모든 근거 UI 확인 뒤 기존 QA6·ACL·편집/링크 흐름까지 한 번에 연결한다. 첫 실패 시 중단하고 미실행 단계는 그대로 남기며 기존 v1 실패에 이어 붙이지 않는다.
3. 실제 호출 수, wire/template 비용, 저장/UI 연결, QA 실행/인용, 첫 실패·cleanup을 먼저 보존한다. 요약 후보는 기존 custody 경로로 분리하고 source 지원·선택근거 지원·핵심 충분성을 기존 잠금 기준으로 판단한 뒤 자기검토/성능과 비교한다. plan 자체의 완전성을 새 품질 기준으로 추가하지 않는다.
4. 충분성이나 관계 지원이 개선되지 않거나 wire 비용만 증가하면 이 후보를 수용하지 않는다. 반대로 요약만 좋아져도 남은 분류·actor·QA 문제, 인간 검수 및 공식 자료 개방 조건이 해결됐다고 하지 않는다. 다음 제품 완료 증거는 실제 요약과 기존 QA가 함께 동작하는 서비스 흐름이다.

현재 안전 집계와 generic 코드만으로 위 가설의 작은 구현을 결정할 수 있어 추가 원문 진단은 선행 조건으로 두지 않는다. 후보2의 관측, 기존 합성 개발 자료 재사용, 과거 집계 노출과 AI 판단·human0 한계를 유지한다. 설계자는 독립 최종 judge가 아니다. 원래15회 호출·실패 원본·입력·잠금·공식 cal/val/test는 불변이며 이번 작업은 이 문서1개뿐이다.
