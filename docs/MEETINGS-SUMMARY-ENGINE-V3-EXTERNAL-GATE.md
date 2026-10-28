# ENGINEv3 B1 최소 수정 계약 — 외부 검토 SHA 재사용
2026-10-28 · 설계만. 코드/테스트/다운로드/취득/observer/companion 생성/실제 실행 0; 자동 사용자 승인 아님.

## 결정과 신뢰 경계
1. B1은 late publication + rollback 실패 + failure-marker 생성 실패 뒤 orphan manifest를 수용하는 문제다; 내부 success marker 하나 추가로 해결하지 않는다.
2. 기존 `check_acquired(root, reviewed_sha)`와 `build --reviewed-acquisition-sha256`를 유지한다. legacy SHA의 뜻은 기존 acquisition.json 그대로다.
3. v3의 같은 SHA는 아래 외부 `acceptance.json`의 정확한 바이트 SHA256로 정의한다. 실제 acquisition.json SHA는 그 안의 manifest ref로 결속한다.
4. 신뢰점은 기존과 같이 외부 검토자가 공급한 expected digest다. 부모가 별도 배정된 observer의 소유·실제 CLI 종료·정확 stdout/manifest·시간·custody를 확인한 뒤만 공급한다; 코드가 계산하여 승인값으로 대입하거나 환경변수/폴더 검색/registry에서 자동 수집하지 않는다.
5. 서명이나 새 trusted registry는 만들지 않는다. SHA/JSON만으로 진짜 관측자를 증명할 수 없으며, 임의 self-asserted JSON의 해시를 공급하는 행위는 이 계약의 외부 검토가 아니다. 이 trust boundary를 API/CLI 설명과 결과 문서에 명시한다.
6. observer는 acquisition CLI 밖에서 직접 발급한 Popen/세션 및 PID·생성시각·실행파일 신원을 관측한다. CLI/worker가 자기 성공을 선언한 기록이나 PID 숫자만으로 외부 관측을 대신하지 않는다.

## 위치와 읽기 규칙
7. 새 성공 WORK root의 고정 sibling `<root.name>.external-review/`만 companion 위치로 사용한다. 기존 실패 root/원본 취득 파일은 수정·복사·재시도하지 않는다; 이 폴더와 바이트는 후속 실제 배정의 OUT 예산에 포함한다.
8. 그 폴더의 허용 파일은 acceptance.json, observer-terminal.json, custody.json, cli.stdout, cli.stderr 5개뿐이다. 실제 생성은 코드 수용·정확 CI 뒤 별도 배정이며 지금은 폴더/catalog/실제 gate를 만들지 않는다.
9. companion이 있으면 supplied SHA가 정확히 일치해야 v3 검사를 진행하며 불일치 시 legacy fallback 금지. 없으면 기존 manifest 검토 후 v3 흔적(profile/selection/schema2/worker-terminal/worker_sampling/argv)이 하나라도 있으면 external acceptance missing으로 거부한다.
10. 모든 ref는 정확히 `{file,size_bytes,sha256}`; file은 해당 역할의 고정 basename만 허용한다. manifest/attempt는 WORK의 acquisition.json/acquisition-attempt.json, 외부 ref는 위 sibling의 고정 파일에만 해석한다; sources의 고정 repo 상대경로 예외는 15a번뿐이다.
11. safe_path/reparse 검사를 두 root 및 모든 ref에 적용한다; 절대/부모/역슬래시/alias/casefold 중복·같은 파일의 역할 겸용·다른 sibling/root를 거부한다. sibling에 다른 파일/하위 디렉터리가 있어도 거부한다.
12. 읽기 전 stat과 읽은 실제 길이 모두 제한·ref 길이와 일치시킨다. acceptance<=64KiB, observer-terminal<=128KiB, custody<=256KiB, stdout<=4KiB, stderr<=8MiB, attempt<=16KiB, manifest<=16MiB; 해시는 <=64KiB 청크로 읽고 초과/변경/관측오류를 실패로 남긴다.
13. 새 외부 JSON은 UTF-8, duplicate key/NaN/Infinity 금지; 그 모든 객체는 아래 정확한 key 집합으로 검증하고 누락/extra/타입 혼용(bool-as-int 포함)을 거부한다. ref SHA는 lowercase hex64, size는 비음수 정수다.

## 외부 companion 형식 — 모두 제안 스키마, 실제 값 없음
14. acceptance 정확한 keys: `{schema,profile,workspace,attempt,manifest,stdout,stderr,observer_terminal,custody,sources}`; schema=`engine-v3-external-acceptance-v1`, profile=`llvm-x64-sampled-50ms-v1`, workspace=정규화된 현재 WORK 절대경로다.
15. attempt/manifest/stdout/stderr/observer_terminal/custody는 10번 ref이다. acceptance 자체만 supplied expected SHA로 검토하고 모든 ref를 재해시한다; manifest 자체 SHA를 v3 reviewed_sha로 공급하면 거부한다.
15a. sources는 정확히 scripts/prepare_summary_grammar_engine.py, tools/summary_grammar/runtime.py, tools/summary_grammar/pins.json의 순서 고정 ref3이다; 실행 script의 repo를 기준으로 safe_path·재해시하며 상한은 각256/128/32KiB다. 현재 bytes와 실제 사전·사후 source 결속이 모두 같아야 한다.
16. observer-terminal 정확한 keys: `{schema,evidence_kind,profile,workspace,attempt_sha256,manifest_sha256,stdout_sha256,stderr_sha256,argv,observer,cli,sources_before,sources_after,exit_code,terminal_observed,elapsed_seconds,budget_seconds,cleanup_reserved_seconds,limits_pass,first_failure}`.
17. observer schema=`engine-v3-external-terminal-v1`, evidence_kind=`external_actual_cli_observation`; profile/workspace와 네 SHA 및 sources_before/sources_after는 acceptance의 해당 값과 같아야 한다. synthetic/self_reported/pending/unknown 표지는 거부한다.
18. observer는 정확히 `{pid,create_time,executable,source_sha256}`, cli는 `{pid,create_time,executable}`다. pid 양의 정수, create_time 유한 양수, executable 정규화 절대경로, source_sha256 hex64; 둘의 신원은 달라야 한다.
19. observer source_sha256와 신원은 실제 배정 전 부모가 결속한 observer 및 직접 발급 세션과 외부 검토에서 일치 확인한다. 검사기가 source_sha256 문자열만으로 observer의 진실성/소유권을 인증한다고 주장하지 않는다.
20. argv는 attempt의 python/-B/script를 재사용한 `[python,-B,script,acquire,--workspace,WORK,--acquisition-profile,PROFILE]`와 정확히 일치하고 cli.executable은 그 python의 정규 경로여야 한다; 다른 token/worker-only 실행을 outer CLI 성공으로 인정하지 않는다.
21. exit_code=정수0, terminal_observed=true, elapsed_seconds=유한한 0 이상 600 이하, budget_seconds=600, cleanup_reserved_seconds=5, limits_pass=true, first_failure=null만 수용한다. elapsed는 외부 실제 CLI 시작부터 terminal까지 같은 monotonic 관측의 차다.
22. stdout 원본 바이트는 `{"status": "ACQUIRED_UNREVIEWED_DO_NOT_EXECUTE"}` 뒤 LF 또는 CRLF 하나만 허용하며 전체 SHA/길이를 결속한다. 추가 줄/접두사/중복 JSON/파싱 후 재직렬화/종료 전 캡처를 거부한다; stderr도 원본 전체 해시/길이를 보존한다.
23. custody 정확한 keys: `{schema,profile,workspace,attempt_sha256,manifest_sha256,observer_terminal_sha256,identities,all_absent,errors}`; schema=`engine-v3-external-custody-v1`, 나머지 결속값은 위 ref와 일치해야 한다.
24. identities는 1..128개의 중복 없는 `{pid,create_time,executable,absent}` 배열이며 신원 타입은 cli와 같고 absent=true만 수용한다. outer CLI와 내부 supervision.cleanup.identities를 모두 포함하며 observer 자신의 신원은 제외한다.
25. all_absent=true, errors=[]만 수용한다. external 관측의 unknown/재사용 불명/잔존/cleanup 실패를 성공으로 바꾸지 않으며 원래 내부 cleanup·first-failure·latch 검사도 그대로 수행한다.

## 구현 접점과 호환성
26. 변경 허용은 prepare_summary_grammar_engine.py의 check_acquired 및 인접 순수 검증 helper/CLI help, tests/test_summary_grammar_engine.py의 추가 합성 검사뿐이다. runtime 전체/run_owned/OwnedTree/safe_path/disk_bytes/write_bounded 및 prepare.build 본문·서명은 원시/AST 불변이다.
27. v3에서 companion을 검증한 뒤 manifest ref의 SHA로 기존 acquisition.json을 reviewed하고 현재 profile/raw/selection/archive/inventory/runtime_bindings 검사를 모두 수행하여 원래 lock을 반환한다. 반환 lock에 외부 필드를 섞지 않는다.
28. acquire_supervised는 check_acquired를 호출하지 않으므로 companion 없이 정상 actual CLI 종료가 가능하다. producer 경로에 companion 생성/수용/자동 승인 코드를 넣지 않는다.
29. build는 790/817줄에서 check_acquired를 두 번 호출하고 verifier 86줄은 build-manifest의 acquisition_sha256를 그대로 전달한다; 모두 같은 immutable companion/ref를 재검증하며 캐시로 두 번째 검사를 생략하지 않는다.
30. 보호된 build-attempt/build-manifest의 acquisition_sha256 필드는 v3에서 '검토 artifact(companion) SHA'라는 호환 의미가 된다; 실제 acquisition.json 해시라고 오기하지 않는다. legacy 의미는 그대로이며 verifier 소스 변경은 필요 없다. 후속 공개 보고서는 review_artifact_sha256와 actual_acquisition_sha256를 각각 명시한다.
30a. 공개 scripts/tools/tests 전체 검색 결과 소비자는 prepare의 저장·재전달, verify:86의 check_acquired 전달, README 사용 예시와 engine 테스트뿐이다. raw acquisition.json과 acquisition_sha256를 직접 비교하는 다른 공개 소비자는 없으며 README의 의미 설명은 부모 문서 범위다.
31. build가 WORK에 새 파일을 쓰므로 외부 custody는 취득 terminal 시점의 고정 acquire 파일/신원만 뜻한다. build 이후 전체 WORK가 custody 때와 같다고 요구하거나 주장하지 않고 외부 evidence 5파일 및 acquire refs는 계속 불변이어야 한다.
32. 새 제어파일 검사는 12번의 읽기량/개수 제한 안에서 매번 수행한다. 기존 첫 검사는 build 900초 deadline 생성 전이고 두 번째는 compile 뒤이므로 보호 본문을 그대로 두고 전체 명령 wall-time<=900초를 새로 보장한다고 쓰지 않는다.
33. 기존 acquisition600/cleanup5/download512MiB/WORK4GiB/RSS2GiB/host2GiB/start4GiB/build runner공유900초/2jobs/validator60초 및 once/fresh-root 규칙은 완화하지 않는다. 후속 actual build의 외부 시간 gate는 전후 검증 시간도 관측하며 별도 배정 전엔 실행하지 않는다.

## 요구 합성 검사와 보존
34. legacy173/기존58 정의의 원시·AST·기대값은 그대로다. 추가된v3 112 중 성공 fixture/검토 SHA 접점만 새 계약에 맞추고 원본285 결과/소스와 부모확인296 통합 결과/실패·reproducer는 그대로 보존한다; 검토에서 실제 테스트를 재실행하지 않는다.
35. v3 raw-manifest SHA만 제공/companion 없음/잘못된 expected SHA/동일 SHA 자동계산 fallback/marker 전체 삭제·profile 혼합을 거부한다; 독립 외부 검토 SHA로 결속한 유효 모형만 원래 lock을 반환한다.
36. 모든 key 누락/extra/중복 JSON key/상한 초과/size·hash 변조/절대·탈출·reparse·alias·다른 root·외부 파일 추가/JSON 타입·비유한 시간 오류를 거부한다.
37. exit!=0/terminal 미확인/elapsed>600/limits 실패/first_failure/다른 attempt·profile·manifest·observer·CLI 신원·argv/불완전 stdout/cleanup unknown·잔존·errors를 각각 거부한다.
38. B1의 late publish+rollback 실패+failure-marker 실패 orphan을 그대로 생성한 모형은 companion 없이 거부하며, 실제 실패를 담은 외부 모형을 arbitrary SHA로 감싸도 exit/time/failure 조건에서 거부한다. 단순 내부 success marker는 수용 경로가 없다.
39. 잘못된/자체 선언만 있는 외부 JSON에 '검토 SHA를 이미 승인받았다'고 가장하면 순수 검사로 진짜 관측 여부를 증명할 수 없다는 한계를 테스트/문서에 남긴다; 실제 승인·운영 증거로 오인시키는 합성 fixture를 발행하지 않는다.
39a. 기존 선택목록/프로필/terminal 변조 검사는 유효 외부 모형을 갖춰 해당 내부 거부 이유까지 도달하게 한다; companion 없음/해시 불일치의 조기 실패로 기존 결함 검출을 대신하지 않는다.
40. 동일 gate로 build 전후 및 verifier 전달 호환 모형, 두 검사 사이 companion/ref 변경 거부, build 새 파일 허용, 보호 본문/기존 정의 불변, 실제프로세스·네트워크0을 확인한다; 전용 합성 회귀+전체 engine/Ruff는 이후 구현 배정 범위다.

## 후속 순서
41. 부모 설계 수용 → 기존 high의 정확2파일 구현/합성 검사 → 독립 delta review → 부모 문서(특히 SHA 의미)/Git/정확 head CI → 새 실제 root와 외부 observer·OUT/once/custody 사전결속을 별도 배정한다.
42. 실제 CLI 종료·최종 stdout/manifest·운용한도·소유 부재를 부모가 확인한 뒤만 외부 companion을 만들고 그 SHA를 검토값으로 수용한다; build/컴파일러/native/model/개인 자료는 이번 범위에 없고 어떠한 새 실행 승인도 생성하지 않는다.
