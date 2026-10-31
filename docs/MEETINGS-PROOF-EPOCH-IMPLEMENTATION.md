# Bounded snapshot reader 구현과 검증

2026-10-20. [설계](MEETINGS-PROOF-EPOCH-PLAN.md)의 64KiB reader와 단발 합성 비교 도구 NEW4를 구현했다. **공식 비용 비교는 아직 실행하지 않았다.** 기존 C5 실패와 동결 코드·자료는 변경하지 않았다. 전체 회의 지능형 관리1차/PR14는 아직 완료되지 않았다.

## 구현

원래 snapshot 함수를 명시적 path/stream adapter로 그대로 호출하는 reference와, 같은16MiB+1 상한까지64KiB씩 읽는 candidate를 비교한다. Nonempty short read를 계속 읽고 close→overflow→stamp 검사 순서를 지킨다. Hash·AST·현재 HEAD·committed bytes·path/alias·negative import·마지막 재읽기를 생략하지 않는다.

측정용 새 remote 없는 Git fixture는40개 payload/393,216bytes와12,852bytes manifest다. 고정된 reference 두 경계→candidate 두 경계만 측정한다. 실제 Git blob cache의 cold/warm 의미와6개 논리 소비 순서를 양쪽 동일하게 유지한다. 읽기 요청 크기와 실제 반환 bytes를 구분하며, OS disk I/O·RSS·실제 할당량으로 해석하지 않는다.

## 실제 검증과 원래 실패

| 검사 | 확인 결과 | 범위 |
|---|---|---|
| 첫 검사 | 51passed/1failed/1skip/2errors,64.52초; Ruff11 | 계수 기대값 오류와 Windows 과도한 parameter ID; 원본 로그 보존 |
| 수정 후 전체 NEW2 검사 | 73passed/1skip,62.04초; Ruff 통과 | 마지막 setup 경계 수정 전; 검사 중 NEW4 SHA 동일 |
| 마지막 변경 영향 검사 | 8passed/45deselected,11.24초; Ruff 통과 | 최종 NEW4 SHA 동일; CLI/deadline/persistence/accounting |
| 독립 코드 읽기 검토 | 최종 변경에 남은 blocker0 | 실제 Astra high 별도 역할; 직접 테스트/사용자 검수0 |

겹치는 검사 수를 합산하지 않는다. 전체73개 결과를 최종 코드 전체 검사로 바꾸어 쓰지 않는다. Windows symbolic-link 검사는 OS 권한으로 skip했으며 그 조건의 로컬 검증 공백이 남았다. 최종 커밋의 필수 CI가 전체 회귀를 다시 검증해야 한다.

검토에서 Git 통신 예외의 owned process 정리·생성 후 남은 timeout, setup AST/hash 계수, 원래 core에 없던 측정 JSON32개 해석, 실제 동결/CI/Git 거부 검사, 첫 output path 검사부터 동일 deadline/meter 사용을 보완했다. 처음 통과한 것처럼 기록하지 않으며 초기 Ruff11/추가2와 테스트 실패를 .local에 보존했다.

부모의 최초 동결 helper는 repository import 경로가 없어 파일 생성 전에 실패했다. PYTHONPATH를 명시한 뒤 동결/봉인 검증이 통과했으며 모델·공식 비교 실행과 무관한 환경 오류로 별도 기록했다.

## 동결과 증거

- [구현 영수증](../experiments/results/meetings-proof-epoch-implementation-v1.json): 실제 검사·전후 코드 SHA·실패 로그 hash·역할/한계.
- [소스 동결](../data/evaluation/meetings-proof-epoch-source-freeze-v1.json):27 bindings/Python23/import candidates710, SHA261abc74b39862f9768387def7a86629ea6345dd43ccb692f6abed6f2174a4f1.
- [Fixture spec](../data/evaluation/meetings-proof-epoch-fixture-spec-v1.json): SHA1a0e9d794f3e6e5a0e52a4281e01ed2f88d3be4828d28ee540661633c8e3584e.
- 기존 C5/C4/GPU/host freeze76/85/59/52의 중복 제거106개 binding은 원래 bytes와 동일했다. 이 수를 새 테스트 수로 합산하지 않는다.

## 재현과 다음 실행

일반 회귀 검사는 다음으로 실행한다. 이는 공식 비교를 소비하지 않는다.

```powershell
uv run --no-sync python -m pytest tests/test_meeting_bounded_snapshot.py tests/test_probe_meeting_bounded_snapshot.py -q
uv run --no-sync ruff check src/doctrail/meeting_bounded_snapshot.py scripts/probe_meeting_bounded_snapshot.py tests/test_meeting_bounded_snapshot.py tests/test_probe_meeting_bounded_snapshot.py
```

다음은 source/freeze/spec 커밋의 실제 push·PR CI3job을 관측하고, source SHA·두 실행ID·freeze/spec hash를 결합한 CI receipt를 별도 커밋하는 것이다. 그 뒤에만 `uv run --no-sync python -m scripts.probe_meeting_bounded_snapshot`을1회 실행한다. `.local/meetings-proof-epoch-v1`이 있으면 삭제·재개·재실행하지 않는다. CLI exit0·terminal summary·정확한 receipt hash·완전한4경계·최종 persistence/deadline을 함께 확인한다.

도구는 커밋된 부모의 GitHub 관측 영수증과 Git bytes/HEAD를 검증한다. 오프라인 실행이 GitHub CI 자체를 인증한다는 뜻은 아니다. 설계6ea47c3의 push CI는3job 통과했으나 당시 PR14 head는e18f595로 관측됐고 동일 설계 SHA의 PR 실행은 보이지 않았다. 이 차이를 [관측 원본](../experiments/results/meetings-proof-reader-design-ci-observation-v1.json)에 보존하고 최종 source SHA의 PR CI로 대신 추정하지 않는다.

## 남은 한계

실제 속도/allocator/RSS 개선·C5 성공 가능성·답변 정답률·서비스 배포는 측정0이다. 합성 n=1 고정 순서는 OS cache/배경 부하를 통제하지 못한다. Blocking I/O 선점 중단과 모든 관측 사이에 끝난 ABA의 검출을 보장하지 않는다. 결과가 좋아도 별도 품질 후보 등록과 실제 의미 평가 전에는 서비스에 채택하지 않는다. 사용자 검수는 별도로 필요하다.
