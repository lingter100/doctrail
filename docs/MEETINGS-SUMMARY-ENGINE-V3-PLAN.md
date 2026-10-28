# ENGINEv3 구현 계약: 고정 x64 선택 취득과 명시적 50ms 자원 표본
2026-10-28 · 설계만 완료. 새 취득/추출/프로파일/테스트/빌드/엔진/모델/Java/Git 실행은 0이다.

## 근거와 변경 이유
- v2는 extract-llvm 중 외부 external_scan_deadline, CLI15/wrapper1, 595.015초, 추출4,406파일로 실패·소비됐다. 원본 root/ZIP/로그/실패 상태는 재사용하거나 수정하지 않는다.
- 별도 단1회 측정4×256: worker resource/log3.328초, safe_path/stat0.188초, self OwnedTree.sample3.484초, external stat0.016초; 총7.203초다. 과거 실패의 인과 비율·예상 속도·600초 성공확률로 확대하지 않는다.
- 현 Budget.check와 run_owned의 disk_bytes 콜백은 각 항목 전후 자원/트리 조회를 반복한다. 아래 정책은 그 빈도를 명시적으로 변경한다. 기존 검사와 동일한 감지 지연이라고 주장하지 않는다.

## 다음 구현의 정확 범위
- scripts/prepare_summary_grammar_engine.py: Budget/취득 CLI·worker 결속/선택 추출·manifest/check_acquired만; tests/test_summary_grammar_engine.py: 기존 검사를 보존하고 합성 회귀를 추가한다.
- tools/summary_grammar/runtime.py는 run_owned의 서명·본문 안에서만 수정한다. OwnedTree 전체, safe_path, disk_bytes, write_bounded와 prepare.build 본문은 원시 소스/AST 대조로 불변을 확인한다.
- pins.json/고정 URL·SHA·엔진 commit/grammar·입력·판정기/QA 코드/외부 observer/기존 결과·문서는 구현 범위 밖이다. 실제 파일명은 prepare_summary_grammar_engine.py다.
- 기본 호출·CLI 옵션 생략은 기존 동작을 유지한다. build/validator의 sampling 및 실행 allowlist는 바꾸지 않는다.

## 명시적 선택과 결속
- acquire에만 --acquisition-profile llvm-x64-sampled-50ms-v1을 추가한다. 알 수 없는 값, inspect/build에서의 지정, worker의 attempt/token/profile 불일치는 시작 전 거부한다.
- acquire_supervised가 새 attempt에 profile을 기록하고 worker argv에 전달한다. 이 경로만 Budget과 run_owned에 고정 profile을 명시 전달한다; 사용자 지정 간격/환경변수 자동활성화는 없다.
- raw/final acquisition에는 profile과 LLVM 선택 policy/선택목록 SHA를, supervision에는 profile·50ms와 supervisor sample 횟수/강제 사유/최대 관측 간격을 결속한다. worker 통계는 phase별 관측 시점을 표시하고 terminal 이전 값을 최종 합계로 부르지 않는다. 기존 manifest는 legacy 경로로 유지한다.
- v3 check_acquired는 attempt/raw/final/supervision의 profile 일치·선택 inventory·archive SHA를 재검증한다. profile 삭제/혼합/변조, 실패 latch나 정리·최종화 실패는 수용하지 않는다.

## 검사 시점과 실패 보존
- worker의 모든 기존 checkpoint에서 전송 누계·절대 deadline·직접 로그 크기/증가·디스크 ledger를 먼저 검사한다. safe_path, write 전 예약, short write 미환급, 청크 크기/CRC·길이·phase full scan은 그대로 유지한다.
- 비용 큰 worker Process/children/RSS/host 조회와 supervisor OwnedTree.sample만 last_sample_start에서 0.050초 이상 지났을 때 수행한다. 성공한 호출의 시작 시각으로 갱신하며 초과 지연을 반복 표본으로 따라잡지 않는다.
- 매 checkpoint에서 deadline을 확인하고, 표본/로그 등 OS 호출 뒤 deadline을 다시 확인한다. 로그·바이트·시간 위반은 표본 시점까지 미루지 않는다. 표본 중 관측 오류/신원/allowlist/자원 실패는 즉시 실패다.
- worker는 시작, 각 phase 시작·완료, 성공 terminal에 강제 표본을 수행한다. supervisor는 시작 전 host gate와 startup scan 완료, child capture 직후, 각 full scan 시작·완료, process terminal 직후·cleanup 전에 강제 표본을 수행한다.
- supervisor는 worker phase를 해석하지 않는다. startup traversal의 host 재조회도 같은 opt-in 간격만 적용하되 시작/완료와 spawn 직전은 강제하고, startup deadline은 모든 기존 경계에서 유지한다.
- Budget과 run_owned 각각 최초 실패 객체/사유를 sticky latch로 보존한다. 후속 정상 관측·재호출·terminal metadata가 이를 지우거나 성공 manifest로 바꾸지 못한다.
- 실패 terminal 표본은 남은 기존 운용 시간 안에서만 시도하고, 시간 소진/기존 실패로 생략되면 미관측을 기록한다. 최초 원인을 유지하며 5초 정리 예약을 침범하는 새 예산·재시도는 만들지 않는다.
- failure metadata는 기존 bounded best-effort 경로로 기록하되 latch를 초기화하지 않는다. terminal 표본/기록 실패는 부가 오류로 남기고 OwnedTree.cleanup·identity-safe kill·최종 부재 검증은 그대로 수행한다.
- 50ms는 checkpoint에서의 표본 예정 간격이며 hard timer·20Hz·최대 감지 지연·RSS peak 보장이 아니다. OS 호출/스케줄링으로 늦어지고 짧은 자식·자원 초과는 표본 사이에서 놓칠 수 있다.

## 고정 LLVM 선택 규칙
- 같은 LLVM ZIP 전체를 새 root에 취득하고 SHA256 82babcd6aae4dc3606e8e0471d816989c384b4bf86a139f184a8b4a1b2c2758d를 먼저 검증한다. 다운로드 바이트 절감은 주장하지 않는다.
- 중앙목록의 단일 prefix llvm-mingw-20250709-ucrt-x86_64/ 아래 bin/, include/, lib/, share/, x86_64-w64-mingw32/ 전체와 LICENSE.TXT를 유지한다. 모든 driver/wrapper/DLL 및 lib/clang/20/ resources를 포함한다.
- 알려진 제외 subtree는 aarch64-w64-mingw32/, armv7-w64-mingw32/, i686-w64-mingw32/, python/뿐이다. 모든 license/copying/copyright 이름의 파일은 위치와 무관하게 보존하고 필요한 부모 디렉터리도 남긴다.
- 알 수 없는 root/top-level/의존성 필수 항목 누락은 거부한다. bin의 clang.exe·clang++.exe·단일 clang-20.exe, resource include, x64 include/lib, 공용 include/lib/share와 라이선스가 비어 있거나 없어도 거부한다.
- 제외 항목도 추출 전에 전체 중앙목록에서 safe_path·casefold 중복·타입/암호화·개수/선언크기를 검증한다. 기존 전체 선언 확장량 cap도 유지하고, 실제 ledger에는 선택해 쓰는 바이트만 한 번 계상한다.
- 선택 전부를 경로순 정렬한 [path,size,CRC,external_attr] 배열(ASCII escaped compact JSON, UTF8/no newline)의 SHA256으로 결속하고 선택/제외 개수·바이트를 기록한다. 선택하지 않은 body는 열지 않으며 선택 body의 CRC/정확 길이·총 디스크 검사는 유지한다.
- 기존 후보5,925파일/467,711,156B는 저장 중앙목록의 참고값이다. 추가 라이선스 보존이 있으면 실제 수치를 기록한다; 숫자만 맞추기 위해 의존성을 삭제하지 않는다.
- CMake/Ninja/고정 엔진 source의 취득·추출 규칙은 유지한다. 기존 runtime_bindings의 wrapper/driver/resource 및 CMake Windows-GNU.cmake line55 결속을 통과해야 한다.
- 이 규칙은 보수적 파일 보존이다. DLL/도구체인 의존성의 실제 완결성은 미검증이며 이후 파일·실행목록 검토 또는 configure/build에서 누락이 확인되면 거부하고 별도 수정한다.

## 구현 수용 검사: 합성/모형만
- 기존 전체 engine 테스트와 Ruff를 실행하고 첫 실패·수정 전 소스·출력을 보존한다. 이 설계 배정에서는 실행하지 않는다.
- fake clock/ps로 기본 per-entry 동작 보존, v3 <50ms 미표본/정확50ms 표본/장시간 OS 호출 후 deadline 실패, start/phase/scan/terminal 강제표본을 검증한다.
- 표본 사이 deadline/log/download/disk 위반의 즉시 실패, 다음 예정/강제 표본의 RSS/host/신원/allowlist/관측 오류, 한번 실패 뒤 상태 회복에도 latch 재거부를 각각 검증한다.
- 실패 terminal 표본·receipt 오류가 최초 원인을 보존하고, cleanup 예약·PID 재사용 미살해·관측 신원 부재·늦은 manifest/rollback 실패 거부를 유지하는지 검증한다.
- 작은 합성 ZIP으로 선택/제외·라이선스 예외·필수 driver/resource/x64 누락·unknown root·제외 subtree 내 unsafe/중복/symlink/암호화/oversize를 검사한다. 제외 body open=0도 검증한다.
- 원래 CRC/길이/short-write/정확 disk boundary/ledger 불일치/redirect body 미읽기·hash mismatch·fresh root only 검사를 유지하고, v3 profile과 manifest 선택목록 결속 변조를 추가한다.
- 해당3파일 외 변경0, OwnedTree/safe_path/disk_bytes/write_bounded/build 본문 불변, build/validator 호출에 v3 옵션 없음, legacy 검사 기대값 완화 없음이 별도 검토 기준이다.

## 다음 단계와 고정 한계
- 부모 수용 → 위3파일 구현+합성 회귀 → 독립 검토 → 부모 문서/Git 및 정확 head CI → 새 root의 취득1회를 별도 배정한다. 기존 실패 root·프로파일은 재사용/재측정하지 않는다.
- 취득600초(정리5초 포함), 전송512MiB, 디스크4GiB, RSS2GiB, host2GiB/start4GiB를 유지한다. 외부 WORK+OUT 예산·once gate·custody도 별도 실행의 필수 조건이다.
- 실제 CLI exit0·정확 최종 stdout/manifest SHA·운용한도·소유 부재를 확인한 뒤에만 파일/실행목록 검토로 넘긴다. build900초/2jobs 및 고정105 native+carrier1/접두사10 검증은 후속 별도 범위다.
- 이 계획은 실제 취득 성공·컴파일러 호환성·엔진 적합성·모델/요약 의미 품질·사용자 검수를 증명하지 않는다. 개인 평가자료·raw 모델 출력은 읽지 않았다.
