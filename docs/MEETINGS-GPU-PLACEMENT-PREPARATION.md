# GPU 배치 비교 입력 준비

2026-10-16. 소스59개를 동결한 뒤, 최종 `bd4fbf38268065477394e907684b6ad0696d8ceb`의 push38870191406과 PR38870197353에서 Java·Python·웹 필수3job이 모두 통과했다. 사용자 계정의 author/committer와 working tree/HEAD 바이트를 확인했다. [CI 영수증](../experiments/results/meetings-gpu-placement-source-ci-v1.json)은 job 상태만 기록하며 과거 테스트 개수를 가져오지 않는다.

같은 HEAD에서 고정 `register` CLI를 **한 번** 실행했다. Tokenizer load1·서로 다른 prompt count1, 실제 native 생성0·다운로드0이다. 새 입력은 **5064 tokens**로 사전 범위4992–5120 안에 들었다. Filler·문구·schema·토큰 한도를 수정하지 않았다. Observer의 전체 CLI 시간38.797초, exit0·passed summary·최종 receipt·HEAD 불변을 확인했다. 이 시간은 모델 응답 시간이 아니다.

- [실행 계획](../data/evaluation/meetings-gpu-placement-execution-plan-v1.json): SHA `36b785b03d8ec0b31a043f6eb2f7be058715780898b1b362b03322c54fb21e35`.
- [준비 영수증](../data/evaluation/meetings-gpu-placement-preparation-v1.json): SHA `4debab954948aaae075c9fd5a291902977d4c5e88b3fd02da5cfcb07ce6e229c`.
- Private input: 41160 bytes, SHA `5912751486432f04255af44fa402d6a7b449c7748ce413e3bd0bdd381629d00b`.
- Prompt SHA `35f54c8dd0481672d03d984d51100a6b499a67a5257c6581d404505e0f5549c2`, token ID SHA `14a96729a7d0eaf4e029cc219ce26d997e66a4a2f9dacf0f477d1d22cbac1966`.

입력 원문과token IDs는 `.local/meetings-gpu-placement-preparation-v1/`에 있으며 준비 경로는 이미 소비됐다. 같은 입력을 다시 등록하지 않는다. 공개 plan/receipt에는 metadata와hash만 저장한다. [CLI 관측](../experiments/results/meetings-gpu-placement-preparation-cli-v1.json)은 원본 observer JSON의 정확한 복사본이다.

이 계획을 커밋한 뒤 같은 고정 입력으로 GPU24→28 순서, 각 최대1회, 합계 최대2회 생성한다. 소스·입력 증명과90초 전체 요청 제한, startup/cleanup 조건을 유지한다. 첫 arm의 독립적인 자원 실패는 안전한 정리와 공통 무결성을 확인한 경우에만 두 번째 arm으로 진행한다. 공통 무결성/저장 실패 또는 불확실한 정리는 중단한다. 재시도·warmup·설정 사다리는 없다.

두 arm의 구조 수용·출력 토큰 수 등이 비교 조건을 만족해야 관측 시간 비율을 계산한다. 준비 통과나 짧은 marker 생성 성공은 일반 질의응답 품질,928토큰 decode 부하, 서비스 채택의 근거가 아니다. 사용자 검수0·Phase1 미완료·PR14draft를 유지한다.
