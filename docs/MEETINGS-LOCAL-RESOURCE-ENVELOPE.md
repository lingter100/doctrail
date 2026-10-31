# 무료 로컬 후보의 자원 예산 설계

2026-10-26 · 설계만 · 기준 HEAD `3e323c98fd6dea78b6eb67983bfeb3209e697b78`

**다음 행동은 새 정책 `native-rss6-host2-v1`을 후보 script/test 2개에만 구현·검토하는 것이다.** native RSS 중단 기준을 8→6GiB로 줄이고, 호스트 가용 RAM 2GiB 기준을 유지해 시작 조건도 10→8GiB로 맞춘다. 실제 생성 적합성은 미확인이며 이 문서는 실행 등록이나 모델 실행 승인이 아니다.

[원래 계획](MEETINGS-SUMMARY-NEXT-DECISION.md)과 [compact 계획](MEETINGS-LOCAL-CANDIDATE-INPUT-NEXT.md)의 내용·품질 요구는 그대로다. v3의 두 시작 관측은 10,732,064,768B와 10,191,384,576B로 각각 10GiB 미만이었다. 둘 다 CLI/native 0·미소비·출력 없음으로 끝났으며, 현재 가용량을 뜻하지 않는다. 기존 v1/v2 소비 결과와 v3 두 거부 기록을 새 정책의 성공으로 바꾸지 않는다.

[과거 v2 결과](../experiments/results/meetings-local-candidate-actual-v2.json)의 허용된 metadata에서 native RSS 표본 최대 2,910,871,552B, 호스트 가용 RAM 표본 최소 8,184,946,688B, 장치 전체 VRAM 표본 최대 3,162MiB를 확인했다. 시작·template/tokenize만 수행했고 completion은 0이다. 이 값은 생성 최고점, native 전용 VRAM, 이후 실행의 필요 메모리를 입증하지 않는다. 2,474,178,720B GGUF 크기도 실행 메모리 예산으로 대체하지 않는다.

| 대안 | 판단 |
|---|---|
| 기존 native 8GiB / 시작 10GiB 유지 | 변경이 가장 적다. 조건이 충족되는 별도 시점을 기다릴 수 있으나 성공 시점은 알 수 없고 통과할 때까지 재관측하지 않는다. |
| 시작 조건만 낮추고 native 8GiB 유지 | 거부. native 허용량과 2GiB 호스트 여유를 함께 설명할 수 없고 기존 거부를 우회한다. |
| 새 native 6GiB / 시작 8GiB / 활성 여유 2GiB | **선택.** native 허용량도 25% 줄이는 새 운영 예산이다. 더 이른 자원 중단 가능성을 받아들이며 내용이나 생성 한도를 줄이지 않는다. |
| native 7GiB / 시작 9GiB | 가능한 중간 정책이지만 실제 생성 적합성 근거는 마찬가지로 없다. 이번에는 기존 2GiB 여유 기준 한 단위만큼 native 예산도 양보하는 6/8 한 가지를 고정한다. |

6GiB는 측정된 최소 필요량이나 성공 확률에서 산출한 값이 아니다. RAM이 부족할 때 native에 허용할 몫을 명시적으로 줄이는 설계 선택이며, 과거 9.49GiB 관측을 통과시키도록 임계값을 역산하지 않는다. 새 정책을 시험하더라도 실패 후 7/9·8/10 등으로 자동 전환하지 않는다.

| 정책 | native RSS 중단 기준 | 활성 가용 RAM 하한 | 시작 가용 RAM 하한 |
|---|---:|---:|---:|
| 기존 기본값 | 8,589,934,592B | 2,147,483,648B | 10,737,418,240B |
| `native-rss6-host2-v1` | 6,442,450,944B | 2,147,483,648B | 8,589,934,592B |

시작 하한 = native 예산 + 호스트 여유다. 외부 fresh gate 1회와 native Popen 직전 내부 gate 1회가 같은 등록 정책의 시작 하한을 적용한다. 외부 거부면 CLI 0, 내부 거부면 native 0으로 끝내며 두 관측은 예약이 아니다. 실행 중에는 RSS가 상한을 **초과**하거나 가용 RAM이 하한보다 **작으면** 자원 실패로 STOP한다. 정확한 경계값은 허용한다.

이것은 기존 0.25초 표본 감시의 중단 기준이다. OS 메모리 예약·할당 차단·순간 최고점 제한을 보장하지 않고 native 외 프로세스·GPU·공유 메모리까지 하나의 RSS 숫자로 설명하지 않는다. 따라서 2GiB가 항상 남는다는 보장도 없다. 현재 소유권 확인·감시·실패 종료를 유지하되 이 한계를 보고한다.

구현 범위는 `scripts/probe_meeting_local_candidate.py`와 `tests/test_probe_meeting_local_candidate.py`뿐이다. 기존 `probe_meeting_summary_mode.py`와 그 전역 `LIMITS`는 변경·monkeypatch하지 않는다. 후보의 기존 `LIMITS`도 legacy 기본값으로 남기고, 검증된 정책 선택에서만 별도의 불변 effective limits를 만든다. CLI/env/임의 숫자 덮어쓰기는 없다.

최소 경로는 후보 내부의 작은 `ResourceGuard` subclass다. `super().check()`로 기존 identity·8GiB·2GiB 검사를 먼저 수행한 뒤 반환된 같은 표본에 6GiB 기준을 추가한다. 초과 시 `self.failure = "resources"`를 먼저 고정하고 기존 resource 오류 체계로 전파해 inherited `arm`이 이를 deadline으로 바꾸지 못하게 한다. 기존 `arm/stop_owned`와 소유 핸들·lease·drain·5초 cleanup을 재사용하며 새 감시 스레드나 런타임을 복제하지 않는다.

선택된 동일 정책을 시작 감시와 활성 감시의 **두 생성 지점**, HTTP resource callback, 외부/내부 시작 gate, report/terminal에 연결한다. 후보 `LIMITS` 또는 보고 숫자만 변경하는 구현은 불합격이다. legacy 정책은 원래 guard와 수치·기본 동작을 유지한다. 읽기 실패·PID/create-time 불일치·이미 종료됨은 기존대로 실패하며 불확실한 PID를 종료하지 않는다.

등록은 기존 schema 1의 strict shape·정확한 legacy limits·wire 기본값을 보존하고, 새 schema 2에서 `resource_policy: "native-rss6-host2-v1"`과 정확한 전체 effective limits를 필수로 묶는다. unknown 정책·추가 키·정책/limits 불일치는 native 전에 거부한다. budget 2개 외 나머지 limits가 바뀌면 거부한다. 등록 SHA·code hashes·observer companion·report/terminal에 정책과 실제 적용 limits를 일치시킨다.

원문 4개·질문 4개·기존 기준/근거 ID/offset·compact wire·모델/profile/template/decoding은 불변이다. 입력 4096, 출력 요약768/검토128/QA256, 요약+검토 공유120초/QA60초, ctx6144·parallel1·GPU99·f16 KV, 시작120/활성900/정리5/전체1025초, 생성8+검토4회/출력4608토큰도 유지한다. 품질/시간 실패를 자원 정책으로 면제하지 않는다.

후속 synthetic 회귀는 다음을 확인한다. 이번 설계에서는 검사 실행도 하지 않는다.

- 기존 등록·wire·limits와 원래 82개 검사를 보존한다. 새 정책 없을 때 10GiB gate/8GiB guard가 그대로이고, 정책·schema·limits 불일치는 실행 전 거부된다.
- 외부 fresh gate와 내부 Popen gate의 정책 결속, 시작 8GiB-1/8GiB/+1 경계, 거부 후 표본 반복·CLI/native 시작 없음, 내부 gate 표본 1회와 보고 일치를 확인한다.
- legacy와 새 정책 각각 RSS 상한-1/상한/+1, 활성 여유 2GiB-1/2GiB/+1을 확인한다. 특히 6GiB 초과·8GiB 이하에서 새 정책만 실패해야 한다.
- 두 guard 생성 지점·HTTP callback·inherited arm에서 낮은 cap을 실제 적용하고, 초과가 resources로 고정돼 deadline으로 오분류되지 않는지 확인한다. 정책별 report/terminal 값도 검증한다.
- 소유 identity 변경/접근 실패/이미 종료된 프로세스, 정확한 소유 핸들만 정리, latch 이후 추가 completion 0, 기존 cleanup/lease/drain/시간 한도 및 실패 보존을 확인한다.

부모 수용·공개 → source2 최소 구현 → synthetic 검사·독립 검토·정확 소스 CI → **새 등록 버전·새 출력 경로·새 companion** 순서로 진행한다. v3 등록 `d75f2edc…`는 CLI 미소비 상태 그대로 보존한다. 새 실행은 별도 배정 후 fresh gate 1회에서 거부면 종료하고, 통과할 때만 공식 CLI 1회다. 자원 재관측 반복·다른 앱 종료·설정 자동 변경·재시도는 없다.

새 실제 결과에서도 요약4/QA4의 기계 유효성·의미 충족·실패·미실행과 자원/시간을 분리한다. 생성 자원 적합성·완전한 요약/답변·사람 검토·서비스 권한/UI·Phase1 완료는 여전히 미확인이다. 유료 API·클라우드·배포는 추가하지 않는다.
