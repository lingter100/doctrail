# 요약 모드 진단의 CLI 진입점 복구와 새 1회 실행 경계

2026-10-23. 부모 검토·수용·커밋을 위한 **전향적 운영 보완안**이다. 사용자 승인이나 새 실제 실행을 선언하지 않는다. 아래 조건을 충족하고 부모가 별도 once를 배정할 때에만 외부 실행 시도 v2를 최대 1회 허용하는 근거로 사용한다.

1. **v1은 실패·소비된 기록으로 보존한다.** [공개 실패 기록](../experiments/results/meetings-summary-mode-development-v1.json)(3,405B/SHA-256 `645c6825b3cbb4ce18a4e9cd90e9ed5a6c67056b2a0c7d518cde48995465f2d5`)과 custody receipt `932f6030baf4cdfb16f125914bf48c9fe88700f7874b683672aae99a0baf5820`에 따르면 직접 파일 호출은 `ModuleNotFoundError: scripts`로 main·등록 검증 전에 끝났다. CLI 1회/exit1, stdout0, run 경로 미생성, native·tokenizer·completion0이다. Wrapper exit0을 진단 성공으로 바꾸지 않으며 v1 등록·CLI·실패·once 권한을 재사용하거나 덮어쓰지 않는다.

2. **변경은 외부 Python 호출 방식 하나다.** 저장소 루트를 cwd로 고정하고 `.venv\Scripts\python.exe -B -X utf8 -m scripts.probe_meeting_summary_mode`로 시작한다. 직접 파일 경로 호출을 대체하며 probe·runtime·native argv·import 코드를 수정하지 않는다. `--registration`에는 아래 v2 등록 경로, `--execute-once-sha256`에는 부모가 동결한 그 파일의 정확한 SHA-256을 전달한다. 환경/PYTHONPATH 우회나 다른 실행 경로를 자동으로 시도하지 않는다.

3. **새 경로와 기존 엄격한 schema를 사용한다.** 등록은 `.local/meeting-summary-mode-execution-v2/registration-v2.json`, CLI 증거는 같은 폴더의 `cli-v2`, 출력은 `.local/meeting-summary-mode-execution-v2/summary-mode-development-v1`이다. v2는 외부 시도 식별자이며 probe diagnostic ID와 출력 basename `summary-mode-development-v1`은 유지한다. 등록 내용은 v1 대비 `output_dir`만 새 경로로 바꾸고 나머지 필드·값은 동일하게 결속한다. 등록·CLI·출력은 새 경로여야 하며 이전 시도 경로를 복구 대상으로 쓰지 않는다.

4. **원계약과 자료·평가 조건을 유지한다.** [원계획](MEETINGS-SUMMARY-QUALITY-NEXT.md)(18,650B/`fb32d66f4c2264edec160b908b83fa1050731c455099636b985793db40d0b329`), [소유 실행 보완](MEETINGS-SUMMARY-MODE-LAUNCHER-REPAIR.md)(11,215B/`7bbd6e2c35c4cea5970a2150bdbbdb74296085eb11a40ca4426aba93fb340a5b`), [이력 경계](MEETINGS-SUMMARY-MODE-PROVENANCE-BOUNDARY.md)(7,014B/`ab191c4aa424d2ca16a874683feb3c88eb6064a89bcb47e9bae0e2fdfa9a11ac`)는 byte-identical이다. Canonical 입력 `7a6c24181281f012dc534712b4e2e0379d6610b4408779fb0f6e4b3bab323639`, source receipt `7dca002538be68f0bf0d2d2d26611a58bdd7059f1c04d88320c4df7ad0c8eb06`, source-only lock `fa149e9f0ce55c9a33f22947b2166bf5a3ada832612ad8fa7fcccee5d36dbc66`과 기존 admission·criteria를 유지한다. 원문·문서 순서·A/B 순서·prompt·가중치·검토·품질 문턱·역할·격리 평가 gate는 변경하지 않는다.

5. **이 문서는 외부 custody companion에 결속한다.** 부모의 공개·실행 custody 기록이 이 보완안의 정확한 path/bytes/SHA-256, v1 실패·custody, v2 등록/hash·전체 CLI argv/cwd, 실행자·명시적 once 배정, 회귀 검사·독립 검토·정확한 CI를 함께 참조한다. Strict registration에 새 필드를 끼워 넣거나 기존 plan/source receipt/source lock을 이 문서로 대체하지 않는다. 기존 code141·cached asset61은 같은 hash를 유지하고 새 CLI subprocess 회귀 검사 파일은 외부 companion에서 별도로 결속한다.

6. **시작 전 검증은 모델 없이 먼저 끝낸다.** 부모가 별도 배정한 runbook 수정과 subprocess 회귀에서 동일 cwd/interpreter/module 진입의 `--help` 성공 및 필수 인자 누락의 argparse 실패를 확인한다. 이 검사는 등록 검증·원문 파싱·출력 생성·native 실행에 진입하지 않아야 하며 실제 inference 가능성이나 품질 증명으로 세지 않는다. 수정·검사 파일의 정확한 source CI 필수 job 통과와 독립 generic 검토 뒤에만 최종 v2 binding을 검토·게시한다. 실제 실행에는 그 이후 별도 once 배정이 필요하다.

7. **모든 기존 예산과 live 시작 조건이 그대로 적용된다.** soft reasoning512/total1312/final 재계수768/input4096/review128, 생성150초·arm180초·startup120초·active1500초·cleanup5초·whole1625초와 최대16completion을 늘리지 않는다. 실행 직전 가용 RAM10GiB 이상, 기존 GPU/worker/llama lease·소유권·충돌 확인, 새 run/CLI 경로 부재와 exact binding을 다시 확인한다. 저장된 자원 snapshot·prepared 등록·이전 lease 확인은 예약이나 시작 승인이 아니다. 조건 미충족이면 시작을 보류하며 임계값을 낮추거나 다른 프로세스를 종료하지 않는다.

8. **새 실행도 실제 exit와 terminal 증거로 판정한다.** 기존 소유 정리·posthash·마지막 저장 뒤 시간 검사와 외부 CLI 시작/종료·exit 관측을 유지한다. Bound terminal의 등록 hash·최초 실패·운영 판정·동일 최종 시간 관측을 외부 custody와 대조한다. Terminal 누락·모순 또는 실제 CLI 비정상 종료를 wrapper 성공으로 덮지 않는다. Semantic final-review 거부의 진단 전용 진행 규칙은 원계약 그대로이며 운영 실패 뒤 추가 completion은0이다.

9. **모델 실험 재튜닝이 아닌 기계적 진입점 복구다.** 수용된 v1 custody상 모델 입력 처리·추론·모델 출력·품질 관측이 없으므로, 그 결과로 자료·기준·prompt·모델·순서·예산을 선택하거나 개선하는 과정이 없다. 기존 source-only lock과 눈가림 평가 순서를 보존할 근거는 이 native0 증거이지 실패 기록 삭제가 아니다. v2 CLI를 실제 발행하면 그 once도 소비된다. v2의 어떤 실패도 보존하고 자동 재개·재시도·대체 호출을 하지 않는다. **이 보완안은 세 번째 시도를 허용하지 않는다.**

이번 작성은 이 새 문서 한 개뿐이며 코드·검사·모델/native/tokenizer·Java/browser·Git 실행은0이다. 실제 원문·private criteria·모델 출력은 읽지 않았다. Phase1 미완료, 유료 호출·공개 서비스 배포0과 기존 노출 고지를 유지한다.
