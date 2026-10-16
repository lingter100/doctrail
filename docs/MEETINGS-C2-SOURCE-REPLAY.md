# 고정된 공개 원문 snapshot 복구

새 checkout에는 `.local` 원문 캐시가 없다. 기존 source inventory helper와 문항은 바꾸지 않고, 이미 채택한 source manifest에 적힌 원본 파일을 복구하는 별도 도구를 추가했다. 질문이나 source를 새로 선정하는 도구가 아니다. 합성 원문과 공개 LICENSE/NOTICE 사본은 저장소에 있으며 다운로드 대상에서 제외한다.

## 사용 방법

저장소 루트의 잠긴 Python3.11 기본 환경에서 실행한다. `--download`가 없으면 네트워크를 사용하지 않고 기존 파일만 검증하며, 누락된 snapshot이 있으면 실패한다.

```powershell
uv run --locked --no-sync python -m scripts.fetch_meeting_source_snapshots --manifest data/evaluation/meetings-c2-calibration-v1/source-manifest-full.json --output .local/c2-source-replay --phase calibration --download
uv run --locked --no-sync python -m scripts.prepare_meeting_plaintext_source_inventory --manifest data/evaluation/meetings-c2-calibration-v1/source-manifest-full.json --output .local/c2-source-inventory-replay --phase calibration --mode adopted-all
```

출력 폴더는 매번 새 경로를 사용한다. 기존 snapshot은 정확한 크기·SHA256·Git blob SHA1이 일치할 때만 재사용하고, 다르면 덮어쓰지 않는다. 원문 경로를 옮기려고 동결 manifest를 수정하지 않는다. `--download --verify-remote`는 이미 있는 파일도 원격 고정 바이트와 비교하지만 기존 파일을 다시 쓰지 않는다.

Validation 실행은 격리된 자료 담당자에게만 맡긴다. 부모/후보 작성자는 validation manifest 본문·원문·질문·정답을 열지 않는다. 이 도구의 phase 필드는 호출자가 그 역할을 지켰다는 기술적 증명이 아니다.

## 검증과 기록

- Manifest에 채택된 public source만 처리하며 저장소·40자리 commit·원래 파일 경로로 만든 HTTPS GitHub raw URL과 정확히 일치해야 한다. 다른 호스트·branch·redirect를 허용하지 않는다.
- 응답 크기, 원래 길이·SHA256·Git blob SHA1을 확인한 뒤에만 등록된 `.local` 경로에 새 파일을 쓴다. 정규화·렌더링·줄 합치기·번역은 하지 않는다.
- 모든 기존 파일과 경로 충돌을 먼저 확인한다. 경로 이탈·symlink/junction을 거부하며 기존 원문·문항·source helper·평가 정책은 수정하지 않는다.
- 새 metadata receipt에 manifest/script hash, 요청 수, 생성/재사용 여부와 검증 결과를 남긴다. 원문·원격 오류 본문·개인 절대경로는 출력하지 않는다. 중간 오류가 나면 완료된 항목과 실패를 보존한다.
- 이 receipt는 새 복구 확인의 기록이다. 과거 source 채택/수집 영수증이나 실제 Java 동등성 영수증을 대체하지 않는다. 모델·tokenizer·GPU·유료 API를 호출하지 않는다.

Synthetic byte fixtures는 빈 작업폴더 복구, 캐시 검증, 명시적 다운로드 허용, 잘못된 hash/경로/commit·redirect·응답 상한·manifest 변경·원격 오류 내용 숨김을 확인한다. Windows symlink 권한이 없는 환경의 skip은 실제 링크 차단 검증 성공으로 세지 않는다. 실제 공개 원문 확인 결과와 전체 회귀 결과는 STATUS와 저장된 receipt를 따른다. 새 checkout에서 전체 모델 실험까지 다시 실행했다는 주장은 아니다.
