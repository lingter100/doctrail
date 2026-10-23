# C3 실제 로컬 자원 검사

2026-10-14, 실행 전 고정 커밋 `d9273c8`. 등록된 정상 요청2단계와 부하2단계를 한 번씩 실행해 총4회 native 호출을 완료했다. 재시도·warmup·유료 호출0이며, 이 결과는 답변 품질 평가가 아니다.

## 실제 결과

| 요청 | 첫 입력/출력 | 둘째 입력/출력 | 요청 전체 시간 | 종료 |
|---|---:|---:|---:|---|
| 정상 합성 요청 |360 / 32 tokens |383 / 24 tokens |8.063초 |양 단계 EOS, 인용·기대 사실 검사 통과 |
| 최대 부하 |5081 / 384 tokens |5081 / 384 tokens |85.547초 |양 단계 등록된 길이 상한 종료 |

정상 둘째 입력383은 실제 첫 계획에서 만들어 native tokenizer로 측정한 값이다. 사전에 이미 측정됐다고 하지 않는다. 부하의 둘째 입력은 독립된 고정 합성 입력이며, 생성한 첫 계획에 대한 답변 품질을 검증하지 않는다. 강제 길이 종료를 정상 답변 완성으로 해석하지 않는다.

부하는 공유90초 기한까지 약4.45초만 남겼다. 한 번의 이 환경 관측이며 다른 부하에서도 같은 여유를 보장하지 않는다. 실제 품질 요청의 지연은 별도로 측정해야 한다.

| 운영 확인 | 결과 |
|---|---|
| 소유 프로세스 정리 |1.015초, 종료 확인 |
| 마지막 요청 시작부터 최초 프로세스 정리 |86.609초, 상한120초 이내 |
| metadata 재시작 |1회 성공, 같은 모델/설정 식별 확인, 추가 생성0 |
| 재시작 프로세스 정리 |0.984초 |
| 전체 실행 |191.859초; 시작·재시작 포함, 요청 응답 시간과 다름 |
| 원본/소스 |66바인딩 및 등록 입력 불변, 원본 재생 검증 통과 |
| 운영 로그 |0bytes |
| Native RSS 관측 최대 |정상6408.61MiB / 부하6921.80MiB, 표본31/331회 |
| 시스템 가용 RAM |정상 전3415146496bytes, 부하 후2652164096bytes |

RSS는 표본 중 최댓값이며 전체 프로세스/GPU의 실제 peak 측정이 아니다. GPU 메모리 peak와 전력비·금액은 측정하지 않았다. 무료 로컬 실행에서 유료 API 호출은0이다.

## 보존과 재생

원본 `.local/meetings-c3-neutral-v1/report.json`과 [공개 원본 사본](../experiments/results/meetings-c3-resources-v1.json)은 바이트가 같다. SHA `f15669fb55f131e077f7650092a4680c4a80ac65a099b522b78230bfabad0132`. [설명 영수증](../experiments/results/meetings-c3-resource-reporting-v1.json)은 실제 토큰·지연·정리·노출 이탈 문서와 원본 hash를 연결한다. 동결 `validate_neutral_report`로 raw/native trace·두 단계 재구성·4호출 ledger·정리/복구를 모델 없이 재생했다.

실제로 사용한 명령은 다음과 같다. 이미 소비한 출력·ledger를 지우거나 이 실험을 다시 실행하지 않는다.

```powershell
uv run --locked --no-sync --group retrieval python -m scripts.probe_meeting_requirements run-neutral --plan data/evaluation/meetings-c3-neutral-plan-v1.json
```

## 다음 품질 실행의 고정

양 split의 승인된 문항/공식 입력, 실제 자원 보고서, 서로 다른 judge의 실제 노출 자기신고와seed를 `meetings-c3-quality-plan-v1.json`에 묶었다(SHA `c5e3f11479e9f240befe1ffcaf83aed0ddcf2288ea294a10bfe0432574def24b`). Calibration용 모델 없는 `check`가 통과했다. 이 등록 시점 품질 생성0이며, 커밋 뒤6문항의 단발 실행을 진행한다. 전체6/6의 독립 최종답변 판정과 운영 조건을 충족해야 validation8의 품질 실행을 열 수 있다.

`meetings-c3-execution-reporting-v1.json`은 원래 부모 source 일부 노출과 judge별metadata 노출을 후속 결과에 연결한다. 완전 비노출·완전 맹검·자동 서비스 채택을 주장하지 않는다. 최초 validation 사전검토7/1 거절과 별도 v2 8승인을 모두 보존한다. 인간 검수0, phase1/PR14 미완료 상태다.
