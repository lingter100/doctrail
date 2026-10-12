# 데이터 구분

- `manifests/`: 출처, 고정 커밋, 이용 조건, 원문 체크섬. 공개 저장소에 포함한다.
- `raw/`, `processed/`: 재현 스크립트로 받은 공개 문서. Git 제외.
- `fixtures/`: AI가 작성한 합성 업무 문서. 실제 회사 문서·사용자 피드백이 아니다.
- `evaluation/`: 질문 생성 주체, 자동 검수, 사용자 검수 상태를 별도 기록한다.

초기 파일럿은 Kubernetes 공식 문서 8개(4개 주제의 한·영 번역 쌍)다. 1,000개 문서·200~300개 평가 질문 확보는 아직 완료되지 않았다. 파일럿은 파이프라인 점검용 `smoke` 집합이며 학습·개발·최종 테스트 성능의 근거가 아니다. 번역 쌍은 동일한 `family_id`를 가진다. 이후 모든 버전·번역·유사 문서를 같은 분할 그룹에 넣는다.

```powershell
uv run python scripts/prepare_pilot.py
```

다운로드 재시도는 최대 3회다. 원문 SHA-256이 다르면 중단한다. `hugo-light-v2` 정제는 YAML frontmatter·HTML 주석·Hugo 태그를 제거하되 용어 툴팁의 표시 문구를 보존한다. v1에서 태그와 함께 용어가 사라지는 문제를 발견해 수정했다. 문장·코드·링크는 유지한다. 외부 정의·포함 파일은 완전히 렌더링하지 못하므로 미해결 태그를 provenance에 기록하고 사용자 검수를 pending으로 둔다. 정제 완료가 의미 보존 검수를 뜻하지 않는다.

Kubernetes Authors의 원문은 [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)이며 [원본 LICENSE](https://github.com/kubernetes/website/blob/4b10551a8c6f0a3f100356d8fc3c6fb5cfde1448/LICENSE)를 따른다. 원출처·고정 버전·변경 사항은 manifest와 생성되는 provenance.json으로 유지한다. Kubernetes의 프로젝트 승인이나 제휴를 의미하지 않는다. 프로젝트 코드의 MIT License는 이 문서들에 적용되지 않는다.
