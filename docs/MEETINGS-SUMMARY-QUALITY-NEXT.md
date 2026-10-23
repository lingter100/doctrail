# 회의 요약 품질의 다음 단계: 같은 모델의 추론 모드 대조 진단

2026-10-23. **추천은 새 공개 회의록4개에서 cached Qwen3.5-9B의 thinking on/off만 대조하는 작은 진단1개**다. 서비스 후보 채택이나 구현·모델 실행 승인이 아니다. 부모의 설계 검토·커밋 뒤 별도 구현 배정을 받는다. 현재 산출물은 이 문서 하나이며 Phase1은 미완료, 유료 호출·공개 서비스 배포는0이다.

## 관측과 아직 모르는 것

- [v3 실행](../experiments/results/meetings-grounded-summary-development-v3.json)은 세 번째 final review 거부로 실패·소비됐다. 업로드5, 저장/UI2, QA0이며 네 번째 요약도 미실행이다. [개별→쌍 잠금 비교](../experiments/results/meetings-grounded-summary-review-v3.json)에서 같은 요청3쌍의 각18주장은 두 단계 모두 원문 지원13/부분3/애매2, 선택 인용 지원10/부분6/애매2, 핵심 충분0/3이다. 회복·퇴보0, 새 주장0, 한 쌍 완전 동일이며 나머지는 인용1개 삭제 또는 문장3개 변경이다.
- [성능](../experiments/results/meetings-grounded-summary-performance-v3.json)은 alignment 평균29.219초, 출력356–421token, 모두EOS이고 전체 분석88.250–107.984초다. 입력4096·출력768 cap 소진이 이번 실패 원인이었다는 증거는 없다. 추가 재작성의 효과가 없었던 이 표본을 모델 전체의 능력 한계로 일반화하지 않는다.
- [잠금 후 자기검토 대조](../experiments/results/meetings-grounded-summary-self-review-v3.json)는 model-supported16 중 선택 인용 지원10/부분5/애매1, model-unsupported1/uncertain1이며 모델 coverage는3개 모두sufficient, 독립은3개 모두insufficient다. 범주를 이진 오답으로 바꾸거나 거부 원인을 추측하지 않는다. 같은 모델의 accepted는 충분한 요약의 증명이 아니다.
- 공개 입력 바인딩은 development5583B/`e80424bda63581faa9787a24a0c1d9f6054c26e1adaa25fed5b99a71c304d32c`, review15092B/`63cde0d638964ae2634143383c96e12257ba7c21aa3adcfd07e75475814b516b`, performance14304B/`aea85733b76bf4082b1620c2f2859193eb61fe170b24f387fd17ef3ecc9ed8db`, self-review15502B/`e00a620bccac4b0fd241752eebdeaae129f73e1178b5a140a58a4d438dd8777c`다. 그 파일의 private/local 참조는 따라가지 않았다.

## 기존 시도와 대안

[C1](MEETINGS-C1-RESULTS.md)의 검토·수정, [C2](MEETINGS-C2-BUDGET-RESULTS.md)의 근거 단위 확대, [C3](MEETINGS-C3-RESULTS.md)의 요구사항 계획은 이미 소비됐다. 구조·정확한 인용·계획만으로 완전한 답변이 보장되지 않았다. 요약 v1의 evidence-before-text, v2 관계 graph, v3 후행 재작성도 보존하며 재실행하지 않는다. QA의 [C4](MEETINGS-C4-QUALITY-RESULTS.md)·[C5](MEETINGS-C5-QUALITY-RESULTS.md)는 thinking 실행 중90초 기한 실패로 의미 평가를 완료하지 못했고, [C6](MEETINGS-C6-PREPARATION-RESULTS.md)는 입력 준비에서 종료해 native0이었다. C7의 자료 수용성 설계와 GPU24→28·host/reader 비교도 새 의미 능력 실험을 대신하지 않는다. 이 진단은 그 조건이나 미실행 문항을 다시 여는 작업이 아니다.

| 대안 | 개선 가능성 | 비용·불확실성 및 이번 선택 |
| --- | --- | --- |
| 같은9B에서 생성 전 thinking 사용 | 초안에 고정된 후행 수정 대신 원문을 읽고 문장·근거를 만들기 전에 조건·상태·예외의 관계를 처리할 계산 기회를 준다. | 요약에서 효과 미검증. 같은 오해·반복·추론 예산 소모도 가능하다. 가중치와 출력 목표를 유지해 작은 대조가 가능하므로 **선택**한다. |
| 더 큰 무료 로컬 모델로 교체 | 현재 모델과 다른 표현·추론 능력이 병목을 바꿀 가능성이 있다. | 가중치·양자화·native 호환·자원·속도를 새로 검증해야 한다. 현재9B의 GPU28 관측도 장치 여유가 작았으며 더 큰 모델의 실행 가능성·우수성을 확인하지 않았다. 지금 다운로드나 모델 교체를 섞지 않는다. |
| 원문 구간별 핵심 추출 후 전체 재구성 | 긴 원문의 국소 집중과 누락 위치 관측에 도움이 될 수 있다. | 구간 밖 조건·예외를 잃거나 잘못 고른 핵심이 다음 단계에 고정될 수 있다. C3 계획·v2 graph와 실질 차이를 증명해야 하며 호출과 경계 검사가 늘어난다. 현재 입력 cap 소진 증거가 없어 분할을 먼저 도입하지 않는다. |

[고정 revision의 공식 모델 설명](https://huggingface.co/Qwen/Qwen3.5-9B/blob/c202236235762e1c871ad0ccb60c8ee5ba337b9a/README.md)은 API 설정의 thinking 전환을 설명한다. 이것은 로컬 pinned native의 작동이나 요약 품질 보장이 아니다. 공식 일반 권장 sampling/output 범위와도 다른 작은 실험이므로, 아래 고정 greedy·제한 예산의 결과를 모든 thinking 설정으로 확대하지 않는다. 같은 prompt의 문구를 더 강하게 쓰거나, 시간만 늘리면 핵심을 잘 파악한다는 가설은 채택하지 않는다.

## 한 가지 변수로 구분할 진단 계약

- 새 진단 ID는 `summary-mode-development-v1`이다. 새로 동결한 실제 공개 회의록4개 각각에 A=nonthinking, B=thinking을 한 번씩 실행한다. 각 arm은 **직접 전체 요약 생성1회→동일한 필수 final review1회**다. alignment·repair·추가 계획·재시도·warmup·번역·후보 선택·fallback은0이다. A도 새 공통 transport의 대조군이며 닫힌 v1을 다시 실행하거나 과거 점수와 인과 비교하지 않는다.
- 생성의 두 arm 모두 `/v1/chat/completions`, 같은 messages·최종 JSON schema·전체 source/unit catalog·identity·seed0/greedy·cache off·parallel1·출력 상한을 사용한다. **실험 변수는 생성의 `enable_thinking` on/off뿐**이다. 요청한 reasoning budget512 등 다른 필드는 두 arm에 같게 둔다. Mode에 따른 실제 template/preamble 차이는 변수의 구현으로 기록한다. A에 기존 completion endpoint, B에 새 chat endpoint를 각각 쓰는 비교는 하지 않는다.
- `GENERATION_PROMPT` 내용과 `source_payload`의 제목·모든 unit·gap을 유지한다. 현재 `partitions` 경로에서 한 번 구성한 공통 catalog를 두 arm에 그대로 사용하고 title/문서ID/revision/content/좌표를 결속한다. 새 분할 규칙·핵심 자동 필터·원문 잘라내기·개발 사례 기반 예시는 없다.
- 최종 wire는 기존 flat draft/abstained 계약과 동일하다. JSON schema는 기존 grammar가 표현하는 필드·상한과 의미 동등성을 합성 검사로 확인하고, 최종 판단은 기존 `parse_draft`·`summary_projection`으로 한다. claims1–6, 문장240/합1200codepoints, 문장당 인용1–4, 완전한 자연어 요약·한국어·정확한 원문 좌표를 유지한다. 부족한 핵심을 삭제하거나 빈 답변·발췌만으로 통과시키지 않는다.
- Final review는 두 arm 모두 기존 nonthinking `REVIEW_PROMPT`/`REVIEW_GRAMMAR`/`parse_review`와128token이다. 전체 원문과 해당 최종 문장·선택 근거만 전달하고 reasoning·A/B 표지·다른 arm·과거 결과를 주지 않는다. 지원성과 coverage gate를 완화하지 않는다. 모든 candidate와 실제 review 결과는 평가 증거로만 보존하고 제품 저장은0이다.
- **새 진단의 사전등록 중단 규칙:** 정상 schema의 semantic final-review rejection은 그 arm의 실패·비수용으로 남기고 다음 사전배정 arm을 관측할 수 있다. 해당 arm의 추가 추론은0이다. 정상 schema의 generation abstained는 schema 오류와 구분한 요약 미생성·semantic 비수용이다. 이번 진단은 이 경우 전체 중단으로 고정하며 검토할 claims가 없어 final review는0이고 남은 arm은 미실행으로 남긴다. 16completion은 완료 약속이 아닌 상한이다. transport/schema/비EOS/시간/무결성/자원 실패도 전체 즉시 중단하고 남은 arm은 미실행으로 남긴다. 이 규칙은 부모가 허용한 진단 전용이며 과거 service fail-fast 실패를 재해석하지 않는다.
- 문서의 동결 ID 순서와 A/B 실행 순서를 출력 전에 잠근다. 균형 순서는 문서1 A→B, 문서2 B→A, 문서3 A→B, 문서4 B→A로 고정하며 결과에 따라 순서를 바꾸지 않는다. 공통 source 준비와 각 arm 시간을 별도로 기록한다. 고정 seed·작은 표본·시간 순서 잔여 효과 때문에 통계적 우월성은 주장하지 않는다.

## 사전 비용·시간·자원 상한

- 가중치는 기존 `data/models/meetings-generation-qwen35-v1.json`의 Qwen3.5-9B Q5_K_M/SHA `dc2a39ae…`, native b11429/`d812350…`만 쓴다. 새 모델·패키지·다운로드·유료 API·STT는0이다. context6144, GPU28 요청, 기존 batch512/ubatch128/fit off와 단일 native 소유권을 고정한다. 실제 offload/Flash Attention은 관측하지 못하면unknown이다.
- 두 arm의 생성 **native total cap은1312token**이다. 이는 requested thinking512 + final-content allowance768 + framing32로 택한 단일 공통 상한이다. A에도 같은1312를 적용해 total budget을 mode와 함께 바꾸지 않는다. `reasoning_budget_tokens=512`는 pinned native가 효과를 직렬화하지 않으므로 **독립 hard cap이 아니다**. 생성 응답의 실제 total≤1312/EOS/무절단을 검사하고, 최종 content를 별도로 native 재토큰화해1–768을 요구한다. 재토큰 수는 실제 generated final segment 수나 독립 native768 cap이 아니다. 초과를 잘라내거나 추가 생성으로 구제하지 않는다.
- 실제 template 포함 입력은 모든 생성·review에서1–4096token이다. Source 동결 후 두 mode의 실제 template·입력을 계수하며 source를 바꿔 맞추지 않는다. 생성한 review 입력도 전송 직전에 실제로 검사하고 초과면 종료한다. cap을 만족할 새 공개 자료가 없으면 진단을 시작하지 않는다. 512/768/1312/4096은 새 계약의 engineering choice이며 C6 validation 수치에서 역산하지 않았다.
- arm당 준비·template/tokenize·생성·최종 재계수·review·파싱·증거 저장을 합쳐 **공유180초**다. 생성은 같은 arm 시작 기준150초까지, review와 나머지 처리는180초까지로 제한해 후행 검토 여유를 둔다. 실제 남은 시간을 매번 전달하며 deadline을 재시작하지 않는다. 입력 준비 공통 비용도 전체 phase에 포함한다.
- 최대8arm/16completion, 총 생성 출력 상한은 `8×(1312+128)=11,520token`이다. Startup≤120초, 공통 준비·8arm·증거 처리 active≤1500초, cleanup≤5초, 마지막 index/seal 쓰기 후까지 whole≤1625초를 모두 만족해야 한다. 생성 수·HTTP/template/tokenizer 수·출력/누락·최초 실패를 분리한다. 시간 초과 뒤 cap 확대·재개·추가 resource/profile 호출은0이다.
- 이180초는 과거 QA90초 기한 실패와 현재 분석88–108초 관측을 고려해 mode의 품질 효과를 조사할 **새 진단 상한**이며 성공 예측·SLO가 아니다. 기존 서비스120초 계약은 변경하지 않는다. 실제 서비스에 더 긴 시간이 필요하면 분석 중 상태·사용자 이탈/취소·실패 표시·각 계층 timeout을 포함한 별도 대기 경험 계약을 먼저 검토한다. 진단의180초를 조용히 Java/React에 이식하지 않는다.
- 기존 무료 장비·배타 lease와 소유 PID/create_time만 사용한다. 사전 가용 RAM10GiB 이상, 소유 native RSS 표본8GiB 이하·실행 중 가용 RAM2GiB 이상을 새 보수적 중단 조건으로 둔다(과거 약6–7GiB RSS 관측에 여유를 둔 운영 선택). 새 진단 내부에서 기존250ms 관측 방식을 arm당 최대721표본으로 제한하고 기존 GPU checkpoint를 기록한다. 기존361 고정 sampler 함수는 수정하거나 다른 상한을 지원한다고 가정하지 않는다. OOM/자원 충돌/소유권 불확실성은 중단하며 다른 프로세스를 종료하지 않는다. 표본 최대는 실제 peak가 아니며 GPU 전체 수치를 프로세스 VRAM으로 바꾸지 않는다. Live 자원 충족 여부는 아직 확인하지 않았다.
- C4/C5에서 native 시간과 전체 요청 시간 사이의 비용이 컸다. 따라서 native timing만으로180초 가능성을 주장하거나 proof/hash/소유 정리를 빼지 않는다. 종료 원인·원래 flags·미실행과 cleanup을 분리하고 모든 실패를 보존한다. Blocking I/O의 hard preemption은 입증 전 주장하지 않는다.

## 최소 구현과 새 자료·독립 평가

1. 부모 검토·설계 커밋 뒤 구현 경계는 **NEW `scripts/probe_meeting_summary_mode.py` + NEW `tests/test_probe_meeting_summary_mode.py` 두 파일**로 시작한다. 한 진단 내부의 작은 mode adapter와 orchestration만 두고 범용 평가 플랫폼·새 서비스·runner 계층을 만들지 않는다. 현재 source serializer/parser/projection, 범용 native HTTP/tokenize·identity proof·lease/cleanup primitive를 재사용한다. 기존 C4/C5의928/384/90 고정 `request_body`·validator는 직접 재사용하거나 전역값을 덮어쓰지 않는다. 확인한 연결점은 `GGUFGenerator._request/begin_request/end_request`, `ThinkingGenerator._tokenize`의 순수 token endpoint 호출 방식, `serve_meeting_gpu_placement.start_llama(gpu_layers=28, phase_deadline=...)`, `serve_meeting_thinking_compat.cleanup_owned`다. 기존 고정 thinking load/prepare/validator 전체를 새1312/180 계약에 그대로 호출하지 않는다. Frozen77·v1/v2/v3·기존 service/launcher/QA/분류/Java/React/DB는 수정하지 않는다.
2. Fake HTTP/clock으로 두 arm 요청이 mode 및 그로부터 파생된 preamble 외에 동일함을 검증한다. 입력4096/4097, total1312/1313, 최종 재계수768/769, split/framing 불일치·중복JSON·비EOS·실효설정 drift, 원문/gap/title 동일성·반복 offset, raw final→review→projection을 검사한다. Reasoning이 content나 judge pack에 섞이지 않아야 한다. native total cap과 요청된 thinking budget의 차이를 telemetry에 보존한다.
3. 같은180초·생성150초, mandatory review, semantic rejection 뒤 다음 사전 arm만 허용, 운영 실패 후 전체 completion0, no retry/repair/product-save, resource/소유 정리, 마지막 저장 이후1625초 검사를 합성 회귀로 확인한다. 이는 의미 능력 증거가 아니다. 독립 코드 읽기와 정확한 source CI 뒤에만 기존 형식의 코드·자산·자료·순서·설정 hash를 부모가 묶고, 별도 once 배정 전에는 실제 경로/프로세스를 만들지 않는다.
4. **별도 자료 담당·독립 source reviewer**가 새 실제 공개 회의록4개를 준비한다. 이용 조건·URL/revision·원문 hash·누락 없는 파싱·좌표·동일 단어 반복·문서 전체의 보존과 과거 모든 시험/개발/진단 pool의 metadata 및 허용된 중복 검토를 동결한다. 문제 단락만 발췌하거나 길이·정답을 맞추려고 원문을 수정하지 않는다. 본 설계자·구현자는 raw/정답/criteria를 작성하지 않으며 새 사례를 prompt 예시로 사용하지 않는다.
5. 기존 지원성·핵심 충분성 원칙을 바꾸지 않는 **source-only 독립 판단자**가 모델 출력 전에 각 원문 필수 조건·예외·현재 상태·시점의 판정 근거를 잠근다. 새 자료의 source-specific 기록은 기존 목표를 재는 도구이며 더 쉬운 gold/합격 기준을 만드는 작업이 아니다. 수정 요청·노출·역할 겹침은 기록한다. 원문이 온전한 자연어 요약을 요구한다는 목표를 분류·QA·발췌 목표로 바꾸지 않는다.
6. 실행 후 각 candidate의 최종 문장·선택 인용과 전체 원문만 익명 pack으로 전달한다. Mode/자기검토/시간/추론 내용/대응표를 숨겨 **개별 지원성·충분성·읽기 쉬움 판단→잠금→쌍 공개 비교→자기검토/비용 대조** 순서를 지킨다. 같은 source로 쌍을 추정할 수 있는 한계는 공개한다. Reasoning의 그럴듯함을 품질 점수로 삼지 않고, 모든 주장 전체의 선택 근거 지원과 원문 핵심 보존을 본다.
7. B가 완전한 요약으로 회복한 문서 수, 새 누락/퇴보, 선택 인용과 문장 전체의 불일치를 문서별로 보고한다. 주장 수를 줄여 분모율만 올리는 것은 개선이 아니다. **B4/4가 전체 주장 지원·핵심 충분·읽기 쉬운 완전 요약과 실제 final-review/운영 수용을 함께 충족**, A 대비 최소1건의 완전 요약 회복과 퇴보0이 있어야 thinking을 서비스 후보로 검토할 근거가 생긴다. A/B 모두 이미 충분하면 thinking 추가 이득은 미확인으로 남긴다.
8. 개선0, 비용만 증가, 새로운 핵심 손실, B 일부만 개선/수용, total/final/input/시간/자원 실패, mode 차이 검증 실패는 이 **고정 제한 thinking 후보**의 기각 또는 운영 미검증 종료다. 일반9B·모든 thinking 방식의 불가능 판정은 아니다. 같은 자료를 재실행·튜닝하지 않는다. 일부 긍정 결과만으로 요약 gate·서비스 fail-fast·기존 독립 판단을 바꾸지 않는다.
9. 진단 통과도 서비스 완료가 아니다. 실제 분류를 포함한 분석 budget, summary v2 저장·모든 근거 이동·QA·ACL/수정/링크·사용자 대기 경험을 기존 서비스에 연결하는 별도 설계·구현·정확한 CI·새 자료 once가 필요하다. **진단4/4는 기존 공식 calibration/운영 무결성 gate, 격리 validation, 최종 test 개방 조건을 대체하지 않는다.** 각 기존 후보의6/6→8/8 등 원래 gate와 자료 격리를 유지하며 닫힌 split을 다시 열지 않는다.

본 역할은 이전 설계·코드 검토와 AGENTS의 역사 집계에 노출됐다. 이번 공개 결과 탐색에서 C2 case-ID 진단의 짧은 설명과 C6 validation 집계 min/max도 읽혔으며 부모에게 고지했다. 해당 사례·수치로 prompt/자료/예산을 튜닝하거나 역산하지 않았다. Private 원문·출력·정답·잠금 기준·cal/val/test 본문은 열지 않았고, 새 자료·기준 작성자나 최종 judge를 맡지 않는다. 작은 표본·AI 검토·human0 한계는 유지한다. 이번 작업의 실제 모델·tokenizer·테스트·서비스 기동·다운로드·Git·구현은0이다.
