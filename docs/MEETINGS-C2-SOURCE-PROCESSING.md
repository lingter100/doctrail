# C2 자료 처리 구현과 Java 동등성

2026-10-14. 질문 작성 전 실제 자료 처리 확인이며 모델 품질 실험이 아니다.

## 구현과 실제 결과

새 `scripts/prepare_meeting_source_inventory.py`는 기존 Python `extract`·`chunk_content`를 호출한다. Java/Python 서비스 코드는 변경하지 않았다. 원본·출처 manifest·기존 처리 코드의 hash를 확인하고 전체 문서와 전체 청크를 새 `.local` 경로에 저장한다. 각 파일은 한 번 읽은 바이트로 hash와 처리를 수행하며 출력 덮어쓰기·잘못된 경로·link/junction·중복 문서·원본 변경을 거부한다. 질문/context 선택이나 모델 호출은 수행하지 않는다.

`adopted-public`은 아직 본문이 없는 합성3건을 명시적으로 제외하고 공개2건만 처리한다. `adopted-all`은 모든 source의 준비 완료를 요구하며 누락된 본문·hash·합성 출처 표시를 거부한다. 후속 합성 원문에는 AI 작성·가상 조직 표시와 작성 역할을 보존한다. 최초 채택 manifest를 덮어쓰지 않고 완성 source manifest를 별도로 등록한다.

실제 고정 공개2문서의 41,069 codepoints에서 **49청크(18+31)**를 만들었다. 별도 Java 테스트가 원본을 직접 읽어 Java `Ingest.extract`·`Retrieval.chunkContent`를 실행하고 전체 내용, page, 청크 내용·시작/끝 위치·순서·ID·UTF-8 hash를 전수 대조했다. **49/49 일치**, Java21 전체 **127검사 통과·실패0·skip0**다. Unicode 조합 문자·이모지 경계도 별도 고정 예로 확인했다.

새 Python helper의 합성 검사45passed/1Windows-symlink-skip와 Ruff가 통과했다. 링크 생성 권한으로 생략한 검사를 로컬 성공으로 세지 않는다. Java의 기본 CI는 공개 원문을 내려받지 않으므로 실제 corpus 검사는 명시 경로가 없으면 건너뛴다. 위 실제 로컬 결과는 경로를 제공하고 실행한 기록이다.

- [Python 원본 영수증](../experiments/results/meetings-c2-source-inventory-calibration-v1.json)
- [Java 원본 영수증](../experiments/results/meetings-c2-source-parity-calibration-v1.json)

공개 사본은 로컬 영수증의 바이트 그대로다. 전체 원문 inventory와 캐시는 `.local/c2-source-inventory-calibration-public-v1/` 및 `.local/c2-source-adoption/calibration/`에 보관하며 Git에 넣지 않는다. source hash와 inventory hash로 연결된다. 영수증은 각 언어에서 독립 실행한 결과이며 Python 실행을 Java 성능으로 표시하지 않는다. 의미 정답률·답변 지연 측정0, 새 질문·선택 context·tokenizer·모델 호출·사용자 검수0이다.

## 재현

저장소 루트의 PowerShell에서 실행한다. 원본 캐시가 없으면 최초 채택 manifest의 고정 URL에서 동일 바이트를 받는다. 다음은 무료 공개 원문 수집이며 helper에서 원본 SHA와 Git blob을 다시 확인한다. 이미 받은 원본을 덮어쓰지 않는다.

```powershell
$sourceManifest = Get-Content data/evaluation/meetings-c2-calibration-v1/source-manifest.json -Raw -Encoding utf8 | ConvertFrom-Json
foreach ($source in $sourceManifest.families[0].sources) {
    if (-not (Test-Path -LiteralPath $source.local_raw_snapshot)) {
        New-Item -ItemType Directory -Force -Path (Split-Path $source.local_raw_snapshot) | Out-Null
        Invoke-WebRequest -Uri $source.raw_url -OutFile $source.local_raw_snapshot
    }
}
uv run --locked --no-sync python scripts/prepare_meeting_source_inventory.py --manifest data/evaluation/meetings-c2-calibration-v1/source-manifest.json --output .local/c2-source-inventory-reproduction --phase calibration --mode adopted-public
```

검사 환경의 Java21 `JAVA_HOME`을 설정한 뒤 저장소 루트에서 실행한다. 출력 경로는 존재하지 않아야 한다. 기본 비교 실험이나 과거 모델 호출은 실행하지 않는다.

```powershell
$sourceRoot = (Get-Location).Path
$sourceInventory = Join-Path $sourceRoot '.local/c2-source-inventory-reproduction/inventory.json'
$sourceReceipt = Join-Path $sourceRoot '.local/c2-source-inventory-reproduction/java-parity.json'
Push-Location server
.\mvnw.cmd -q -Dtest=MeetingSourceParityTest "-Ddoctrail.sourceRoot=$sourceRoot" "-Ddoctrail.sourceInventory=$sourceInventory" "-Ddoctrail.sourceParityReceipt=$sourceReceipt" test
Pop-Location
```

이번 실제 전체 Java 검사에는 위 `-Dtest` 필터를 빼고 모든127개를 실행했다. 원문이 없는 환경의 일반 단위 검사는 `uv run --locked --no-sync pytest -q tests/test_prepare_meeting_source_inventory.py`로 수행한다.

## 동결 이후

새 helper·합성 검사·Java 대조 검사·처리 규칙·최초 manifest·영수증을 별도 source-processing freeze로 고정한다. 비교 정책 source41/v2와 과거 결과는 보존한다. 그다음 신규 합성 원문 작성·내용 일관성 확인·source inventory 고정, calibration 질문/oracle 작성·독립 사전 검토, 두 정책 tokenizer 준비, 실행 계획 봉인 순서로 진행한다. 검증 split 본문은 격리 역할만 읽고 부모에게 집계와 hash만 전달한다. Phase1/PR14는 미완료/draft다.
