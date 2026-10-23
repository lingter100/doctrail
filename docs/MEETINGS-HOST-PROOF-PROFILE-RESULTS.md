# Host 검증 비용: 합성 프로파일 실제 결과

2026-10-16, source `3a1268f42277f09c3e2674be1ebcd375a01aaa19`. Push38863819959와 PR38863824654의 필수3job 성공을 확인한 뒤 등록한 CLI를 **1회** 실행했다. Cold1+warm6 모두 완료했고 CLI exit0, 최종 passed summary, 완전한 receipt가 일치했다. 추가 profile/native/tokenizer/HTTP/품질 호출은0이다.

## 측정 결과

| 항목 | 관측값 |
|---|---:|
| 별도 setup | 14.725초 |
| Cold pass | 20.083초 |
| Warm6 중앙값 | 2.933초 |
| Warm6 범위 | 2.786–5.329초 |
| 내부 terminal checkpoint까지 | 55.249초 |
| 외부 관측 CLI 벽시계 | 56.613초 |

Warm 개별 시간은3.409,5.329,2.988,2.879,2.823,2.786초다. Cold는 프로세스 내 Git proof cache가 비어 있다는 뜻이며 OS cache를 비우지 않았다. 내부 checkpoint 시간은 자기 자신의 마지막 기록 이전 값이다. 외부 관측은 별도 자식 CLI의 시작·import·종료까지 포함하며, 두 시간의 차이를 특정 원인에 배분하지 않는다.

| Warm 구간 | 중앙값(ms) |
|---|---:|
| HEAD 확인 | 120.381 |
| AST·후보 경로 | 133.917 |
| 전체 snapshot/hash | 740.007 |
| JSON metadata 검사 | 93.254 |
| Git proof | 846.804 |
| unchanged 재검사 | 768.621 |
| HEAD 재확인 | 126.193 |
| 합성17개 기록·flush·fsync | 65.339 |

각 열의 중앙값은 서로 다른 pass에서 나올 수 있으므로 합계를 전체 중앙값이라고 부르지 않는다. Snapshot/hash·Git proof·unchanged 세 구간의 실제 pass별 시간 비중은 **78.61–83.09%**였다. Git proof에는 HEAD 명령 비용도 포함돼 있으므로 이를 순수 파일 I/O 비중으로 해석하지 않는다.

Cold Git proof는 `git show`134회와 HEAD1회였다. Warm Git proof는 매번 HEAD1회, `git show`0회다. 각 warm pass는1,953,792bytes의134파일을 세 번 읽고 hash했다. AST의53,248bytes 읽기를 더해 전체 component read5,914,624bytes, hash5,861,376bytes다. 별도 HEAD 확인·재확인까지 포함하면 pass의 전체 Git subprocess는3회다. Archive는17개/69,632bytes/flush17/fsync17이며 native event가 아니다.

## 해석과 다음 판단

확인한 사실은 **warm Git object 조회는 이미 캐시되고, 파일 snapshot 검사가 반복된다**는 것이다. Git 명령 전체를 없애거나 mtime만 믿는 변경을 정당화하지 않는다. 반복 검증 결과를 안전하게 재사용하는 작은 비교의 후보는 생겼지만, 최적화 구현이나 개선 효과가 입증된 것은 아니다.

이 workload는 합성 Python13개와 JSON121개다. 실제 C4의 전체 import graph·metadata·자료·HTTP·모델 응답 처리를 재현하지 않는다. 계측 wrapper가 추가하는 경로 guard와 recorder 비용도 분리하지 않았다. 따라서 **2.933초를 C4 host 시간으로 대입하거나, 이 값을 줄이면 둘째 요청이 성공했을 것이라고 말할 수 없다**. 첫 C4의18.755초 차이는 여전히 원인 미확정이다.

이제 무료·로컬 조건에서 proof 중복 개선과 native/GPU 배치 검토 중 어느 한 작업이 실제 품질 평가 완료에 더 도움이 되는지 비교한다. 기존 Astra xhigh 역할의 판단과, 반복 실패에 대한 사용자의 제한적 max 비교 지시에 따른 별도 Astra max 읽기 검토를 사용한다. 아직 새로운 policy·resource 실행·최적화를 등록하거나 실행하지 않는다. 닫힌 C4/기존 pool은 재사용하지 않으며 서비스90초와 토큰 한도를 늘리지 않는다.

## 환경·증거·재현 한계

실행 환경은 Windows build10.0.26200, AMD64, Python3.11.15, processor string `Intel64 Family 6 Model 170 Stepping 4, GenuineIntel`이다. OS cache·동시 부하·백신/파일시스템 영향을 통제하지 않았고 한 머신의 작은 표본이다. 최고 warm 값5.329초도 제거하지 않았다. Linux CI 성공을 Windows 시간 측정과 합산하지 않는다.

- [원본 receipt의 정확한 공개 복사본](../experiments/results/meetings-host-proof-profile-v1.json), SHA `c746ebd3615b79c91fadef5d1d6b4d7ce154c447731f2ab9e27f86284203c656`.
- [별도 CLI·CI·환경 관측](../experiments/results/meetings-host-proof-profile-cli-v1.json), SHA `7098ae1c9ea3523519dacbfc36edbbd88d894075139e985fc4b6054d96f0cc1e`. 실제 종료코드0, summary, 빈 stderr, source HEAD/52개 bytes 불변을 기록했다.
- [공개 복사·중복 없는 집계](../experiments/results/meetings-host-proof-profile-publication-v1.json), SHA `affb9cae555cfa87653c42ba8378fd4545ebe9e953190f53772dde5f90f915da`. 원본2개150,684bytes가 같고 절대 환경 경로/credential 패턴0건이다. 패턴 검사가 모든 민감 값 부재의 보장은 아니다.

실제 생성한 fixture/Git/archive는 `.local/meetings-host-proof-profile-v1/`에 남겼고 지우거나 다시 실행하지 않는다. 저장소에는 재현 가능한 generator·정확한 fixture hash·code freeze와 측정 metadata를 공개했다. 원본 설정은 [설계](MEETINGS-HOST-PROOF-PROFILE-PLAN.md), 구현·합성 검사와 I/O 경계 한계는 [구현 기록](MEETINGS-HOST-PROOF-PROFILE-IMPLEMENTATION.md)을 따른다. Snapshot/path 검사는 관측 경계의 상태를 확인하며 파일시스템 전체를 잠그는 보장이 아니다.

이 결과는 모델 성능 개선·서비스 준비·사용자 검수 완료가 아니다. 전체 goal ACTIVE, Phase1/PR14 미완료/draft이며 다음 작업은 비교 검토 후 별도 기록한다.
