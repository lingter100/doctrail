# C4 별도 호환성 자원 검사 결과

2026-10-16. 상태는 **passed_resources_only**다. 원래 C4-P0 실패를 고치거나 재실행한 결과가 아니라, 사전에 등록한 동일예산 호환성 후속의 새 중립2건을 한 번 실행했다. 실제 품질 질문·사용자 검수·모델 채택은0이다.

## 고정과 실행 순서

- 설계259712c → NEW4/source52 고정 a929359 → 필수 CI 통과 → 단발 offline 준비 → plan/preparation 커밋4ba51b9 → 새 native2 순서다.
- a929359의 push38842697501/PR38842703171, 입력4ba51b9의 push38843554022/PR38843558362가 각각 필수3job 모두 성공했다. 입력 PR은 Python2235통과/21환경skip/기존warning1(78.87초), 실제 Java browser47통과/0실패다.
- 캐시 tokenizer를 한 번 로드해 고정 완성JSON2052tokens>928을 확인했다. 새 입력은 normal63/stress5048이며 literal이나 입력을 결과에 맞춰 다시 고르지 않았다.
- 실제 실행 HEAD는 `4ba51b9a6eefb1dfd78e2732ee8fe3933fe3bc0c`다. 같은 캐시 Qwen3.5-9B Q5_K_M, 고정 llama.cpp, GPU24/context6144/input5120/전체출력928/요청사고512/공유요청90초를 유지했다.

## 실제 관측

| 측정 | 정상 | 부하 |
|---|---:|---:|
| 입력 토큰 | 63 | 5,048 |
| 실제 전체 출력 토큰 | 521 | 928 |
| 종료 | EOS | length |
| 최종 content 재토큰 수 | 6 | 414 |
| 요청 시간 | 37.984초 | 88.000초 |
| sampled native RSS 최대 | 6,248.887MiB | 6,313.855MiB |
| RSS 표본 수 | 149 | 343 |
| request watchdog 발동 | 없음 | 없음 |

부하의414재토큰·length 종료는 미완성 합성 padding을 끝까지 생성한 자원 검사다. 정상 답변의384재토큰 수용 조건을 통과한 자연어 답변으로 취급하지 않는다. 재토큰 수는 native가 생성한 사고/최종 구간의 정확한 분할 토큰 수가 아니다. 요청사고512는 실제 적용값이 응답에 직렬화된 독립 hard cap이 아니다.

원래 실패를 일으킨 큰 반복 규칙 대신 고정 literal이 실제 바이너리에서 처리됐다. 최초 및 metadata 재시작 프로세스 모두 합친 stdout/stderr emitted0bytes, EOF, reader join을 확인했고 read/join/cleanup 오류는0이었다. 정리는0.969초와0.875초로 각각5초 안이다. 마지막 요청 시작부터 정리까지88.984초, 최초 시작·두 요청·정리·metadata 재시작 전체245.844초다. metadata 재시작1회에서는 새 생성 없이 identity만 대조했다.

두 dispatch가 모두 응답과 자원 계약을 완료했다. 원래 C4의2dispatch/1완성과 합치면 누적4dispatch/3완성이며, 원래 실패는 그대로 남는다. source52의 실행 전후 일치와 별도 post-run hash검사가 통과했다. 다운로드·유료 사용·품질 호출·서비스 채택은0이다.

## 해석과 한계

88초는90초 한도보다2초 작다. 단일 장비·단일 실행이며 여유가 작으므로 p95 지연이나 운영 안정성을 증명하지 않는다. 정상 시간이 원래56.172초보다 짧아도 새 중립 입력과 실행 시점이 다르므로 성능 개선 실험으로 비교하지 않는다. RSS는 표본으로 본 호스트 메모리이며 실제 peak나 GPU 메모리가 아니다.

이번 결과는 사고를 쓰는 단일 호출의 연결·문법·자원 조건만 확인한다. 인용 정확성·필수정보 완전성·근거 지지·한국어/영어·근거 없는 질문의 보류는 아직 검증하지 않았다. 일반 문서와 여러 회의를 포함하는 원래 범위를 유지하며, 새 품질 policy/도구를 고정한 뒤 새 source-first calibration6과 격리 validation8을 준비한다. Calibration6/6을 만족하기 전 validation을 열지 않고 서비스에 자동 채택하지 않는다.

## 보존과 재현

| 산출물 | SHA-256 |
|---|---|
| `data/evaluation/meetings-c4-compat-source-freeze-v1.json` | `de8bfc6b92603b1cd5d999afb5788222c7b71ccda1e7a9a3c0aa5a7df36ef61e` |
| `data/evaluation/meetings-c4-compat-neutral-plan-v1.json` | `8454ddfe48e6f3f5eaff67a4b5abeedc049c2f608f88c25bc20fd83d64b9ead6` |
| `data/evaluation/meetings-c4-compat-neutral-plan-v1.preparation.json` | `3e0f795462aa05bc5138b0e16cb963241a16e35d6764f74f51bc7c8e610674c1` |
| `experiments/results/meetings-c4-compat-resources-v1.json` | `4221cf730c348b4ba6d5741f47a818e1c2ee68cdd337e21a05947d5379bd6043` |
| `experiments/results/meetings-c4-compat-reporting-v1.json` | `01cfaa954d771c756a342b71c81e343e6813a4ced62126b388908be4e3f3afe5` |

공개 raw는 로컬 원본199,199bytes와 동일하다. 개인정보 경로·인증정보 검사를 거쳤으며 합성 입력/응답은 결과 artifact에만 보존하고 운영 진단 내용은 저장하지 않았다. 원본 자원 실패·2167byte 진단·닫힌 C3 및 이전 자료는 수정하지 않았다.

저장된 결과를 모델 없이 다시 검사하는 명령은 다음과 같다. 완료된 register/run은 반복하지 않는다.

```powershell
uv run --locked --no-sync python -m scripts.probe_meeting_thinking_compat_resources replay --plan data/evaluation/meetings-c4-compat-neutral-plan-v1.json --report experiments/results/meetings-c4-compat-resources-v1.json
```

전체 goal은active, 회의 Phase1과 PR14는미완료/draft다. 다음 독립 제품 수정은 저장 요청 중 뒤늦게 입력한 담당자·상태·요약이 유실되는 React 경합이며, 이 문서 작성 시 아직 실제 재현·수정 검증 전이다.
