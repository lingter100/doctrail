# 로컬 요약의 정확한 길이 경계 검토

2026-10-27 · 설계만 · v6 소비·원본 보존 · 현재 source2 `9de904a8` / `f323dd3c`

**다음 요약 작업은 hard240/총1200을 그대로 표현하는 생성 문법의 작은 기술검증이다. 제품 통합·다음 실제 생성은 아직 선택하지 않는다.** prompt 미세변형을 반복하거나 토큰을 먼저 늘리지 않는다. 충분한 근거 기반 자연어 요약이 목표이며, 경계 통과는 의미 품질의 대체물이 아니다.

수용된 v6 안전 진단 `7eb019c1`은 고정5줄 system의 정확한 전송4건을 확인했다. 요약3건은768토큰 limit·미완결, EOS1건은738토큰에서 둘째 주장243>240으로 먼저 거부됐다. 다른254/248과 총1239>1200은 후속 관측이다. parsed/review0이며 v5와 거부 분포가 같다.
같은 개발 입력에서 두 실행이 실패했다는 사실은 충분한 다른 요약의 불가능성, 필요 토큰량, prompt의 일반적 효과 또는 모델의 의미 능력을 입증하지 않는다. 개별 의미 판정도 없다. 과거 출력은 수리·재채택하지 않는다.

| 대안 | 판단 |
|---|---|
| 또 다른 길이 prompt | 보류. 기존 조건과5줄이 전송됐고 여전히 hard 위반이 관측됐다. 표현 미세조정 반복의 근거가 부족하다. |
| 기존 hard 경계의 생성 중 제약 | **기술검증 우선.** EOS의 길이 위반을 직접 겨냥한다. 3건의 token limit·완결·근거/내용 충족까지 해결한다고 주장하지 않는다. |
| 출력 상한 변경 | 보류. 예시768→1024는 요약4건 요청 상한+1024, 전체4608→5632다. 원래240/1200과review는 그대로여야 하며 별도 정책/등록으로 비용을 공개해야 한다. 현재 출력의 필요량·성공을 예측할 근거는 없다. |
| 분할 생성 후 통합 | 보류. 추가 호출·토큰·시간과 문맥 간 조건/예외 누락 위험이 생기는 별도 설계다. 현재 전체 입력이4096 안에 들어왔으므로 이번 형식 실패의 최소 개입은 아니다. |
| 다른 무료 로컬 모델 | 별도 후보로 보류. 더 좋은 의미 품질·이 PC 적합성은 미확인이다. 라이선스/asset/runtime·동일 기준·자원/시간 재결속이 필요하며 이번에 탐색·다운로드하지 않는다. |

정확한 목표는 기존 생성 문법에서 표현 가능하고 frozen parser가 수용하는 초안을 추가로 배제하지 않으면서, decoded `text`마다1–240·합계≤1200을 생성 중 지키는 것이다. claims1–6·evidence1–4·원본 ID·키/순서·abstain 경로는 보존한다. 문자·근거·주장을 사후 자르거나 재번호화하지 않는다.
일괄200자×6 또는 최대5claims는 원래 허용 범위를 줄이므로 제외한다. 예를 들어 길이(240,240,240,240,239,1)의6개 주장도 총1200으로 남겨야 한다. 1–5claims는 개별240이면 합계가 자동으로≤1200이지만6claims에는 전체 합계 제약이 따로 필요하다.

[고정 GBNF 안내](https://raw.githubusercontent.com/ggml-org/llama.cpp/d81235049384534c167caea52b85a694f6103d14/grammars/README.md)는 Unicode 문자와 bounded repetition을 지원하고 반복 방식의 sampling 비용을 경고한다. 현재 `char+`를 단순 `char{1,240}`으로 바꿔도 전체 합계는 해결되지 않는다.
[같은 revision의 JSON 변환기](https://raw.githubusercontent.com/ggml-org/llama.cpp/d81235049384534c167caea52b85a694f6103d14/common/json-schema-to-grammar.cpp)의 char 규칙도 raw 문자와 escape를 구별한다. 원문 코드포인트 수·JSON 표현 길이·모델 토큰 수는 다른 값이다. `maxLength` 예제를 전체 decoded 합계 제약의 증거로 사용하지 않는다.
검증할 단위는 decoded Unicode scalar1개다. 한글/ASCII/비BMP literal, 따옴표·역슬래시·slash escape, BMP `\uXXXX`, 올바른 surrogate-pair 표현을 같은 decoded 값에 같은 비용으로 매핑해야 한다. 단독 surrogate는 기존 UTF-8 gate처럼 거부하고, 조합형을 정규화하거나 ASCII/한글 전용으로 줄이지 않는다. JSON escape 금지도 하지 않는다.
그 단위에 주장 위치·현재 문자열 길이·총 길이의 유한 상태를 결합할 수 있는지 검토한다. 단순 좌표 상한만6×241×1201=1,736,646이라서 그대로 규칙화하는 방식은 비용 미확인이다. 1–5/6 분기·공통 상태 공유·불가능 상태 제거를 검토하되 길이 배분을 고정하지 않는다. 이는 구현 가능성 가설이며 완성 문법이 아니다.
[공식 grammar 구현](https://raw.githubusercontent.com/ggml-org/llama.cpp/d81235049384534c167caea52b85a694f6103d14/src/llama-grammar.cpp)은 반복을 규칙으로 전개하고 분기를 stack으로 처리한다. 따라서 짧은 문법 표기나 유한 상태라는 사실만으로 초기화·메모리·sampling 비용이 작다고 결론내리지 않는다. native 수정이나 새 sampler로 우회하지 않는다.

후속 작은 기술검증은 부모의 **별도 배정 뒤에만**, 새 격리 폴더에서 수행한다. source2·frozen77·기존 grammar/등록/모델은 읽기 전용이며 실제 회의·질문·판정기준·모델 출력은 입력으로 쓰지 않는다.
1. 먼저 순수 생성기/길이 상태 명세와 reference oracle을 만들고, 기존 수용 범위 보존·개별/전체 상한 불변식을 검토한다. 문자열은 규칙 검증용 합성값뿐이다. literal/escape 등가성과 가변 길이 배분을 포함한 최대256개 corpus를 엔진 결과 보기 전에 고정한다.
2. 개별0/1/239/240/241, 총1199/1200/1201, claims0/1/5/6/7, 6×200 및 비균등6개, 빈/잘린 문자열·잘못된 escape·surrogate·중복 키·원래 ID 경계를 포함한다. 유효 전체 문자열과 그 prefix의 진행/완결을 구분하며 frozen JSON/길이 판단과 대조한다. 유한 corpus 통과를 모든 문자열의 증명으로 부르지 않는다.
3. 같은 b11429 revision의 [공식 model-free validator](https://raw.githubusercontent.com/ggml-org/llama.cpp/d81235049384534c167caea52b85a694f6103d14/tests/test-gbnf-validator.cpp) 또는 동일 API의 제한된 harness로 문법 초기화·완전 문자열·prefix를 검사한다. 준비된 pinned 도구가 없으면 그 상태를 반환하며 다운로드·빌드·다른 runtime 사용으로 임의 확장하지 않는다.
4. 해당 공식 validator는 invalid 문자열에도 최종 exit0이 가능하므로 종료코드만으로 통과 판정하지 않는다. 명시 valid/invalid verdict·예상값·stdout/stderr·도구/문법/corpus SHA를 결속하고, verdict 불명확·충돌은 실패로 보존한다.

기술검증의 사전 작업 상한은 생성 문법2MiB·명시 규칙20,000개, 순수 구성60초, validator batch60초·관측 RSS512MiB·호스트 여유2GiB다. 반복 전개 예상량도 먼저 기록한다. 이는 작은 조사 범위를 제한하는 **운영 상한**이며 충분성/속도/OS hard 보장이 아니다. 실제 제품 RSS6/시작8/호스트2 정책을 대체하지 않는다.
상한 초과·수용 가능한 합성값의 탈락·길이 위반 수용·Unicode 불일치·엔진 초기화 실패·시간/자원 초과·판정 모호성 중 하나면 중단하고 증거를 반환한다. 상한을 올리며 통과할 때까지 반복하거나 문자열/claim 범위를 줄여 성공 처리하지 않는다. 실제 토큰 filtering 비용은 model-free 문자 검사로 입증되지 않는다.

통과하더라도 source2 통합은 별도 검토 결정이다. 최소 새 helper/test에서 재현 가능한 grammar를 만들고 새 immutable format/policy·등록 버전에 생성기/문법 SHA를 결속한다. schema1–4/default, v6의5줄 prompt, 기존 parser·review·QA·wire·입력·모델·자원·time budget은 자동 변경하지 않는다. 추가 요약 개입 하나만 분리한다.
768토큰은 JSON 키·근거 ID까지 포함하므로1200문자 경계가 token 완결을 보장하지 않는다. v6 입력2507–3367은 과거 측정이고 새 grammar의 속도 증거가 아니다. 등록4096+1024=5120<ctx6144라는 산술만으로 상한 상향의 안전성·속도·품질을 판단하지 않는다.
요약과 mandatory review는120초 공유, review는 별도 입력4096/출력128이다. 지금까지 유효 초안이 없어 review 적합성은 미확인이다. 향후 예산 변경을 선택한다면 summary 한도·전체 요청량·시간·context/자원 범위를 새 정책에 먼저 명시하고, v6를 더 큰 한도로 다시 판정하지 않는다.
동일 개발4건의 이전 관측 비교는 반복 노출된 개발 진단이며 대조 실험·일반화·최종 평가가 아니다. 새로운 generation budget과 grammar를 동시에 바꿔 효과를 혼동하지 않는다. 새 data/validation/finaltest 노출은 없다.

QA 지침 계획 `b6651dda`의 source2 작업과 이 요약의 source2 수정/실험을 겹치지 않는다. 부모의 다음 배정에서 실제 기준 HEAD·QA 조건을 고정하고, 요약 기술검증 결과가 수용된 뒤에만 통합·정확 CI·새 등록/output/companion·사전 packet 결속·별도 실제1회 순서를 정한다. 지금은 구현·실행 권한을 확장하지 않는다.
향후 실제는 기존 요약4/QA4 분모·원문/질문·필수 내용/근거 기준·원본 ID·독립 사전 기준 채택·추가 매핑 전 개별 의미 lock을 유지한다. 기존 consumed v6는 재실행하지 않으며 fresh gate1회·무재시도·내용 거부/STOP·소유 cleanup 규칙도 유지한다. QA 판단은 별도이고 이 설계에서 읽거나 조정하지 않는다.
최종 판단은 완결/구조·review·독립 의미 충분성·핵심 누락·근거 지지·자연스러운 한국어를 분리한다. 문법이 닫혔다는 이유만으로 요약 성공·서비스 채택·Phase1 완료를 선언하지 않는다.

이번 작업은 승인된 안전 집계/일반 코드와 위 고정 official source의 read-only 검토뿐이다. local 입력9개의 크기·SHA와 외부 URL/revision/확인 범위를 새 영수증에 기록했다. raw/parsed 응답·private source/question/criteria/진단 상세·QA 판단은 읽지 않았고 engine/native/tokenizer/검사/다운로드/Git 실행은0이다.
