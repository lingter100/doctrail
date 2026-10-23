# C2 literal-text 자료 처리 후속 버전

2026-10-14. 질문·합성 평가 원문 작성 전 형식 호환성 보완이다. 비교 정책 source41은 바꾸지 않는다.

격리 source 감사에서 검증용으로 먼저 등록한 공개4파일 중3개가 RST임을 확인했다. 기존 v1 helper는 Markdown·txt suffix만 허용했다. 원래 `.rst` 출처를 `.txt`라고 잘못 기록하거나 문서를 제외하지 않고, **명시적 `ingestion_kind="txt"`**를 요구하는 새 `prepare_meeting_plaintext_source_inventory.py`를 추가했다. RST include·참조·markup을 실행하거나 렌더링하지 않으며, 기존 서비스의 txt 추출·정규화·분할 함수에 원본 바이트를 전달한다.

새 경로는 v1의 경로/hash/출처 검사와 record 생성을 재사용한다. suffix 기반의 기존 추출 타입 선택에만 메모리 안의 사본을 사용하고 결과에는 원래 source path·immutable URL·raw snapshot·원본 hash·원래 manifest hash를 보존한다. 원문 파일이나 manifest를 쓰지 않는다. 결과에 `source_processing_version=2`, 실제 `ingestion_kind`와 `source_path`를 추가한다. 합성 자료의 명시적 제외/전체 모드 조건도 유지한다.

## 검증과 보존

새 합성13검사와 기존45검사, 총 **58passed/1Windows-link-skip** 및 Ruff를 확인했다. 별도 Astra high 코드 검토에서 material defect는 발견하지 못했다. 이는 코드 검토이며 검증 split의 원문이나 모델 출력 검토가 아니다.

새 경로로 공개 calibration2개를 처리하고 실제 Java 대조를 다시 수행했다. **49/49 청크 일치, 해당 Java2검사 통과**다. [Python 영수증](../experiments/results/meetings-c2-source-inventory-calibration-v2.json)·[Java 영수증](../experiments/results/meetings-c2-source-parity-calibration-v2.json)은 원본 바이트로 보존한다. 앞선 v1의 Java127/전체 Python1525 통과를 새 버전 전체 검사의 수치로 바꿔 쓰지 않는다. 모델 재실행은 없었다.

처음 새 진입점을 파일 경로로 실행했을 때 `scripts` 패키지를 찾지 못했고, 부모가 이 실패를 확인하기 전에 Java 대조를 호출해 입력 부재 오류도 발생했다. 평가 자료·모델 실행 실패는 아니며 아래 모듈 실행 명령으로 준비 성공을 확인한 다음 Java를 실행해 대조를 통과했다.

`c0751cd`의 원격 push38495821005/PR38495825777은 backend의 테스트1개에서 실패했다(1,505passed/21skipped). 외부 절대경로 거부 fixture가 `C:/outside.md`를 고정해 Linux에서 저장소 내부 상대경로로 해석된 탓이다. Java/web은 통과했다. 플랫폼의 실제 외부 절대경로를 생성하도록 **테스트1줄만** 고쳤다. v1 helper 구현·원문·모델 정책은 그대로다. v1 freeze/영수증/실패는 `c0751cd`로 재현할 수 있고 현재 후속 source-processing-v2에 테스트 변경과 새 진입점을 등록한다.

검증 source4개는 격리 역할이 Apache-2.0 파일 고지와 LICENSE/NOTICE·원본 hash를 확인했으며 부모는 metadata/schema/hash만 확인했다. 이 문서 작성 시 검증 본문 청크 대조는 아직 미실행이다. 새 freeze commit 이후 격리 역할이 실제 처리를 담당한다. 질문·oracle·선택 context·tokenizer·모델 호출·사용자 검수0, 서비스 채택0이다.

## 실행 방법

저장소 루트에서 **모듈 방식**으로 실행한다. 지정하는 출력 경로는 새 경로여야 한다. 검증 phase는 격리 역할만 수행한다.

```powershell
uv run --locked --no-sync python -m scripts.prepare_meeting_plaintext_source_inventory --manifest data/evaluation/meetings-c2-calibration-v1/source-manifest.json --output .local/c2-source-reproduction-v2 --phase calibration --mode adopted-public
```

Java 대조는 [기존 실행 방법](MEETINGS-C2-SOURCE-PROCESSING.md)의 inventory/receipt 경로만 새 출력으로 바꾼다. 동결 자료는 `git checkout c0751cd` 등 해당 source 커밋의 별도 checkout에서 재현하며 현재 작업 폴더를 소급 덮어쓰지 않는다.
