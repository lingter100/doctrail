# 로컬 실행과 복구

현재 상태는 로컬 단일 프로세스 검증이다. 인터넷 서비스 배포, TLS·외부 DB·오브젝트 스토리지 연동은 하지 않았다. GitHub 공개 소스 저장소와 인터넷 서비스 배포를 구분한다.

## 실행

Windows PowerShell에서 저장소 루트의 `./scripts/start.ps1`을 실행하면 웹과 Java 서비스를 빌드한 뒤 `http://127.0.0.1:8000`에서 시작한다. Java 21이 필요하며 Maven은 체크섬 고정 wrapper가 준비한다. 중지는 해당 터미널에서 Ctrl+C다. 다른 포트는 `./scripts/start.ps1 -Port 8001`로 정한다. 이전 Python 서비스는 `-Backend Python`을 명시한다.

수동 명령은 README를 따른다. Java 기본 DB는 `var/doctrail-java.sqlite3`, Python 참조 구현은 `var/doctrail.sqlite3`이며 변경은 `DOCTRAIL_DB` 환경변수다. 기존 데이터를 자동 복사하지 않으므로 Java에서 새 계정 화면이 나오는 것이 기존 계정 삭제를 뜻하지 않는다. [Java 전환과 복사·복구](JAVA-MIGRATION.md)를 따른다. DB에는 계정·세션·업로드 원문이 포함되므로 공개 저장소에는 넣지 않는다.

Windows의 PATH에 있는 Oracle javapath 실행기는 자식 JVM을 만들 수 있다. 실행·검증 도구는 `java.home`으로 실제 JDK 실행 파일을 찾아 서버를 실행하고 해당 JVM이 종료될 때까지 기다린다. 한글 경로의 이전 Python editable 설치에는 `hatch dev-mode-exact`와 `editables`를 유지한다.

## 백업과 복구

```powershell
uv run --no-sync python scripts/backup_db.py --source var/doctrail-java.sqlite3 --output var/backups/before-change.sqlite3
```

SQLite backup API로 일관된 복사본을 만들고 무결성을 검사한다. 기존 백업을 덮어쓰지 않는다. 복구할 때는 서버를 멈추고 새 경로로 복구한다.

```powershell
uv run --no-sync python scripts/backup_db.py --source var/backups/before-change.sqlite3 --output var/restored.sqlite3 --restore
$env:DOCTRAIL_DB = 'var/restored.sqlite3'
./scripts/start.ps1
```

복구본의 기존 세션을 지워 다시 로그인하도록 한다. 복구 후 로그인·문서 조회·검색을 확인한다. 원래 DB는 검토 후 사용자가 보존·제거 여부를 결정할 수 있도록 그대로 둔다. 스키마 v1 이외의 DB는 시작 시 거부한다. 아직 버전 간 자동 마이그레이션은 없다.

## 오류·로그

요청 ID, 라우트 템플릿, 응답 상태, 소요시간을 기록한다. 원문·질문·비밀번호·쿠키는 운영 로그에 넣지 않는다. 검색 질문은 사용자가 보는 개인 기록으로 DB에 저장된다. Java의 Tomcat access·파서·쿠키 오류 로거와 PDFBox/Fontbox 진단을 비활성화한다. 잘못된 HTTP 요청이나 쿠키는 서비스 필터에 도달하기 전 컨테이너에서 처리되므로 별도로 검증한다. Python의 Uvicorn access 로그도 검색어가 URL에 포함될 수 있어 비활성화한다.

파일은 5MiB, PDF 100페이지, 추출 문자는 300,000자로 제한한다. 스캔 PDF는 OCR을 지원하지 않는다는 처리 실패 상태로 남긴다. 최초 파싱 실패는 문서에서 확인·재처리할 수 있다. 정상 문서의 재처리가 실패하면 기존 정상 리비전을 유지한다. 네트워크 수집은 최대 3회 재시도하지만 영구 404·체크섬 오류를 성공으로 숨기지 않는다.

## 공개 배포 전 필요한 작업

현재 PDF 파서는 프로세스 격리·CPU 제한이 없고, 로그인 제한은 프로세스 메모리 기준이다. HTTP 로컬 쿠키는 Secure=false이며 HTTPS에서는 `DOCTRAIL_SECURE_COOKIE=1`이 필요하다. 공개 배포 전에는 파싱 워커 격리·타임아웃, 중앙 제한, 계정 수명주기, HTTPS/프록시 설정, 부하 검증, DB 접근·백업 보관 정책을 구현·검증한다.

검색마다 권한이 허용된 청크를 토큰화하고 SQLite 쓰기 트랜잭션을 유지하므로 현재 방식의 동시 처리 성능은 검증되지 않았다. 1,000문서 확장 시 색인 구조와 PostgreSQL 이전을 실측으로 판단한다. 비용 견적과 배포 후보를 사용자에게 제시하고 승인받은 뒤 외부 자원을 사용한다.
