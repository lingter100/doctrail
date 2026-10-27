# 로컬 요약 생성의 분량 계획 개입

2026-10-27 · 설계만 · 현재 candidate `b873645c` / tests `779ce7fc` · v5 소비·원본 보존

**다음 후보는 요약 생성에만 고정된 분량 계획 지침 `summary-budget-plan-v1`을 추가한다.** 현재 무료 로컬 모델·768토큰·문법·원문·의미 기준을 유지하는 단일 개입이다. 충분하고 자연스러운 한국어 요약이 목표이며, 더 많은 구조 수용을 품질 개선으로 간주하지 않는다.

수용된 안전 진단 `d44c6b84`에서 요약3건은 실제768토큰 상한·미완결 JSON, 나머지1건은 EOS728토큰·주장6개·개별170–238자·총1235자로 총1200 한도를 초과했다. grammar echo4건 일치·펜스0·parsed0·review0이다. 이 설계는 원 응답을 읽지 않았으며 기존 오류를 재판정하지 않는다.
관측된 세 연속 출력이768 안에 끝나지 않았다는 사실은 충분한 다른 요약도 불가능하다는 증거가 아니다. EOS 응답의 의미 충족 여부도 모른다. QA 판단·packet은 별도이며 읽거나 개입하지 않는다.

| 대안 | 판단과 비용 |
|---|---|
| 현재 설정 그대로 반복 | 선택하지 않는다. 소비된 v5를 반복하지 않으며 새로운 제어 가설도 없다. |
| 동일 예산 + 요약 분량 계획 지침 | **선택.** 기존 전체 내용·근거 조건 아래 문장별 분량을 배분하는 작은 개입이다. 준수·품질·완결 개선은 가설이다. |
| 출력 상한 상향 | 보류. 예를 들어768→1024는 총 요청 상한4608→5632(+1024)이지만 필요한 토큰량의 근거가 없고120초 안 검토 시간을 잠식할 수 있다. 총1200자 위반 자체도 해결하지 않는다. |
| 더 엄격한 문자열/주장 수 문법 | 보류. 개별240자만 강제해도 총1200·768토큰은 보장하지 못한다. decode 후 문자 합계와 JSON escape를 다루는 새 제약·엔진 검증이 필요하며, 주장 수나 문자 수의 강제 축소는 충족 가능한 내용을 제한할 수 있다. |
| 후처리 자르기·닫기·재생성 | 거부. 의미/근거를 바꾸거나 실패 경계·호출 예산을 바꾼다. |

기존 `GENERATION_PROMPT`에도 이미240/1200, 주장1–6, 필수 내용·불확실성·abstain이 명시돼 있다. 한도 누락이 원인이라고 단정하지 않고, 기존 문구를 그대로 둔 채 **출력 전 전체 분량 배분**을 더 구체적으로 지시한다. 계획용 추가 호출이나 계획 출력은 없다.

160자/총960자는 **soft 작성 목표**다. 최대6개×160=960으로 기존 총1200보다20%의 문자 여유를 두는 사전 선택이며, 측정된 최적값이나 토큰 환산값이 아니다. 주장 수1–6은 줄이지 않는다. 충분한 내용에 필요하면 개별240·총1200까지 허용하고 목표 초과 자체를 오류로 처리하지 않는다.

추가 지침의 정확한 본문은 아래5줄이다. LF로 연결하며 끝 LF는 없고, 예시·원문별 조정은 추가하지 않는다.
```text
Plan the complete summary before emitting JSON; emit only the final JSON, not the plan.
Choose 1-6 claims according to essential content, not a fixed count. Allocate space across all claims rather than giving every claim the maximum.
Aim for at most 160 Unicode code points per claim and 960 in total as soft writing targets. If sufficient supported coverage needs more, use the original limits of 240 per claim and 1200 total.
Remove repeated wording, not necessary facts or qualifications. Preserve names, decisions versus proposals, conditions, exceptions, dates, scope and unresolved uncertainty with each claim's supporting evidence.
The 768 generated-token budget covers the entire JSON, including keys and evidence IDs; code points are not tokens. Complete the whole JSON within that budget. If a sufficiently complete supported summary cannot fit the original limits, abstain.
```

압축 과정에서 조건·예외·변경·날짜·범위·주체·확정/제안 구분·불확실성이 빠지거나 서로 다른 근거를 부당하게 합칠 위험이 있다. 기존 필수 내용과 주장 전체의 근거 지지 기준을 그대로 평가한다. 짧음이나 abstain은 성공의 대체 지표가 아니다.

parser의 문자 수는 decoded text의 `len`이며 공백·문장부호도 포함한다. 모델 토큰은 JSON 키·괄호·근거 ID와 본문을 함께 소비한다. 코드포인트·문자열 표현·토큰은 같지 않으므로960자 목표가768토큰 완결을 보장하지 않는다.
등록 수치상4096+768=4864는 ctx6144보다1280 작지만 이 차이는 추가 출력 예산이나 RAM/속도 보장이 아니다. 과거 요약 입력2324–3184는 새 지침의 token 수를 포함하지 않으며, 추가 후4096 gate를 실제 요청마다 그대로 적용한다. 미리 tokenizer로 보정하지 않는다.
유효 초안 뒤에는 원문+후보의 별도 review 입력도4096 이하이고 출력128이어야 한다. 요약 생성·검토는 동일120초 deadline을 공유한다. v5에서 review0이므로 입력·시간·검토 완결 적합성은 아직 미확인이다. 지침 추가나 더 긴 생성으로 검토 여유가 늘어난다고 주장하지 않는다.

최소 구현 범위는 candidate/test 두 파일이다. frozen77·공통 GGUF·summary prompt/grammar/parser·QA/review는 수정하지 않는다. candidate의 summary 요청에만 위 상수 지침을 넣고, compact 변환 전 system=`GENERATION_PROMPT + LF + instruction`, 변환 후 끝에 기존 `LF + COMPACT_LEGEND`를 붙인다. user payload·원문/ID/순서·기존 system 본문은 그대로다.
새 schema4만 schema3의 정확한 `response_format`/compact/resource/limits에 `summary_control`을 추가한다. 정확 키는 `{policy,base_prompt_sha256,instruction_sha256,effective_system_sha256}`이며 policy는 위 한 가지, hash3종은 코드 소유 UTF-8 bytes와 완전히 같아야 한다. 정확 값은 설계 영수증에 결속한다.
순수 `registration_policy`가 외부 observer와 내부 실행 모두에서 이를 검증한다. bool/잘못된 schema·unknown/추가/누락 키·타입·hash·wire/resource/format 혼합은 native 전 거부한다. 임의 prompt 문자열·CLI/env override·mutable 선택은 허용하지 않는다. 실제 summary system이 선택된 조합과 다르면 실패한다.
schema1/2/3와 직접 호출 기본값은 기존 요청 바이트·동작 그대로다. 새 경로도 summary 이외 system/user/template/grammar가 변하지 않게 한다. report/terminal에는 선택 policy·hash3종을 등록/코드/보고 SHA와 함께 기록한다. 구 경로의 출력에 메타데이터가 추가되면 바이트 동일과 구분해 공개한다.

후속 synthetic 회귀는 기존147 cases를 보존하고 다음을 확인한다. 이 설계에서 검사나 엔진 실행은 하지 않는다.
- old schema/default 요청 그대로; schema4 정확 결속·불변 선택·native 전 거부·외부 observer 일치; summary에만 정확 지침1회와 실제 system hash 적용.
- QA/review 및 source payload/ID/전체 원문 바이트 보존, 동일 grammar3종·echo STOP·EOS 필수·fallback/repair0; 미완결·닫힌 limit 응답은 원래대로 거부.
- 목표160/960 초과도 hard240/1200 이내의 합성 초안은 기존 parser 기준으로 수용하며, 240/241·1200/1201·주장1/6/7·Unicode/escape·근거 순서 경계는 그대로 검사한다. soft 목표를 새 validator로 만들지 않는다.
- 지침을 포함한 입력4096/4097, review의 별도 입력/128토큰·공유120초 deadline, 첫 오류/내용 거부 후 고정 일정·자원 guard·소유권/cleanup·단 한 번 규칙을 보존한다.
- 문자열/mock 검사를 실제 토큰량·분량 계획 수행·엔진·의미 품질 증거로 부르지 않는다. 최초 실패와 before2도 보존한다.

원문4·질문4·판정기준·Ministral3 3B Q5_K_M·native b11429·template/greedy·ctx6144·parallel1·GPU99·f16 KV는 유지한다. 입력4096, 출력768/128/256, 요약+review120초/QA60초, 시작120/활성900/정리5/전체1025초, RSS6GiB/시작여유8GiB/활성여유2GiB도 같다.

부모가 v5 결과를 별도 공개하고 이 계획 수용·공개 → source2 구현 → synthetic/독립 검토/정확 소스 CI → 새 schema4 등록·새 output·companion·사전 packet 결속 → 별도 실제1회 배정 순서다. v5 재실행·옛 limit/결과 재해석·새 calibration/validation/finaltest 노출은 없다.
같은 고정 순서의 요약4+QA4를 각1회만 요청하고, 유효 요약마다 기존 mandatory review1회(최대4)를 적용한다. 최대 생성8/전체12회·요청4608토큰, 분모 요약4/QA4를 유지한다. QA는 변경 없이 별도 평가하며 이 설계의 조정 근거로 사용하지 않는다.
fresh 자원 gate1회 거부면 CLI0, 통과면 공식CLI1회다. 내용 거부는 기존대로 다음 고정 항목으로, 프로토콜/echo·자원·시간·binding·cleanup 실패는 기존 STOP 처리로 간다. 폴링·다른 앱 종료·실행 중 문구/상한 변경·실패 후 재생성은 없다.
기존 출력 전 packet 계약 `63ee643f`의 대상선별·공개 순서를 재사용하고 새 등록에 해시로 결속한다. 독립 판정자는 기존 기준을 출력 전에 채택하며, 추가 매핑·자체검토·성능 공개 전에 개별 의미 판정을 잠근다. 기존 노출은 기록하고 완전 맹검을 주장하지 않는다.
구조 수용·review·독립 의미 충족·미실행·실패·시간/자원을 분리한다. 이전 v5와의 동일 개발 입력 관측 비교는 반복 노출된 개발 진단이며 인과 효과 추정·일반화·최종 평가가 아니다. 품질 기준 충족 증거 없이 서비스 채택·Phase1 완료를 선언하지 않는다.

근거: [이전 형식 계획](MEETINGS-LOCAL-FORMAT-NEXT.md), 안전 진단 `d44c6b84`/receipt `d88064b8`/부모 수용 `615c6eab`, 일반 코드 등을 포함한 입력9개 참조는 새 설계 영수증에 크기·SHA로 결속했다. raw/parsed 응답·원문·질문·private 기준·QA 판단/packet은 열지 않았다. 새 데이터·모델·다운로드·유료 API·클라우드는 추가하지 않는다.
