# GPU 배치 단발 비교 결과

2026-10-16, 실행 소스 `7ac7513c2fb969b0f0e794c3d61e6e82b2ddfcb2`. [고정 설계](MEETINGS-GPU-PLACEMENT-PLAN.md)와 [입력 준비](MEETINGS-GPU-PLACEMENT-PREPARATION.md)에 따라 GPU24→28을 각1회 실행했다. **두 arm 모두 자원 조건을 통과**했다. 이 실험은 종료됐으며 재시도·역순 실행·추가 설정 비교를 하지 않는다. 일반 질의응답 품질과 서비스 채택은 아직0이다.

## 실제 관측

| 항목 | GPU24 요청 | GPU28 요청 |
|---|---:|---:|
| 입력 / 출력 토큰 | 5064 / 521 | 5064 / 521 |
| 최종 JSON 재토큰 / 종료 | 6 / EOS | 6 / EOS |
| 전체 요청 | 71.485초 | 63.453초 |
| 모델 준비 구간 | 33.265초 | 37.953초 |
| 요청 내 소스 검증 | 6.312초 | 12.360초 |
| Template + 입력 tokenize | 0.031초 | 0.047초 |
| 전송 직전 증명·예약 | 5.860초 | 12.734초 |
| Native HTTP | 59.047초 | 38.094초 |
| 최종 검증·저장 | 0.203초 | 0.203초 |
| 전체 요청에서 단계 합을 뺀 차이 | 0.032초 | 0.015초 |
| Native prompt 자체 시간 | 13.047801초 | 8.486958초 |
| Native prediction 자체 시간 | 45.962405초 | 29.581878초 |
| Cleanup 전체 | 1.359초 | 1.078초 |
| 요청 시작→cleanup 종료 | 72.844초 | 64.531초 |
| GPU used: 전송 직전 / 요청 종료 | 4588 / 4632MiB | 5212 / 5238MiB |
| GPU free: 전송 직전 / 요청 종료 | 1336 / 1292MiB | 712 / 686MiB |
| Owned RSS 관측 최대값 | 6617866240 bytes | 6578634752 bytes |
| RSS 표본 수 | 275 | 246 |

Native 자체 시간과 HTTP 시간은 중첩되며 합산하지 않는다. GPU는 동일 장치의 전체 관측값으로 프로세스 VRAM이나 peak가 아니다. RSS도 지정된 간격의 관측 최대값이며 실제 peak 또는 GPU 메모리를 대신하지 않는다. 두 arm 모두 시작 전과 cleanup 후 GPU used10MiB/free5914MiB를 기록했고, 드라이버의 total6141MiB·used·free 필드를 별개로 보존했다. 실제 GPU offload 수와 Flash Attention 적용 여부는 API에 노출되지 않아 unknown이다.

같은 input/output 수·identity·설정·문법과 정상 응답을 확인한 이 pair의 전체 요청 비율24/28은 **1.12658**이다. 28의 요청은 이 관측에서8.032초(약11.24%) 짧았다. Native 시간은 줄었지만 두 검증 구간의 합은12.172→25.094초로 늘었다. 따라서 native 차이를 전체 지연 개선으로 그대로 옮기거나 증가 원인을 GPU 배치에 단정하지 않는다.

## 통과 조건과 한계

실제 생성 전송2·파싱2·구조 수용2, 각launch1·dispatch1이다. Native emitted bytes0·EOF·read/join 오류0, watchdog 미작동·sampler 종료·owned process 정리를 확인했다. 실행 후 두 PID의 부재와 source59/기존C4코드85/host프로파일52의 working tree·HEAD 바이트를 대조했다. 원본 observation20개도 hash와bytes가 일치한다. 추가 다운로드·warmup·재시도·품질 판정·사용자 검수는0이다.

Pair 내부 시간244.313초와 전체 CLI266.984초를 구분한다. CLI exit0, terminal summary의 `resources_all_passed=true`, 각 arm 상태, 최종 report, HEAD 불변을 함께 확인했다. 모델 입력과 응답·reasoning·token IDs는 로컬에만 보존했고 의미 답변으로 평가하지 않았다.

각 arm은n=1이며24가 항상 먼저다. OS cache·온도·전력·동시 부하를 통제하지 않았고 다른 프로젝트의 프로세스를 종료하지 않았다. 이 값은 안정적인 평균·p95·원인 분리나 서비스 성능 보장이 아니다. 28의 종료 시점 여유686MiB는 추가 동시 추론의 안전성을 증명하지 않는다. 출력은521tokens의 짧은 marker 과제이며928tokens 끝까지의 decode 부하도 입증하지 않는다. 과거 C4 실패를 성공으로 바꾸거나 닫힌 자료를 다시 실행하지 않는다.

## 증거와 다음 판단

- 로컬 원본 `.local/meetings-gpu-placement-v1/report.json`: SHA `c24cc320a381fc4eeddcb3ffa78edc0a578a20ba02ec3a0928bc7b03a3523301`.
- [공개 metadata](../experiments/results/meetings-gpu-placement-v1.json): SHA `63ae6b0483fde0b21eccf2ecee8836ab93ab2a403d7be2d5f707ce0961dda8e4`. 원본의 정확한 복사본이 아닌 파생본이다. 장치 UUID는hash로, RSS 표본은집계와hash로 바꾸고 owned PID를 제외했다. 숫자 결과나 오류 상태는 바꾸지 않았다.
- [CLI 관측](../experiments/results/meetings-gpu-placement-cli-v1.json)은 observer의 정확한 복사본이다. [공개·무결성 기록](../experiments/results/meetings-gpu-placement-publication-v1.json) SHA `d058f2fad5d57dffc0840003282619262a8589eee1d2d1d8de2e619df906290d`는 private20개와59/85/52바인딩 확인을 포함한다.

이 결과는 GPU28을 새 무료 품질 후보에서 검토할 근거다. 기존90초와토큰 조건·일반 문서/복수 회의/혼합 근거/KO·EN/보류 범위를 유지하며 새 source-first 자료와 독립 검토가 필요하다. 원래cal6/6 이후 격리val8/8 관문은 완화하지 않는다. 다음 한 단계는 독립 Astra xhigh의 metadata·code 읽기 검토 후 별도 설계로 기록한다. 제품 기본값은 바꾸지 않았다.
