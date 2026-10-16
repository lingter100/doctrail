# GPU24→28 — 새 중립 resource pair 사전등록

2026-10-16. `meetings-gpu-placement-v1`은 같은 캐시 Qwen3.5-9B Q5_K_M과 llama.cpp build를 사용하는 **24 control → 28 candidate, 각 최대1회**의 새 중립 실험이다. 28의 개선 효과와 메모리 적합성은 미검증 가설이다. 이 문서와 [protocol](../data/evaluation/meetings-gpu-placement-protocol-v1.json)만 작성하며 현재 구현·offline 준비·native 실행은0이다. 기존 C4 실패·닫힌 pool·host profile은 그대로 보존한다. 이 실험은 품질 평가나 서비스 채택이 아니다.

## 선택 근거와 고정 native 소스의 의미

허용된 C4 timing metadata에서 첫 요청은86.157초, native prediction63.403초와 prompt4.000초였다. 두 번째 요청은 deadline 실패했고 native 완료 시간·출력량은 없다. 합성 host profile의 warm 중앙값2.933초와 반복 검사 비중은 실제 C4 비용의 인과 증명이 아니며 회수 가능한 시간도 아니다. Proof 검사나90초를 바꾸지 않고 요청한 GPU 배치 값 하나의 새 관측을 얻는다. [C4 metadata](../experiments/results/meetings-c4-quality-failure-metadata-v1.json), [합성 profile metadata](../experiments/results/meetings-host-proof-profile-v1.json).

고정 `d81235049384534c167caea52b85a694f6103d14`의 배치 계산은 **출력층을 GPU층 수에 포함**한다. GPU backend가 사용 가능한 이 경로에서24는 출력1+반복23,28은 출력1+반복27의 배치를 요청하며 입력층은 CPU에 둔다. 이를24/28개의 반복층이라고 쓰지 않는다. 이 계산은 실제 설치 바이너리의 tensor별 배치를 관측한 증거가 아니다. [배치 계산](https://github.com/ggml-org/llama.cpp/blob/d81235049384534c167caea52b85a694f6103d14/src/llama-model.cpp#L1502-L1526), [층 수 출력 구현](https://github.com/ggml-org/llama.cpp/blob/d81235049384534c167caea52b85a694f6103d14/src/llama-model.cpp#L1806-L1818).

Flash Attention의 고정 기본값은AUTO이며 지원 탐색으로 실효값을 정한다. 양 arm에서 기존 argv의 기본 AUTO를 유지하며 on/off flag를 추가하지 않는다. `/props`만으로 실효 GPU층 수나 FA 상태를 증명하지 않는다. 보고서는 `gpu_layers_requested=24/28`, `gpu_layers_effective=null`, `flash_attention_requested=auto`, `flash_attention_effective=null`로 구분한다. [기본값](https://github.com/ggml-org/llama.cpp/blob/d81235049384534c167caea52b85a694f6103d14/common/common.h#L437-L460), [AUTO 해석](https://github.com/ggml-org/llama.cpp/blob/d81235049384534c167caea52b85a694f6103d14/src/llama-context.cpp#L506-L509).

기존 기록의 RTX4050 Laptop6141MiB, RAM31.51GiB와 가중치6,577,841,376bytes는 현재 여유 VRAM이나28의 성공 보장이 아니다. 공식 원 모델 config는 본체32층과 MTP1층을 적지만, 그 숫자만으로 quantized runtime의 실제 메모리 배치를 단정하지 않는다. [고정 model config](https://huggingface.co/Qwen/Qwen3.5-9B/blob/c202236235762e1c871ad0ccb60c8ee5ba337b9a/config.json). 새 다운로드·모델 교체·의존성 설치는 없다.

## 유일한 변경과 같은 입력

기존 `scripts/serve_meeting_thinking.py:command()`의 argv를 새 launcher에서 복사하고 `--n-gpu-layers` 값만24 또는28로 바꾼다. Arm별 임시 port·인증 token·소유 PID/출력 경로는 운영 식별값이며 추론 설정 변수가 아니다. 정규화한 argv의 유일한 의미 차이가24→28인지 실행 전에 검사한다. API key는 기존처럼 환경으로만 전달하며 argv·보고서·예외 원문에 기록하지 않는다.

같은 모델 SHA `dc2a39aef291f91a9116ad214058da0d86eb648743a124bd8c333787c4b9c91c`, 원 revision `c202236235762e1c871ad0ccb60c8ee5ba337b9a`, b11429/d812350 build, alias, manifest, tokenizer 자산을 고정한다. Context6144/input5120/전체출력928/requested thinking512/최종 JSON 재토큰384/공유요청90초, batch512/ubatch128/parallel1/fit off, greedy seed0, cache off, 같은 chat template·grammar·stop·reasoning 설정을 유지한다. 512와384는 별도의 native hardcap이 아니다.

**새 메시지1개를 양 arm에서 byte-identical하게 사용한다.** 새 GPU 배치 확인용 중립 지시와 ASCII `u `5000회의 기계적 padding을 생성한다. 지시는 filler를 무시하고 짧게 생각한 뒤 고정 marker JSON을 반환하게 한다. 정확한 지시 bytes·직렬화·padding 생성기는 소스 동결 전에 새 probe에 고정한다. 기존 질문·문맥·문항 ID·resource 입력을 복사하지 않는다. 최종 형식 `{"marker":"teal"}`은 기존 정상 transport 검증기를 그대로 재사용하기 위한 형식이며 품질 문항 재사용이 아니다.

Schema는 object의 필수 `marker` string const `teal`, `additionalProperties:false`로 고정한다. 큰 `minLength`·반복 pattern·긴 const를 사용하지 않는다. 동결된 `ThinkingGenerator.generate_neutral(..., stress=False)`를 재사용해 reasoning/content 분리, 유효 JSON, 자연 EOS, 최종재토큰384 이하를 검사한다. `stress=True`나 final384 우회는 금지한다. **928은 최대 출력 cap이다. 짧은 marker 출력은928 decode 부하나 실제 Q&A 최대 부하를 입증하지 않는다.**

소스·fixture generator 동결 커밋과 CI 뒤 공식 offline 준비를 한 번만 예약한다. 캐시 tokenizer load1회로 단일 새 입력의 prompt bytes/hash·token IDs hash·정확한 수를 기록하며 **4992..5120**이어야 한다. 양 arm은 같은 준비 결과를 공유한다. 범위를 벗어나면 준비 실패로 닫고 padding 조정·binary search·추가 count·재준비를 하지 않는다. 원시 input/prompt/token IDs와 준비 원문은 `.local`에만 저장한다. 커밋하는 실행계획은 generator/source/입력/schema/준비영수증의 hash, 정확한 count와 arm 순서를 결합한 metadata다. 실행 전 private 입력이 커밋된 생성기와 동일하고 모든 hash가 맞는지 확인한다.

## 실행 횟수·안전·시간 경계

순서는 **24 → 28**로 고정한다. 각 arm은 새 소유 process를 최대1회 시작하고 생성 POST를 최대1회 시도한다. 전체 native 생성 시도는 최대2다. Warmup·재시도·fallback·추가 설정·역순 pair·metadata 확인용 추가 모델 재시작은 모두0이다. 두 arm이 끝나거나 공통 중단 조건에 도달하면 결과를 닫는다.

| 구간 | 경계와 판정 |
| --- | --- |
| 공통 preflight / arm setup | 실행계획·source·HEAD·자산 identity 확인, 배타적 output/ledger 예약, 소유 process 시작·health·identity 확인. 모델 startup은 요청90초와 별도이며 각 arm readiness 상한240초, 전체 pair 상한1200초에 포함한다. Cold startup 시간을 생성 요청 시간으로 섞지 않는다. |
| `t0` / timed verify | 요청 경계에서 monotonic90초와 소유 watchdog을 시작한다. 이후 byte/HEAD/path 재검증, 메시지 준비, template 적용·input tokenize를 모두90초에 포함한다. |
| before-send | 실제 prompt/token/request bytes를 준비영수증과 대조하고 같은 source/HEAD/identity를 재검증한다. 전송 예약을 durable하게 남기고 GPU checkpoint 및 관측 callback 뒤 남은 시간을 다시 검사한다. |
| native | 실제 HTTP send hook 직전의 남은 시간을 timeout에 반영한다. Frozen transport의 내부90초가 외부 `t0+90`을 연장하지 못하도록 새 probe의 얇은 wrapper가 더 이른 deadline을 사용한다. POST 직전 재검사 없이 관측 callback 뒤 전송하지 않는다. |
| finalize | 응답 관측·계약 검증·native final tokenize·필수 원시 응답/관측 기록·요청 결과 확정까지 같은90초다. Native reported prompt/decode와 client HTTP interval은 겹치므로 합산하지 않는다. 최종 경계검사에서90초를 넘으면 실패다. |
| cleanup / publication | 소유 process와 drain·watchdog·sampler 종료를 합쳐 cleanup5초, 요청 `t0`부터 종료 확인까지120초를 유지한다. 최종 pair 요약 저장은 요청 시간과 구분한다. Blocking I/O가 늦게 반환하는 경우 관측 경과와 실패를 보존하며90초 성공으로 바꾸지 않는다. |

전송 예약·HTTP send 시도·파싱된 응답·계약 수용을 별도 계수한다. Send hook은 wire 전달이나 생성 완료 증거가 아니다. 타임아웃 뒤 없는 응답·token 수·native timing을0으로 채우지 않는다. 첫 실패와 뒤의 정리/저장 실패를 따로 보존한다. 저장 성공 여부가 불확실하면 통과를 주장하지 않는다.

Control의 timeout, native OOM/backend 실패, startup/launch 실패, JSON/EOS/최종길이 등 arm-local 실패가 나도 **공통 code/HEAD/identity 계약이 정상이고 소유 자원의 안전한 종료가 증명되면** candidate1회를 허용한다. Process 미생성이 확인되거나 생성한 process가 모두 종료돼야 한다. Cleanup 실패·소유권 불명·살아 있는 자식/관측 process·drain read/join 오류·공통 source/plan/identity 불일치·phase deadline은 즉시 전체 중단이며 candidate는 미실행으로 남긴다. OOM으로 진단 bytes가 발생하면 해당 arm의 log0/resource 조건은 실패한 채 보존한다. 정상 drain과 안전 종료가 확인되는 arm-local 진단 실패를 control 성공으로 바꾸지 않으며, 그 사실만으로 candidate를 재시도로 해석하지 않는다.

## 같은 bounded 관측과 원문 경계

양 arm 모두 기존 `--log-disable`와 `DiscardDrain`을 유지한다. Native stdout/stderr는8192bytes chunk로 EOF까지 계속 버리면서 전체 emitted bytes와 read/join 오류를 센다. 원문 logger·32MiB 저장·새 로그 parser를 추가하지 않는다. Arm 통과에는 emitted0/EOF/read·join오류0이 필요하다. 원시 HTTP 응답의 `__verbose`, reasoning, content, token IDs와 입력은 배타적인 `.local/meetings-gpu-placement-v1/` 하위 파일에만 보존한다. 운영 console과 public artifact에 원문을 넣지 않는다.

RSS는 기존 psutil 방식으로 소유 PID만250ms 간격, 요청당최대361회·90초 경계까지만 관측한다. 제한은 hang 시 표본 리스트가 계속 자라는 일을 막기 위한 것이며 더 많은 표본을 얻으려고 시간을 늘리지 않는다. GPU는 같은 physical GPU 식별자로 **launch 전 / send 직전 / 요청 종료 / cleanup 후**의 고정4지점에서만 읽는다. 기존 설치된 read-only GPU utility를 사용하고 각 조회는최대1초·재시도0이다. Send 직전과 정상 요청 종료 조회 비용은90초에 포함한다. 요청이 이미 실패했을 때 종료 조회는 실패 후 정리 구간으로 명시한다. 조회 process도 소유 종료를 확인한다. 새 package나 GPU 설정 변경은 없다.

GPU total/used/free 등 장치 전체 metadata와 시각·성공/오류·누락 사유를 기록한다. Windows에서 process VRAM이 없으면 `null`이며 RSS로 대신하지 않는다. 표본 최대값은 진짜 peak가 아니고 GPU 전체 사용량은 이 process 단독 사용량이 아니다. 도달하지 않은 checkpoint·권한/지원 부족·timeout도 `null`과 사유로 남긴다. 누락은0메모리나 성공으로 해석하지 않고 해당 메모리 비교를 제한한다. 같은 sampler 코드·간격·checkpoint·상한을 양 arm에 적용한다.

Public allowlist는 arm ID, 요청한 GPU값/실효값 unknown, 정규화 argv와 설정 hash, 모델/build/source/plan/input/schema/grammar hash, input/output/final재토큰 수, 종료 사유·safe error code, 분리된 시간·남은시간, bounded 메모리 표본/누락 metadata, 횟수·cleanup·drain 상태, private artifact의 hash/byte 수뿐이다. Credential·원문 지시·응답·reasoning·token IDs·raw native text·임의 예외 문자열은 제외한다.

## 구현 소유권과 실행 전 순서

부모가 설계2파일을 먼저 커밋한다. 이후 실제 Astra high 구현 역할은 다음 **NEW4만** 소유한다.

- `scripts/serve_meeting_gpu_placement.py`
- `scripts/probe_meeting_gpu_placement.py`
- `tests/test_meeting_gpu_placement_launcher.py`
- `tests/test_probe_meeting_gpu_placement.py`

기존 command, 모델/identity 검증, lease, cleanup/drain, 정상 ThinkingGenerator, tokenizer load/count, path/snapshot/Git proof primitive를 수정 없이 재사용한다. 기존 compat/quality `bindings/check/register/run`은 닫힌 plan/report/body를 읽으므로 호출하지 않는다. 새 probe 안에 fixture 생성·offline register·모델 없는 실행계획 검사·단발 pair run·metadata projection만 둔다. 새 서버·공통 평가 플랫폼·품질 adapter·서비스 통합은 만들지 않는다.

순서는 **NEW4+허용 dependency closure+fixture generator/spec+설계 동결 → 커밋·필수 CI → 공식 offline neutral 등록1회 → 실행계획/metadata 준비영수증 커밋 → 새 output에서24/28 최대2회**다. 실제 모델 실행 전까지 준비·검토 단계의 native0을 유지한다. 입력 내용·padding·예산·옵션이 달라지면 이 등록으로 실행하지 않는다. 준비나 pair가 실패해도 같은 ID/output을 지우거나 이어 실행하지 않는다.

합성 검사에서는 arm argv 차이1개, marker 정상 transport/최종384/EOS, outer deadline과 callback 후 late-send 차단, 후보 누락·source/HEAD drift의 전송 전 거부, control-local 실패 후 안전 종료에 따른 candidate 여부, cleanup 실패 시 중단, send/response/수용 계수 분리, bounded sampler/null 처리, log0·private/public 원문 분리, 단발 예약과 최초 실패 보존을 확인한다. 실제 모델로 테스트하거나 old pool을 열지 않는다.

## 결과 해석과 종료

각 arm의 완료·90초·정상 계약·log0·cleanup을 독립 보고한다. **양쪽의 input/output token 수가 같지 않으면 speedup이나 동일 작업 처리량 개선을 주장하지 않는다.** 같은 수라도 token 경로와 실효 FA가 같다는 보장은 없으므로, 같은 identity/settings/grammar와 두 정상 응답이 확인될 때만 이 pair의 관측 latency 비율을 기술한다. Native timing 누락·timeout은 censoring으로 남기며 실패 시간을 완성 시간으로 비교하지 않는다.

각 arm n=1이고24가 항상 먼저라 OS cache·온도·전력·동시 부하·순서 효과를 분리하지 못한다. 28의 효과가 없거나 pair가 미완료면 그대로 보존하고 config/cap ladder·추가 pair를 하지 않는다. 결과만으로 서비스 채택·전체928 부하 통과·일반 Q&A 품질 개선을 선언하지 않는다. 향후 품질은 새 source-first 자료, 일반 문서·복수 회의·혼합 근거·KO/EN·완전성·정확 인용·적절한 보류를 유지하며 freshcal6/6 뒤 격리val8/8의 별도 계약이다.

설계 역할 `/root/free_qa_candidate_review`는 실제 Astra xhigh이며 이전 후보/code 검토·공개 집계와 timing metadata에 노출돼 향후 독립 output judge에서 제외된다. 이번에는 허용된 코드·manifest·공개 설계와 pinned 공식 소스만 읽었고 닫힌 원문·질문·oracle·trace 값·validation 의미자료 접근0, source/item authorship0, tokenizer/native/품질 실행0이다.
