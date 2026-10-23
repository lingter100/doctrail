# C4-P0 실제 중립 자원 검사 — 원본 실패 종료

2026-10-15, 실행 commit `5dfc95cf7263d8cddeafc7812ab0e83a99ef9f62`. 등록한 normal1/stress1을 한 번 시도했고 전체 결과는 **failed_closed**다. 정상 연결은 통과했지만 부하 JSON 문법이 고정 native parser의 반복 제한에 걸렸고 로그0 조건도 실패했다. 품질 자료·자연어 Q&A 생성·서비스 채택은0이며 동일 실행을 반복하지 않는다.

## 실제 관측

| 항목 | 원본 관측 | 의미 |
|---|---|---|
| 정상 입력/출력 | 62/521tokens, EOS | 전체 출력은 사고·framing·최종 내용 포함 |
| 정상 최종 내용 | 정확한 합성 JSON, 재토큰화6tokens | 사고/최종 분리와 형식만 확인 |
| 정상 요청 시간 | 56.172초 | Java 전체 요청 시간이나 일반 Q&A 시간이 아님 |
| 정상 native RSS | 표본 최대5959.60MiB,215표본 | 실제 peak·GPU 메모리는 미측정 |
| 부하 입력 | 5050tokens, 요청 전달됨 | 생성 응답/완성928token 시간 미측정 |
| 부하 오류 | generation_backend_unavailable | native 진단에 문법 반복 횟수 제한 명시 |
| native 로그 | 2167bytes | 등록한0bytes 조건 실패 |
| 소유 process 정리 | 0.812초, 종료 확인 | 마지막 요청 시작부터 정리까지2.906초 |
| 전체 실행 | 98.640초 | 시작·검증·호출·정리 포함 |

두 요청이 전달됐고 완성 native 응답은 정상1개뿐이다. 부하의 생성 token 수는 응답이 없어 기록하지 않는다. 원본 watchdog은 모두 미작동이며 이번 부하 실패를90초 초과나 메모리 부족으로 해석하지 않는다. 실패 뒤 재시작·metadata 복구·추가 생성은0이다.

## 원인과 한계

부하 schema의 `minLength:10000`이 `char{10000,}` 규칙으로 변환됐다. native 진단은 `number of repetitions exceeds sane defaults`를 보고했다. 연결 전 합성 검사는 이 실제 native 문법 제한을 재현하지 못했다. `--log-disable`을 사용했어도 parser 진단이 표준 오류로 나왔으며 원본 로그를 보존한다. 현재 서비스의 일반 Q&A 문법이 같은 오류를 낸다고 확장해서 주장하지 않는다.

정상 응답이521tokens에56.172초였으므로 전체928token 부하가90초에 들어올지는 별도 위험이다. 이번 부하 요청은 초기에 실패해 그 한도를 실측하지 못했다. 단순 비례 추정은 실제 부하 결과가 아니며, schema 수정만으로 자원 검증을 통과한다고 결론 내리지 않는다.

원본 `sources_unchanged=false`는 실패로 성공 경로의 마지막 검사를 실행하지 못한 상태다. 별도 모델 없는 검사에서는43파일 모두 동결 hash와 같았다. 이 추가 검사는 원본 필드를 소급 변경하지 않는다. 원본 replay도 동일한 failed_closed를 재현했다.

## 보존과 다음 작업

- [원본 바이트 사본](../experiments/results/meetings-c4-resources-v1.json): SHA256 `2b66105860e47180dc29ff78213d43ade81ac29ef2f17ba19ba632440e017729`.
- [native 진단 바이트 사본](../experiments/results/meetings-c4-resource-native-diagnostic-v1.txt): SHA256 `b7f8c9bb70c0d8da6f0331d5b7e604fcd164c84f03506c6b3393238b663cdf53`.
- [별도 보고 영수증](../experiments/results/meetings-c4-resource-reporting-v1.json): SHA256 `369d90174f1c73e58683d3fd7cfaa0004903fc44e1f39c46f5b36df4f1ff4f36`.
- 계획 SHA256 `ba0b3f40134f79a63eee61329ea50dbebc121d7e357a9bbbec0ff8511b4e1e6d`, source43 SHA256 `2ba79c7fba2ad52090392f9256396dc8a1813b6bfae31d6b06a7ba2dd9f2d701`.

다음은 고정 native source에서 문법 제한과 진단 출력을 확인한 뒤, 관측된 속도를 포함해 별도의 무료 로컬 후속 계약을 판단하는 것이다. 원본 source/plan/보고서를 고치지 않는다. 새 품질 질문 작성이나 validation 개방은 자원 검증으로 대신하지 않는다. 일반 문서·복수 회의·한국어/영어 Q&A 범위와cal6/6→격리val8/8 기준은 유지한다. 사용자검수0이며 원래 전체 목표와 Phase1/PR14는 미완료다.

최초 index 바이트 검사에서 Git의 CRLF→LF 변환 때문에 native 진단 사본이 원본과 달라질 것을 검출했다. 해당 진단 파일 하나만 `.gitattributes`의 `-text`로 지정해 실제 바이트를 보존한다. 원본 끝의 빈 줄도 제거하지 않으며 이 원본 파일만 whitespace 검사에서 제외한다. 실험 재실행이나 원본 내용 수정은 아니다.

모델 없는 재생(실패 상태를 확인하므로 CLI 종료값1이 예상된다):

```powershell
uv run --locked --no-sync python -m scripts.probe_meeting_thinking_resources replay --plan data/evaluation/meetings-c4-neutral-plan-v1.json --report experiments/results/meetings-c4-resources-v1.json
```
