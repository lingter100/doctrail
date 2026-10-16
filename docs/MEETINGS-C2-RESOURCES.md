# C2-P0 실제 자원 확인

2026-10-14. 실행 소스 `662965da5d84b0b9749464e00f0ffa30bfcaae7f`. **자원 사전 조건 통과이며 자연어 답변 품질·서비스 채택은 아직 아니다.** [고정 계획](../data/evaluation/meetings-c2-resource-plan-v1.json)의 합성 입력2개만 각각 한 번 실행했다. 이전 평가 질문·oracle를 사용하지 않았다.

[원본 보고서](../experiments/results/meetings-c2-resources-v1.json) SHA256:
`eb138abc5e6af97df68026b3e68c771c7e9d6c4dc974aa58865e894956b4a4d6`.
로컬 원본에서 바이트를 그대로 복사했으며 원문은 공개 가능한 새 합성 자료다.

| 측정 | 정상 계약 | 강제 출력 부하 |
|---|---:|---:|
| native 입력 tokens | 474 | 3,881 |
| native 출력 tokens | 27 | 384 |
| 종료 | EOS | limit |
| 어댑터·watchdog 정리 포함 | 3.079초 | 31.953초 |
| native 입력 처리 | 1.341초 | 8.157초 |
| native 생성 | 1.522초 | 23.607초 |
| native RSS 최대 표본 | 6,243.65 MiB | 6,273.39 MiB |
| RSS 표본 수 | 13 | 126 |

강제 부하는 같은 prompt를 준비하지만 별도 자원 문법으로 무의미한 `x ` 출력을 길게 요구했다. `limit`은 이 검사에서 사전 등록한384-token 부하 달성의 증거이며 정상 답변 성공이 아니다. 실제 서비스 답변의 length 종료는 계속 실패로 처리한다. 이번 공식 tokenizer 길이와 native 길이는 두 입력에서만 같았다.

실제 native 호출2, 재시도0, warmup0, 추출0, 품질 질문0, 유료0, 사용자 검수0이다. 모델·GGUF·llama.cpp·greedy와 nonthinking 설정을 확인했고 native cache는 양쪽0이었다. source28파일 hash가 끝까지 같았으며 native 로그 합계0바이트였다.

두 호출은90초 전에 끝났으므로 **실제 timeout/강제 종료 경로는 실행되지 않았다.** 소유 process의 정상 종료와 새 process의 health·모델 identity 확인을 실제 수행했고 이후 모두 정리했다. 마지막 요청 시작부터 첫 process 종료까지32.734초였다. 재시작 과정의 생성은0이며 취소 후 후속 생성 성공을 뜻하지 않는다. Watchdog 동작은 별도 합성 검사에서 확인한 범위다.

RSS는0.25초 주기의 native 프로세스 표본이며 정확한 peak·GPU 메모리·전체 서비스 메모리가 아니다. 강제 반복 출력의 속도를 자연어 생성 속도로 일반화하거나 이전 C1의 느린 관측과 품질·속도 개선으로 비교하지 않는다. 전원·다른 작업·문법 형태 등 실행 상태를 통제한 벤치마크가 아니다. API 비용0과 로컬 전력 비용 미측정을 구분한다.

## 검증과 다음 경계

고정 전 전체 Python1,325·Ruff, 별도 코드 검토가 통과했다. 정확한 source head의 push CI `38489022676`과 PR CI `38489029729`도 모두 성공했다. GitHub author/committer는 모두 `lingter100`으로 확인했다. Java·React 코드는 바뀌지 않았으며 이번 결과는 Java 요청 지연이나 브라우저 품질 수치가 아니다.

다음 비교는 새 자료에서만 수행한다. 새 C0 줄 단위 대조군에도384-token·90초를 적용해 예산 차이와 근거 단위 차이를 섞지 않는다. 새 정책·실행기·자료 가족을 먼저 고정하고 calibration·격리 validation을 준비한다. C0/C1·미실행4·기존prepared12·M5-B·최종test는 보존한다. PR14와 회의1차는 계속 미완료다.

재현 시 기존 결과 폴더를 지워 같은 실험을 반복하지 않는다. 모델 없는 테스트와 계획의28개파일 hash 검사는 반복 가능하다. 이 실행 명령은 provenance 기록이다.

```powershell
uv run --locked --group retrieval --no-sync python -m scripts.probe_meeting_blocks_resources run --plan data/evaluation/meetings-c2-resource-plan-v1.json
```

이미 사용한 `.local/meeting-blocks-c2-resources-v1`이 존재하면 실행기는 시작 전에 거부한다. 실제 모델 호출이 필요하면 별도 목적과 새 계획을 등록해야 한다.
