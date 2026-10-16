# 모델 없는 host 검증 프로파일 구현

2026-10-16. [사전등록 설계](MEETINGS-HOST-PROOF-PROFILE-PLAN.md)에 따라 새 script/test2개를 구현했다. **공식 측정은 아직0회**다. 기존 실험 함수·닫힌 자료와 동결85파일은 그대로다. 모델이나 서비스 동작을 변경하지 않았다.

## 구현과 확인한 범위

`scripts/profile_meeting_host_proof.py`는 별도 합성 Git 저장소에서 고정134파일(Python13+JSON121)을 만든다. Fixture Python은 AST로만 읽고 실행하지 않는다. 원래 `source_files`, path/snapshot/hash, GitProof 함수를 계측하며 원래 전체 반환값과 합성 파일 roster를 구분한다. 모든 pass에서 없는 import 후보가 새로 나타났는지도 확인한다. 실제 저장소 코드는 setup의 동결 증명에만 읽는다.

CLI는 고정 경로 `.local/meetings-host-proof-profile-v1/`를 배타적으로 예약한다. 경로/phase/우회 인자를 받지 않고 기존 출력이 있으면 거부한다. 동결 JSON 자체가 현재 HEAD의 Git blob과 같은지 먼저 확인한 뒤, 봉인된 code roster와 후보 경로 존재 상태를 적용한다. 새 후보는 본문을 읽기 전에 거부한다. 프로젝트 HEAD/index/config를 바꾸지 않으며 합성 Git만 remote 없이 초기화한다.

Cold1/warm6 각 pass에서 HEAD, AST/경로, snapshot/hash, JSON metadata, Git proof, unchanged, HEAD 재확인, 합성17기록의 write/flush/fsync를 따로 측정한다. 중첩 primitive 시간과 상위 component 시간은 합산하지 않는다. Bytes는 성공적으로 반환된 read bytes이며 OS에서 일부 전달 후 read가 실패한 미관측 전송량은 추정하지 않는다. 실패 후에도 부분 counter·첫 오류와 미실행 pass를 남긴다.

최종 합성 검사 **29통과/2skip,56.33초**, Ruff 통과. Windows symlink 권한 부재2건을 건너뛰었고 hardlink 검사는 실행했다. 검사 전후 source/test hash가 같으며 독립 Astra xhigh 읽기 검토가 같은 hash에서 추가 finding 없음을 확인했다. 읽기 검토가 실행 성공을 대신하지 않는다.

검사는 원시 함수만 쓰는 reference와의 결과 비교, 동일 길이·mtime의 byte 변경, HEAD 변경, read 중 변경, 경로 탈출·link alias, 새 import 후보, metadata 변경, 기록 오류, deadline, Git의 실제 freeze/commit 증명, 안전 CLI 거부를 포함한다. 합성 검사로 실제 C4 latency나 답변 정확도를 증명하지 않는다.

## 실패와 보완

초기10실패/11통과/2skip 및 Ruff10건을 보존했다. Root-level 합성 helper가 기존 함수의 `package[0]` 전제와 맞지 않아 실패했고 helper를 하위 폴더로 옮겼다. 기존 동결 함수를 고치지 않았다. 기존 PreparationError의 안전 오류 코드를 잃던 문제도 보완했다. 이후21통과/2skip은 중간 결과다.

마지막 archive deadline 테스트가100ns 예산을 써 실제 Git subprocess를1ms에 중단한1실패/23통과/2skip은 테스트 clock 설정 오류다. 실제300초 예산과 archive17 이후 합성 clock 전진으로 수정했다.25통과 및 앞선29통과/65.23초도 최종 allowlist/CLI 수정 전 결과로 구분한다. 초기 실패는 tool 원문이 남고 로컬 파일에는 **관측 요약**을 저장했으며 이를 원본 stdout 파일이라고 부르지 않는다.

독립 검토와 부모 검토로 실패 read bytes 누락, protocol hash 누락, 최종 기록 뒤 deadline 검사, 동결 파일의 Git 증명보다 앞선 새 후보 읽기, 잘못된 CLI 인자의 traceback을 보완했다. 새 저장 framework나 모델 호출을 추가하지 않았다.

## 동결과 다음 실행

- [구현 검증 영수증](../experiments/results/meetings-host-proof-profile-implementation-v1.json), SHA `1234f1cf724f4e9e9d4da2ca991ed3904bd913f93e42ece10b67a95e3481a3a6`.
- [구현 동결](../data/evaluation/meetings-host-proof-profile-source-freeze-v1.json), SHA `1171f14f7cb176838385723a040ded6921409cc1cfb168833d35e4782687f412`: code50+설계2=52bindings, 후보 경로1352개. Fixture manifest SHA `5637824f61154370b1d0f1335aa9dfd489091c3d687957dd0ba14c7075087384`.
- Script SHA `995b342878c8ef34722787742819d36252d67dbb045ee60cce905ed8ae54e7cc`, test SHA `659546d95c0d298a011332dd687808c9e72959f695b6d65f3591e1c81a1886df`.

동결 source 커밋·필수 CI 성공과 출력 예약 부재를 확인한 뒤에만 다음 CLI를1회 실행한다. 이미 결과가 있으면 반복하지 않는다. 모델·tokenizer·HTTP·품질 호출은0이다.

```powershell
uv run --no-sync python -m scripts.profile_meeting_host_proof
```

Deadline은300초 **I/O 경계 검사**다. Git subprocess에는 남은 timeout을 적용하지만 blocking file I/O를 강제로 선점 중단하지는 않는다. 마지막 기록 후 초과 여부를 확인하고 필요하면 실패 amendment를 최대1회 시도한다. 그 저장까지 실패하면 디스크의 과거 `passed`가 남을 수 있으므로 **최종 CLI exit0 + passed summary + 완전한 receipt**가 모두 필요하다. 최종 elapsed 표시는 자기 자신의 마지막 저장 전 샘플이며 CLI 전체 벽시계 시간과 구분한다. Profile 내부 setup은 Python 시작·import 앞의 비용까지 재는 값이 아니다.

공식 실행 결과와 환경·CLI 관측은 별도 결과 문서에 기록한다. 현재까지 공식 profile/native/tokenizer/HTTP/quality/사용자 검수0, 전체 goal ACTIVE, Phase1/PR14 미완료/draft다.
