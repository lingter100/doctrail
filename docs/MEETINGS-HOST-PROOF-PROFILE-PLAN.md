# Host 무결성 검증 비용 — 모델 없는 프로파일 사전등록

2026-10-16. `meetings-host-proof-profile-v1`은 새 측정 도구의 설계이며 아직 구현·실제 프로파일을 실행하지 않았다. 기존 C4 품질 실패, 동결 코드85, 모든 닫힌 pool은 변경하지 않는다. 부모가 C4 실패 문서·원본 보존·프로젝트 Git을 담당하고, 이 설계 역할은 이 문서와 [protocol](../data/evaluation/meetings-host-proof-profile-protocol-v1.json)만 작성한다.

## 확인한 사실과 확인하지 못한 원인

허용된 공개 [실패 metadata](../experiments/results/meetings-c4-quality-failure-metadata-v1.json)에서 첫 요청은 전체86.157초, native prompt3.999651초와 prediction63.402728초였다. 합계67.402379초와 전체의 차이는18.754621초이며90초까지 여유는3.843초였다. 이 차이는 Git 비용의 실측이 아니다. HTTP, template/tokenize, native 계측 밖의 작업, 파일 검사·기록·응답 처리 등이 섞여 있다. 두 번째 요청은91.343초에 deadline 실패했고 native response/timing/output 계수는 관측하지 못했다. Watchdog 이후 예외 처리·thread/process 대기를 포함할 수 있는 경과값을90초 성공으로 재해석하지 않는다.

현재 runner는 요청 전과 전송 직전 callback에서 `verify()`를 수행한다. 뒤의 검증은 동일90초 안에 포함된다. `source_files()`의 AST/경로 탐색, metadata 검증, 반복 hash 순회가 조사 대상이다. `GitProof`는 이미 Git object 증거를 캐시하므로 모든 warm 검사에서 모든 `git show`를 다시 실행한다고 주장하지 않는다. Offline 준비 CLI의57초대 경과도 서비스 지연이나 Git 비용으로 대체하지 않는다.

이 프로파일은 실제 폐쇄 C4 요청을 재생하지 않는다. 첫 요청의18.755초를 원인별로 소급 배분하거나, 최적화하면 두 번째 요청이 성공했을 것이라는 인과관계를 입증하지 않는다. Native 응답을 저장한 파싱 응답 수와 wire 수신/생성 완료 수도 구분한다. 기존 C4는 전송 시도2·저장된 파싱 응답1·구조 수용1·의미 판정0으로 닫힌 상태다.

## 접근·실행 경계

- Native/model/tokenizer/HTTP/품질 호출, 다운로드, cloud/paid 서비스는 모두0이다. 기존 native launcher와 quality `check/run/prepare/audit` entrypoint를 호출하지 않는다.
- 실제 실행계획의 phase 참조, 현재·과거 source/question/context/oracle/answer, raw report, trace 값, 격리 validation/test 의미 자료를 열지 않는다. 실패 metadata의 trace 경로도 따라가지 않는다.
- 실제 저장소에서 읽을 수 있는 것은 사전 고정한 tooling/transport Python 코드와 공개 설계 문서, 이 protocol뿐이다. Profile 실행은 실패 metadata도 다시 읽을 필요가 없다. 구현에서 필요한 `.py` import closure는 코드 전용 allowlist로 고정하며 dataset/fixture JSON·Markdown으로 확장하지 않는다. 실제 저장소의 코드 bytes·closure·HEAD 확인은 측정 pass 밖의 setup 무결성 확인용이며 측정 workload로 세지 않는다.
- Workload는 새 전용 합성 Git 저장소에 기계적으로 만든 Python·metadata134개뿐이다. 실제 항목의 ID·문장·문맥·oracle 구조를 복사하거나 길이에 맞춰 재구성하지 않는다. 기존 `source_files/path/snapshot/GitProof` 등 결정적 primitive를 수정 없이 재사용하되 측정 root는 모두 합성 fixture 저장소로 고정한다. 실제 저장소의 AST 후보 경로 탐색이나 Git byte proof를 측정 pass에 섞지 않는다.
- 현재 단계에서는 최적화 verifier, 새 답변 policy, 모델 호출, 실제 profile 실행을 구현·실행하지 않는다. 설계 커밋 이후의 허용 구현은 계측 script와 합성 검사뿐이다. 모델 성능 측정용 새 평가 플랫폼을 만들지 않는다.

## 고정된 인공 workload와 횟수

Official fixture는 총134개 bound file이다. 이 숫자는 공개 metadata의134 bindings에서 착안한 인공 부하 크기이며 실제 binding 목록을 복제하지 않는다. 구성은 **합성 Python13개×4096bytes + JSON72개×4096bytes + JSON49개×32768bytes**로 고정한다. Python13개는 기존 `source_files()`의 고정 `NEW_FILES` seed12개 경로와 deterministic helper1개다. 이13개의 내용과 import graph는 기계적으로 만들고 AST로만 읽으며 실행하지 않는다. JSON121개만 단순 `schema_version/ordinal/padding` 구조를 사용한다. 모든 파일은 UTF-8 ASCII·LF의 기계적 padding을 사용하고 query·context·answer·reasoning·oracle나 실제 내용·길이를 복사하지 않는다. 정확한 fixture roster와 raw SHA256, 고정 byte 생성 알고리즘·양성/음성 import 후보는 구현 코드·검사와 함께 실행 전에 봉인한다.

AST 탐색과 후보 경로 존재 검사는 **합성 fixture root 안에서만** 수행한다. 기존 `source_files()`의 전체 반환값을 봉인하되 비존재 constant 경로의 본문은 읽지 않고 실제 데이터 파일로 연결하지 않는다. 전체 반환 경로와 실제134개 bound file 집합을 구분한다. 허용되지 않은 경로·본문 접근은 읽기 전에 실패해야 한다. 새 exclusive fixture root 안에만 remote0 Git 저장소를 만들고134개 합성 bytes를 한 번 commit한다. `GitProof`는 이134개와 합성 HEAD만 증명한다. Git init/add/commit과 fixture-local 설정은 해당 합성 root의 setup에만 허용하며 network·hook·signing 호출을 금지한다. 실제 프로젝트 HEAD/index/config와 사용자 전역 Git 설정은 바꾸지 않는다. 부모는 측정 동안 프로젝트 HEAD를 고정한다. 실제 코드 allowlist/closure 무결성 확인과 fixture 구축·합성 commit은 setup 시간으로 분리하며 official 단발 예약 안에서 한 번만 수행한다. `.git` 내부 파일과 봉인 manifest·출력은134개 bound file에 포함하지 않는다.

측정은 **cold1 + warm6, 총7개 guard pass**다. Cold는 같은 프로세스의 증거 cache가 비어 있다는 뜻이며 OS disk cache를 비웠다는 뜻이 아니다. Warm6은 같은 fixture bytes·HEAD와 같은 `GitProof` instance를 사용한다. 정해진 횟수의 재실행·추가 warmup·자동 retry·성공할 때까지 반복은 없다. Setup을 포함한 전체 profile 상한은300초이며 중간 실패·상한 초과도 단발 예약을 소비한다. 이300초는 모델 없는 측정 작업의 종료 한도이며 서비스90초를 변경하지 않는다.

각 pass는 고정 순서로 합성 HEAD 확인, 합성 Python13개의 AST/후보 경로 탐색, 합성134개 전체의 path/alias/snapshot/hash, JSON121개 metadata 검증, 합성134개의 Git byte proof, 전체 unchanged 재검사, 합성 HEAD 재확인을 수행한다. 실제 저장소 코드 무결성용 roster는 이 측정 집합에 포함하지 않는다. 같은 pass 안의 반복 읽기를 제거하지 않아 기준 비용을 유지한다. 그 뒤 별도 `archive` 구간에서17개 인공 metadata 기록을 exclusive write/flush/fsync한다. 각 기록은4096bytes로 고정하고 값이나 크기를 실제 trace에서 가져오지 않는다. Output은 fixture 밖의 새 pass별 폴더에만 쓰며 다음 pass의 binding 집합에 포함하지 않는다. 이17개는 파일 기록 부하이며 native 이벤트나 전송 시도로 세지 않는다.

이는 폐쇄 runner 전체 `verify()`의 동일 workload 재현이 아닌 primitive 수준의 통제된 구성이다. 파일 수·크기·import graph·archive가 인공적이므로 실제 C4 또는 향후 서비스 요청 지연으로 외삽하지 않는다.

## 계측과 무결성 동등성

구간은 `head`, `ast_paths`, `snapshot_hash`, `metadata_validation`, `git_proof`, `unchanged`, `head_recheck`, `archive`로 구분한다. Monotonic elapsed ns와 호출 수, 읽기/쓰기/hash bytes, snapshot/path 검사 수, Git subprocess 수와 command 종류, fsync 수를 기록한다. Setup의 실제 코드 무결성 확인·합성 Git 생성 통계와 pass의 합성 workload 통계를 분리한다. 중첩 구간은 inclusive/exclusive 시간을 구분해 이중 합산하지 않는다. Count가 함수 호출인지 OS syscall인지 명시하며 관측하지 않은 syscall 수를 추정하지 않는다. stdout/stderr나 읽은 원문을 timing log에 넣지 않는다. Setup/전체/각 pass 시간을 별도로 기록하고 cold 값과 warm6의 개별 값·median/min/max를 공개한다. 동시 부하·OS cache·계측 overhead는 통제되지 않은 한계로 남긴다.

계측 wrapper는 원래 primitive의 반환값·예외·순서를 변경하지 않는다. 합성 검사에서 wrapper 없는 reference와 계측 경로가 같은 fixture의 accept/reject, hash/binding/closure/HEAD 결과를 내는지 확인한다. 깨끗한 fixture, byte drift(크기·mtime이 같아도), HEAD drift, read 중 변경, path escape, symlink/reparse/hardlink alias, metadata tamper, 새 import 후보 생성, archive 오류를 포함한다. Platform에서 불가능한 link 검사는 skip으로 공개하고 다른 OS에서의 증명을 주장하지 않는다. 이 검사는 테스트 임시 폴더만 사용하며 official profile 출력 예약을 만들지 않는다.

현재 `source_files()`는 파일 내용뿐 아니라 후보 경로의 존재 여부에도 의존한다. 향후 AST 결과를 캐시하려면 양성·음성 후보 경로 목록과 모든 관련 bytes를 봉인하고 매 dispatch에서 존재 상태와 path guard를 다시 검증해야 한다. 기존85개 hash만으로 캐시하면 새 local/shadow module을 놓칠 수 있다. 이 프로파일에서는 기존 탐색을 유지하며 음성 후보가 생성되면 reference와 동일하게 closure 변화/실패를 검출한다.

향후 최적화도 실제 pre-dispatch의 전체 byte/HEAD/path 검사, metadata·역할 binding, 요청 바이트, 전송 전 durable reservation과90초 callback 포함을 유지해야 한다. mtime-only cache, 검증 생략, deadline 밖으로의 비용 이동으로 성공 처리하지 않는다. Validation의 원래cal6/6 gate와 byte-bound replay도 유지한다. 이 문서는 그런 최적화의 구현 승인이 아니다.

## 다음 구현 담당과 최소 interface

설계 두 파일을 부모가 먼저 커밋한다. 그 뒤 부모가 지정하는 실제 Astra high 구현 역할이 다음 **NEW2 파일만** 소유한다.

- `scripts/profile_meeting_host_proof.py`: fixture 생성, component 계측, 단발 실행/metadata report CLI.
- `tests/test_profile_meeting_host_proof.py`: 위 경계·동등성·계수·실패 보존의 합성 검사.

최소 interface는 `prepare_fixture(root, spec) -> sealed_manifest`, `measure_pass(fixture, proof, recorder) -> pass_metadata`, `run_profile(root) -> report`, CLI `python -m scripts.profile_meeting_host_proof`다. Arbitrary input/output/phase/closed-artifact path 인자를 받지 않는다. Timing clock/recorder는 합성 검사에서 주입할 수 있으나 official CLI에 skip/bypass 옵션을 두지 않는다. 측정 대상 기존 함수를 고치거나 새 wrapper를 서비스 호출 경로에 연결하지 않는다.

Official output은 `.local/meetings-host-proof-profile-v1/` 하나다. 시작 전에 exclusive directory를 예약하고 존재하면 읽어 이어 실행하거나 지우지 않고 거절한다. 실패 원인·이미 끝난 pass·미실행 pass·counter·partial receipt를 보존하며 로그에는 safe error code/type만 쓴다. Git proof나 저장이 실패하면 성공 표시를 만들지 않는다. Model/tokenizer/HTTP/download/quality counter는 각각 명시적0이고 코드가 그 경로에 도달하면 실패해야 한다.

구현 완료 후 부모/독립 검토자가 NEW2, 허용 dependency closure, fixture generator/spec/roster, 이 설계 두 파일을 hash로 동결하고 커밋·필수 CI를 확인한다. 이 구현 동결 commit이 실행등록을 겸한다. 해당 선행조건이 충족되면 이미 승인된 범위 안에서 official cold1+warm6을 한 번 수행하며 별도 사용자·부모 승인파일이나 추가 순차 commit을 요구하지 않는다. 단발 CLI가 정확한 구현 commit SHA, protocol hash, dependency/fixture spec/roster hash를 시작 영수증과 최종/부분 보고서에 자동 기록하고 실제 바이트와 대조한다. 현재 설계 역할은 구현·실행·Git을 하지 않는다.

## 결과의 사용과 노출

Profile 성공은 측정·증거 보존의 성공일 뿐이다. 가장 비싼 구간과 절대 ms/횟수/bytes를 보고 다음 하나의 최소 최적화를 별도 등록하거나, 최적화 근거가 부족함을 보고한다. 개선 비율만으로 모델 준비 완료를 선언하지 않는다. 이후 새로운 실행 경로가 동결·CI를 통과하더라도 fresh source-first cal6/6→격리val8/8, 일반 문서·복수 회의·KO/EN·완전성·정확 근거·적절한 보류 범위를 유지한다. 90초/928 total/요청사고512/최종JSON재토큰384/입력5120/context6144는 바뀌지 않으며 독립 native hardcap이 아닌 수치는 그대로 구분한다. 닫힌 pool의 미실행 문항을 이어 실행하거나 이름을 바꿔 재사용하지 않는다.

설계 역할 `/root/free_qa_candidate_review`는 이전 후보 설계·코드 검토와 공개 C2 case-summary/집계, 이번 C4 timing-only metadata에 노출됐다. 현재·과거 격리 body/oracle/answer/reasoning을 읽었다는 뜻은 아니다. 이 역할은 향후 독립 품질 판정에서 계속 제외된다. 이번 작성 단계의 source/item authorship, profile, tokenizer/native/quality 호출과 사용자 검수는 모두0이다.
