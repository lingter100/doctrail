"""Small synthetic bytes and fake network/processes only; no live resource or asset reads."""
import io
import json
import struct
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import prepare_meeting_free_qa as cli
from tools.free_qa import assets as a


def string(value):
    value = value.encode() if isinstance(value, str) else value
    return struct.pack('<Q', len(value)) + value


def encoded(kind, value):
    if kind == 8: return string(value)
    if kind == 9:
        element, values = value
        return struct.pack('<IQ', element, len(values)) + b''.join(encoded(element, x) for x in values)
    return struct.pack('<' + a.FORMATS[kind], value)


def entries(index=0):
    result = [('split.no', 2, index), ('split.count', 2, 2), ('split.tensors.count', 5, 2)]
    if index == 0:
        result += [('general.architecture', 8, 'qwen2'), ('tokenizer.ggml.model', 8, 'gpt2'),
                   ('tokenizer.ggml.tokens', 9, (8, ['한국어', 'e\u0301', '<|im_end|>'])),
                   ('tokenizer.ggml.token_type', 9, (5, [1, 1, 3])),
                   ('tokenizer.chat_template', 8, '한국어\r\n{{ messages }}'), ('tokenizer.ggml.add_bos_token', 7, 0)]
    return result


def gguf(rows=None, index=0):
    rows = entries(index) if rows is None else rows
    return b'GGUF' + struct.pack('<IQQ', 3, 1, len(rows)) + b''.join(string(k) + struct.pack('<I', t) + encoded(t, v) for k, t, v in rows)


def synthetic_spec():
    bodies = [gguf(index=i) + b'UNINTERPRETED-PAYLOAD' for i in range(2)]
    spec = {'gguf': {'shards': [{'filename': f'shard-{i}.gguf', 'size_bytes': len(body),
             'sha256': a.sha(body), 'url': f'https://huggingface.co/test/resolve/fixed/shard-{i}.gguf'} for i, body in enumerate(bodies)]}}
    return spec, bodies


def base_root(tmp_path):
    root = tmp_path / 'owned'; root.mkdir(); (root / 'assets').mkdir(); (root / 'tmp').mkdir()
    (root / 'profile.json').write_bytes(a.PROFILE.read_bytes())
    return root


def bind_attempt(root, operation, monkeypatch, deadline=1800):
    folder = root if operation == 'acquire' else root / 'verify'
    if operation != 'acquire': folder.mkdir(); (folder / 'tmp').mkdir()
    a.write_json(folder / 'attempt.json', {'token': 'fixed', 'operation': operation, 'root': str(root), 'deadline': deadline})
    monkeypatch.setenv('DOCTRAIL_ASSET_WORKER', 'fixed')


class Response(io.BytesIO):
    status = 200
    def __init__(self, body, url='https://cas-bridge.xethub.hf.co/test', headers=None):
        super().__init__(body); self.url = url; self.headers = headers or {}
    def geturl(self): return self.url


def opener_for(spec, bodies):
    urls = {s['url']: b for s, b in zip(spec['gguf']['shards'], bodies, strict=True)}
    calls = []
    def open_(req, **kwargs):
        calls.append(req.full_url)
        assert 0 < kwargs['timeout'] <= 10 and req.get_header('Accept-encoding') == 'identity'
        return Response(urls[req.full_url])
    return SimpleNamespace(open=open_), calls


def fake_publish(partial, target):
    assert not target.exists() and partial.parent == target.parent
    partial.rename(target)


def acquired(root, spec, bodies, monkeypatch):
    bind_attempt(root, 'acquire', monkeypatch)
    opener, calls = opener_for(spec, bodies)
    result = a.worker(root, 'acquire', 'fixed', 1800, spec=spec, opener=opener, publish=fake_publish, clock=lambda: 0)
    (root / 'supervisor.stdout').write_bytes(b'')
    (root / 'supervisor.stderr').write_bytes(b'')
    a.write_json(root / 'supervisor.json', {'status': 'TERMINAL_CLEAN', 'cleanup': {'all_absent': True, 'errors': []}})
    assert len(calls) == 2
    return result


def test_profile_exact_official_shards_provenance_and_runtime_refs():
    p = a.profile()
    assert sum(x['size_bytes'] for x in p['gguf']['shards']) == 4683073632
    assert p['gguf']['entry_filename'] == p['gguf']['shards'][0]['filename']
    assert p['gguf']['revision'] == 'bb5d59e06d9551d752d08b292a50eb208b07ab1f'
    assert p['provenance']['conversion_base_commit'] is None
    assert p['provenance']['base_metadata_observation_revision'] == 'a09a35458c702b33eeacc393d103063234e8bc28'
    assert p['license']['name'] == 'Apache-2.0'
    assert p['runtime_reuse']['runtime_file_count'] == len(p['runtime_reuse']['runtime_files']) == 55
    assert len(p['primary_metadata']) == 8 and not p['constraints']['native_execution_approved']
    assert p['preparation_limits']['transfer_bytes'] == a.TRANSFER
    assert p['preparation_limits']['new_owned_disk_bytes'] == a.DISK
    assert p['preparation_limits']['total_seconds'] == a.SECONDS
    assert p['preparation_limits']['embedded_metadata_read_limit_bytes'] == a.METADATA


def test_profile_byte_change_and_duplicate_json_fail(tmp_path, monkeypatch):
    profile = tmp_path / 'profile'; profile.write_bytes(a.PROFILE.read_bytes() + b' ')
    monkeypatch.setattr(a, 'PROFILE', profile)
    with pytest.raises(a.BoundaryError, match='profile_bytes'): a.profile()
    with pytest.raises(a.BoundaryError, match='duplicate_json'): a.parse_json('{"a":1,"a":2}')


def test_import_and_inspect_no_asset_runtime_or_network_access(monkeypatch, capsys):
    monkeypatch.setattr(cli, 'supervise', lambda *args, **kwargs: pytest.fail('not allowed'))
    cli.main(['inspect'])
    assert 'PROFILE_ONLY_ASSETS_NOT_READ' in capsys.readouterr().out
    with pytest.raises(a.BoundaryError): cli.main(['inspect', '--download'])
    with pytest.raises(a.BoundaryError): a.supervise('unused', 'acquire')
    with pytest.raises(a.BoundaryError): a.supervise('unused', 'verify-only', allow_download=True)


def test_gguf_raw_template_digest_typed_tokenizers_and_no_tensor_reads():
    data = gguf()
    class Limited(io.BytesIO):
        def read(self, n):
            assert n >= 0 and self.tell() + n <= len(data)
            return super().read(n)
    stream = Limited(data + b'FORBIDDEN-TENSOR-AREA')
    row = a.KVReader(stream).parse()
    assert stream.tell() == row['metadata_bytes_read'] == len(data)
    assert row['template'] == {'raw_utf8_sha256': a.sha('한국어\r\n{{ messages }}'.encode()), 'size_bytes': len('한국어\r\n{{ messages }}'.encode())}
    assert row['metadata_wire_sha256'] == a.sha(data)
    token = next(x for x in row['tokenizer'] if x['key'] == 'tokenizer.ggml.tokens')
    assert token['type'] == 9 and token['element_type'] == 8 and token['count'] == 3
    assert token['value_wire_sha256'] == a.sha(encoded(9, (8, ['한국어', 'e\u0301', '<|im_end|>'])))
    assert not row['tensor_descriptors_or_payload_parsed']
    binding = a.validate_metadata([row, a.KVReader(io.BytesIO(gguf(index=1))).parse()])
    assert not binding['execution_approved'] and binding['requires_separate_review']


@pytest.mark.parametrize('fault', ['magic', 'version', 'endian', 'zero-tensors', 'too-many-keys', 'truncated', 'duplicate', 'key', 'key-length', 'string-length', 'utf8', 'type', 'nested-array', 'array-count', 'array-size', 'bool', 'nan', 'limit'])
def test_gguf_strict_malformed_lengths_types_counts(tmp_path, fault):
    body = gguf()
    if fault == 'magic': body = b'FAIL' + body[4:]
    elif fault == 'version': body = body[:4] + struct.pack('<I', 2) + body[8:]
    elif fault == 'endian': body = body[:4] + struct.pack('>I', 3) + body[8:]
    elif fault == 'zero-tensors': body = body[:8] + b'\0' * 8 + body[16:]
    elif fault == 'too-many-keys': body = body[:16] + struct.pack('<Q', 65537) + body[24:]
    elif fault == 'truncated': body = body[:-1]
    elif fault == 'duplicate': body = gguf(entries() + [entries()[0]])
    elif fault == 'key': body = gguf([('bad key', 0, 1)])
    elif fault == 'key-length': body = body[:24] + struct.pack('<Q', 1025)
    elif fault == 'string-length': body = gguf([('x', 8, 'abc')])[:-11] + struct.pack('<Q', a.METADATA + 1)
    elif fault == 'utf8': body = gguf([('x', 8, b'\xff')])
    elif fault == 'type': body = b'GGUF' + struct.pack('<IQQ', 3, 1, 1) + string('x') + struct.pack('<I', 13)
    elif fault in {'nested-array', 'array-count', 'array-size'}:
        body = b'GGUF' + struct.pack('<IQQ', 3, 1, 1) + string('x') + struct.pack('<IIQ', 9, 9 if fault == 'nested-array' else 8, 2_000_001 if fault == 'array-count' else 2_000_000)
    elif fault == 'bool': body = gguf([('x', 7, 2)])
    elif fault == 'nan': body = gguf([('x', 6, float('nan'))])
    reader = a.KVReader(io.BytesIO(body), max_bytes=24 if fault == 'limit' else a.METADATA)
    with pytest.raises((a.BoundaryError, UnicodeDecodeError)): reader.parse()
    assert reader.used <= reader.maximum


@pytest.mark.parametrize('fault', ['split-index', 'split-count', 'split-type', 'tensor-total', 'architecture', 'template-missing', 'tokenizer-missing', 'second-mismatch'])
def test_gguf_known_expectations_and_missing_bindings_reject(fault):
    first, second = entries(), entries(1)
    if fault == 'split-index': second[0] = ('split.no', 2, 0)
    elif fault == 'split-count': first[1] = ('split.count', 2, 3)
    elif fault == 'split-type': first[0] = ('split.no', 4, 0)
    elif fault == 'tensor-total': first[2] = ('split.tensors.count', 5, 3)
    elif fault == 'architecture': first[3] = ('general.architecture', 8, 'qwen3')
    elif fault == 'template-missing': first = [r for r in first if r[0] != 'tokenizer.chat_template']
    elif fault == 'tokenizer-missing': first = [r for r in first if r[0] != 'tokenizer.ggml.tokens']
    elif fault == 'second-mismatch': second.append(('tokenizer.chat_template', 8, 'changed'))
    rows = [a.KVReader(io.BytesIO(gguf(x))).parse() for x in [first, second]]
    with pytest.raises(a.BoundaryError): a.validate_metadata(rows)


@pytest.mark.parametrize('fault', ['extra-file', 'extra-dir', 'hardlink', 'reparse', 'parent-reparse', 'disk'])
def test_exact_root_inventory_links_and_disk(tmp_path, monkeypatch, fault):
    root = base_root(tmp_path); spec, _ = synthetic_spec()
    path = root / 'assets' / spec['gguf']['shards'][0]['filename']; path.write_bytes(b'x')
    if fault == 'extra-file': (root / 'extra').write_bytes(b'x')
    elif fault == 'extra-dir': (root / 'extra').mkdir()
    elif fault in {'hardlink', 'reparse', 'parent-reparse'}:
        original = Path.lstat
        def altered(p):
            value = original(p)
            if p == (root.parent if fault == 'parent-reparse' else path):
                fields = {k: getattr(value, k) for k in ('st_mode', 'st_nlink', 'st_size', 'st_ino', 'st_dev', 'st_mtime_ns')}
                fields['st_nlink' if fault == 'hardlink' else 'st_file_attributes'] = 2 if fault == 'hardlink' else 1024
                return SimpleNamespace(**fields)
            return value
        monkeypatch.setattr(Path, 'lstat', altered)
    else: monkeypatch.setattr(a, 'DISK', 1)
    with pytest.raises(a.BoundaryError): a.scan(root, spec)


@pytest.mark.parametrize('url', ['http://huggingface.co/x', 'https://evil.example/x', 'https://huggingface.co.evil/x', 'https://user@huggingface.co/x', 'https://huggingface.co:444/x'])
def test_network_origin_fail_closed(url):
    with pytest.raises(a.BoundaryError): a.checked_url(url)


@pytest.mark.parametrize('fault', [None, 'short', 'long', 'hash', 'status', 'encoding', 'length', 'redirect', 'io'])
def test_streaming_download_no_retry_preserves_partial(tmp_path, fault):
    root = base_root(tmp_path); spec, bodies = synthetic_spec(); shard = spec['gguf']['shards'][0]
    body = bodies[0][:-1] if fault == 'short' else bodies[0] + b'x' if fault == 'long' else bodies[0]
    if fault == 'hash': body = b'x' + body[1:]
    response = Response(body, url='https://evil.example/x' if fault == 'redirect' else 'https://huggingface.co/x')
    if fault == 'status': response.status = 206
    if fault == 'encoding': response.headers = {'Content-Encoding': 'gzip'}
    if fault == 'length': response.headers = {'Content-Length': '0'}
    calls = []
    def opened(*args, **kwargs):
        calls.append(1)
        if fault == 'io': raise OSError('mocked offline')
        return response
    budget = a.Budget(root, spec, 1800, lambda: 0)
    if fault:
        with pytest.raises((a.BoundaryError, OSError)):
            a.download_one(root, shard, budget, SimpleNamespace(open=opened), fake_publish)
        assert (root / 'assets' / (shard['filename'] + '.part')).exists()
        assert not (root / 'assets' / shard['filename']).exists()
    else:
        result = a.download_one(root, shard, budget, SimpleNamespace(open=opened), fake_publish)
        assert result['sha256'] == shard['sha256']
        assert (root / 'assets' / shard['filename']).read_bytes() == body
        assert budget.transferred == len(body)
    with pytest.raises(a.BoundaryError): a.download_one(root, shard, budget, SimpleNamespace(open=opened), fake_publish)
    assert len(calls) == 1


def test_budget_cumulative_transfer_shared_deadline(tmp_path, monkeypatch):
    root = base_root(tmp_path); spec, _ = synthetic_spec()
    monkeypatch.setattr(a, 'TRANSFER', 3)
    budget = a.Budget(root, spec, 1800, lambda: 0); budget.check(3)
    with pytest.raises(a.BoundaryError, match='transfer'): budget.check(1)
    with pytest.raises(a.BoundaryError, match='deadline'): a.Budget(root, spec, 1800, lambda: 1795).check()


@pytest.mark.parametrize('fault', [None, 'changed', 'extra', 'missing', 'prior-cleanup', 'limit'])
def test_mock_acquire_then_offline_verify_seals_observations_not_approval(tmp_path, monkeypatch, fault):
    root = base_root(tmp_path); spec, bodies = synthetic_spec()
    result = acquired(root, spec, bodies, monkeypatch)
    assert not result['execution_approved']
    target = root / 'assets' / spec['gguf']['shards'][0]['filename']
    if fault == 'changed': target.write_bytes(b'x' + bodies[0][1:])
    elif fault == 'extra': (root / 'assets/extra.gguf').write_bytes(b'x')
    elif fault == 'missing': target.rename(target.with_suffix('.part'))
    elif fault == 'prior-cleanup': (root / 'supervisor.json').write_text(json.dumps({'status': 'FAILED', 'cleanup': {'all_absent': False, 'errors': ['unknown']}}))
    elif fault == 'limit': monkeypatch.setattr(a, 'METADATA', len(gguf()) + 23)
    bind_attempt(root, 'verify-only', monkeypatch)
    kwargs = {'spec': spec, 'opener': SimpleNamespace(open=lambda *args, **kw: pytest.fail('offline')), 'clock': lambda: 0}
    if fault:
        with pytest.raises(a.BoundaryError): a.worker(root, 'verify-only', 'fixed', 1800, **kwargs)
        assert (root / 'verify/failure.json').exists()
        if fault == 'limit': assert (root / 'verify/shard-1.json').exists()
    else:
        verified = a.worker(root, 'verify-only', 'fixed', 1800, **kwargs)
        assert verified['status'] == 'VERIFIED_BYTES_METADATA_UNREVIEWED' and verified['network_calls'] == 0
        assert not verified['metadata']['execution_approved']
        assert verified['metadata']['binding_sha256'] == a.sha(a.canonical(verified['metadata']['shards']))
        assert len(verified['metadata']['shards']) == 2
        with pytest.raises(FileExistsError): bind_attempt(root, 'verify-only', monkeypatch)


def test_worker_token_cannot_be_omitted_or_mismatched(tmp_path, monkeypatch):
    root = base_root(tmp_path); spec, _ = synthetic_spec(); bind_attempt(root, 'acquire', monkeypatch)
    with pytest.raises(a.BoundaryError, match='worker_binding'):
        a.worker(root, 'acquire', 'wrong', 1800, spec=spec)


class Clock:
    now = 0
    def __call__(self): return self.now
    def sleep(self, seconds): self.now += seconds


class FakePS:
    class NoSuchProcess(Exception): pass
    class AccessDenied(Exception): pass
    def __init__(self, fault=None): self.alive, self.fault, self.killed = True, fault, []
    def Process(self, pid):
        if self.fault == 'capture': raise self.AccessDenied()
        if not self.alive: raise self.NoSuchProcess()
        return SimpleNamespace(pid=pid, create_time=lambda: 3,
            exe=lambda: str(Path(a.sys.executable) if self.fault != 'unexpected' else Path(a.sys.executable).with_name('unknown.exe')),
            children=lambda recursive: [], kill=self.kill)
    def kill(self):
        if self.fault == 'cleanup': raise self.AccessDenied()
        self.killed.append(17); self.alive = False


class FakeProcess:
    pid = 17
    returncode = None
    def __init__(self, ps):
        self.ps = ps; self.handle_kills = 0; self.closed = False
        self._handle = SimpleNamespace(Close=lambda: setattr(self, 'closed', True))
    def poll(self):
        if self.ps.fault in {'timeout', 'capture', 'cleanup'}: return None
        self.ps.alive = False; self.returncode = 0; return 0
    def wait(self, timeout):
        if self.ps.fault == 'cleanup': raise subprocess.TimeoutExpired('mock', timeout)
        self.returncode = 0; return 0
    def kill(self): self.handle_kills += 1; self.ps.alive = False


@pytest.mark.parametrize('fault', [None, 'capture', 'unexpected', 'timeout', 'cleanup', 'log'])
def test_supervisor_only_owned_mock_worker_terminal_and_cleanup(tmp_path, monkeypatch, fault):
    root = tmp_path / 'owned'; spec, bodies = synthetic_spec()
    monkeypatch.setattr(a, 'profile', lambda: spec)
    monkeypatch.setattr(a, 'SECONDS', 6)
    monkeypatch.setenv('TEMP', 'hostile-external-temp')
    clock, ps = Clock(), FakePS(fault); process = FakeProcess(ps); launches = []
    def launch(argv, **kwargs):
        launches.append(argv)
        assert kwargs['env']['TEMP'] == kwargs['env']['TMP'] == str(root / 'tmp')
        if fault is None:
            token = kwargs['env']['DOCTRAIL_ASSET_WORKER']; monkeypatch.setenv('DOCTRAIL_ASSET_WORKER', token)
            opener, _ = opener_for(spec, bodies)
            a.worker(root, 'acquire', token, 6, spec=spec, opener=opener, publish=fake_publish, clock=clock)
        if fault == 'log': kwargs['stdout'].write(b'x' * (1024**2 + 1)); kwargs['stdout'].flush()
        return process
    if fault:
        with pytest.raises((a.BoundaryError, FakePS.AccessDenied)):
            a.supervise(root, 'acquire', allow_download=True, ps=ps, popen=launch, clock=clock, sleeper=clock.sleep)
        receipt = a.read_json(root / 'supervisor.json')
        assert receipt['status'] == 'FAILED'
        if fault == 'capture': assert process.handle_kills == 1 and process.closed and not receipt['cleanup']['all_absent']
        if fault == 'cleanup': assert not receipt['cleanup']['all_absent'] and not process.closed
    else:
        result = a.supervise(root, 'acquire', allow_download=True, ps=ps, popen=launch, clock=clock, sleeper=clock.sleep)
        assert result['status'] == 'ACQUIRED_VERIFIED_METADATA_UNREVIEWED' and process.closed
        assert a.read_json(root / 'supervisor.json')['status'] == 'TERMINAL_CLEAN'
    assert len(launches) == 1 and set(ps.killed) <= {17}
    with pytest.raises(FileExistsError): a.supervise(root, 'acquire', allow_download=True, ps=ps, popen=launch)



def test_bounded_small_control_file_read(tmp_path):
    path = tmp_path / 'control'; path.write_bytes(b'12345')
    with pytest.raises(a.BoundaryError, match='small_file_limit'): a.small_bytes(path, 4)
    assert a.small_bytes(path, 5) == b'12345'


@pytest.mark.parametrize('operation', ['acquire', 'verify-only'])
def test_late_first_shard_change_preserves_original_stages_and_fails(tmp_path, monkeypatch, operation):
    root = base_root(tmp_path); spec, bodies = synthetic_spec()
    first = root / 'assets' / spec['gguf']['shards'][0]['filename']
    def change():
        info = first.stat()
        a.os.utime(first, ns=(info.st_atime_ns, info.st_mtime_ns + 2_000_000_000))
    if operation == 'acquire':
        bind_attempt(root, operation, monkeypatch)
        opener, calls = opener_for(spec, bodies)
        def publish(partial, target):
            fake_publish(partial, target)
            if target.name == spec['gguf']['shards'][1]['filename']: change()
        with pytest.raises(a.BoundaryError, match='late_asset_change'):
            a.worker(root, operation, 'fixed', 1800, spec=spec, opener=opener, publish=publish, clock=lambda: 0)
        assert len(calls) == 2 and (root / 'download-1.json').exists()
        assert (root / 'failure.json').exists() and not (root / 'acquisition.json').exists()
    else:
        acquired(root, spec, bodies, monkeypatch); bind_attempt(root, operation, monkeypatch)
        original = a.verify_one
        def verify_file(path, shard, budget, remaining):
            row = original(path, shard, budget, remaining)
            if path.name == spec['gguf']['shards'][1]['filename']: change()
            return row
        monkeypatch.setattr(a, 'verify_one', verify_file)
        with pytest.raises(a.BoundaryError, match='late_asset_change'):
            a.worker(root, operation, 'fixed', 1800, spec=spec, clock=lambda: 0)
        assert (root / 'verify/shard-1.json').exists() and (root / 'verify/failure.json').exists()
        assert not (root / 'verify/metadata.json').exists()
    assert first.read_bytes() == bodies[0]


def test_download_publication_rejects_replacement_identity(tmp_path):
    root = base_root(tmp_path); spec, bodies = synthetic_spec()
    opener, _ = opener_for(spec, bodies)
    def replaced(partial, target):
        target.write_bytes(partial.read_bytes())  # distinct synthetic inode; original retained
    with pytest.raises(a.BoundaryError, match='published_identity'):
        a.download_one(root, spec['gguf']['shards'][0], a.Budget(root, spec, 1800, lambda: 0), opener, replaced)
    assert len(list((root / 'assets').iterdir())) == 2



def test_download_and_metadata_verification_share_same_deadline(tmp_path, monkeypatch):
    root = base_root(tmp_path); spec, bodies = synthetic_spec(); bind_attempt(root, 'acquire', monkeypatch)
    clock = Clock(); opener, calls = opener_for(spec, bodies)
    def near_end(partial, target):
        fake_publish(partial, target)
        if target.name == spec['gguf']['shards'][1]['filename']: clock.now = 1794
    def elapsed(path, shard, budget, remaining):
        assert budget.deadline == 1800 and clock.now == 1794
        clock.now += 2
        budget.time_check()
        pytest.fail('must not extend the metadata phase deadline')
    monkeypatch.setattr(a, 'verify_one', elapsed)
    with pytest.raises(a.BoundaryError, match='shared_deadline'):
        a.worker(root, 'acquire', 'fixed', 1800, spec=spec, opener=opener, publish=near_end, clock=clock)
    assert len(calls) == 2 and (root / 'download-2.json').exists()
    assert (root / 'failure.json').exists() and not (root / 'acquisition.json').exists()


class RedirectBody(Response):
    """An arbitrarily large/unending body must never be read, even boundedly."""
    def __init__(self, code, location, on_close=lambda: None):
        from email.message import Message
        headers = Message()
        if location is not None: headers['Location'] = location
        super().__init__(b'', headers=headers)
        self.code = self.status = code
        self.msg = 'synthetic redirect'
        self.read_calls = []
        self.on_close = on_close
    def read(self, *args):
        self.read_calls.append(args)
        pytest.fail('redirect body must not be consumed')
    def close(self):
        self.on_close()
        super().close()
    def info(self): return self.headers


def dispatch_opener(responses, requests):
    class OfflineHTTPS(a.urllib.request.HTTPSHandler):
        def https_open(self, req):
            requests.append((req.full_url, req.timeout))
            assert responses, 'unexpected retry or network dispatch'
            response = responses.pop(0)
            response.code = response.status
            response.msg = 'synthetic response'
            response.info = lambda: response.headers
            return response
    # The normal HTTPErrorProcessor and OpenerDirector dispatch the real status
    # handlers. Only the transport is fake; redirect handling is never stubbed.
    return OfflineHTTPS()


@pytest.mark.parametrize('status', [301, 302, 303, 307, 308])
@pytest.mark.parametrize('allowed', [True, False])
def test_real_redirect_dispatch_closes_unbounded_body_without_read(tmp_path, status, allowed):
    root = base_root(tmp_path); spec, bodies = synthetic_spec()
    budget = a.Budget(root, spec, 1800, lambda: 0)
    url = 'https://cas-bridge.xethub.hf.co/fixed' if allowed else 'https://evil.example/fixed'
    discarded = RedirectBody(status, url); final = Response(bodies[0], url=url)
    responses, requests = [discarded, final], []
    opener = a.urllib.request.build_opener(a.urllib.request.ProxyHandler({}),
        a.Redirects(budget), dispatch_opener(responses, requests))
    if allowed:
        result = a.download_one(root, spec['gguf']['shards'][0], budget, opener, fake_publish)
        assert result['sha256'] == spec['gguf']['shards'][0]['sha256']
        assert budget.transferred == len(bodies[0]) and len(requests) == 2
    else:
        with pytest.raises(a.BoundaryError, match='download_origin'):
            a.download_one(root, spec['gguf']['shards'][0], budget, opener, fake_publish)
        assert budget.transferred == 0 and len(requests) == 1
    assert discarded.closed and discarded.read_calls == []


@pytest.mark.parametrize('fault', ['deadline', 'transfer', 'disk', 'loop', 'hops', 'missing', 'scheme', 'credentials', 'relative', 'method'])
def test_real_redirect_dispatch_shared_budget_and_hop_policy(tmp_path, monkeypatch, fault):
    root = base_root(tmp_path); spec, _ = synthetic_spec(); clock = Clock()
    budget = a.Budget(root, spec, 1800, clock)
    start = spec['gguf']['shards'][0]['url']
    url = {'loop': start, 'missing': None, 'scheme': 'http://huggingface.co/x',
           'credentials': 'https://user@huggingface.co/x', 'relative': '/fixed'}.get(fault, 'https://huggingface.co/next')
    def close_event():
        if fault == 'deadline': clock.now = 1795
        elif fault == 'transfer': budget.transferred = a.TRANSFER + 1
        elif fault == 'disk': monkeypatch.setattr(a, 'DISK', 1)
    first = RedirectBody(302, url, close_event)
    redirects = [first]
    if fault == 'hops': redirects = [RedirectBody(302, f'https://huggingface.co/{i}') for i in range(11)]
    final = Response(b'x', url='https://huggingface.co/fixed')
    requests = []; responses = [*redirects, final]
    opener = a.urllib.request.build_opener(a.urllib.request.ProxyHandler({}),
        a.Redirects(budget), dispatch_opener(responses, requests))
    request = a.urllib.request.Request(start, method='POST' if fault == 'method' else 'GET')
    if fault == 'relative':
        with opener.open(request, timeout=10) as response: assert response.read(1) == b'x'
        assert requests[1][0] == 'https://huggingface.co/fixed'
    else:
        with pytest.raises(a.BoundaryError): opener.open(request, timeout=10)
        assert len(requests) == (11 if fault == 'hops' else 1)
    assert all(r.closed and not r.read_calls for r in redirects)
    assert budget.transferred == (a.TRANSFER + 1 if fault == 'transfer' else 0)


def test_default_download_opener_binds_redirects_to_shared_budget(tmp_path, monkeypatch):
    root = base_root(tmp_path); spec, bodies = synthetic_spec()
    budget = a.Budget(root, spec, 1800, lambda: 0)
    real_builder = a.urllib.request.build_opener
    redirects = [RedirectBody(307, 'https://huggingface.co/next')]
    requests, responses = [], [*redirects, Response(bodies[0])]
    def builder(*handlers):
        assert next(h for h in handlers if isinstance(h, a.Redirects)).budget is budget
        return real_builder(*handlers, dispatch_opener(responses, requests))
    monkeypatch.setattr(a.urllib.request, 'build_opener', builder)
    a.download_one(root, spec['gguf']['shards'][0], budget, publish=fake_publish)
    assert len(requests) == 2 and redirects[0].closed and not redirects[0].read_calls


@pytest.mark.parametrize('operation', ['acquire', 'verify-only'])
@pytest.mark.parametrize('fault', [None, 'result-read', 'receipt-write', 'final-scan', 'read-error', 'write-error', 'scan-error'])
def test_finalization_deadline_and_io_failure_append_invalidation(tmp_path, monkeypatch, operation, fault):
    spec, bodies = synthetic_spec(); root = tmp_path / 'owned'
    if operation == 'verify-only':
        root = base_root(tmp_path); acquired(root, spec, bodies, monkeypatch)
    monkeypatch.setattr(a, 'profile', lambda: spec)
    clock, ps = Clock(), FakePS(); process = FakeProcess(ps)
    folder = root if operation == 'acquire' else root / 'verify'
    state = {'worker_done': False, 'injected': False, 'launches': 0}
    original_read, original_write, original_scan = a.read_json, a.write_json, a.scan
    def inject(phase):
        if not state['worker_done'] or state['injected']: return
        if fault == phase:
            state['injected'] = True; clock.now = 1801
        elif fault == {'result-read': 'read-error', 'receipt-write': 'write-error', 'final-scan': 'scan-error'}[phase]:
            state['injected'] = True; raise OSError('synthetic final I/O failure')
    def read(path):
        result = original_read(path)
        if path == folder / ('acquisition.json' if operation == 'acquire' else 'metadata.json'): inject('result-read')
        return result
    def write(path, value):
        original_write(path, value)
        if path == folder / 'supervisor.json': inject('receipt-write')
    def scan(path, value):
        result = original_scan(path, value)
        if (folder / 'supervisor.json').exists(): inject('final-scan')
        return result
    def launch(argv, **kwargs):
        state['launches'] += 1
        token = kwargs['env']['DOCTRAIL_ASSET_WORKER']; monkeypatch.setenv('DOCTRAIL_ASSET_WORKER', token)
        opener, _ = opener_for(spec, bodies)
        a.worker(root, operation, token, 1800, spec=spec, opener=opener, publish=fake_publish, clock=clock)
        state['worker_done'] = True
        return process
    monkeypatch.setattr(a, 'read_json', read); monkeypatch.setattr(a, 'write_json', write); monkeypatch.setattr(a, 'scan', scan)
    kwargs = {'allow_download': operation == 'acquire', 'ps': ps, 'popen': launch, 'clock': clock, 'sleeper': clock.sleep}
    if fault is None:
        a.supervise(root, operation, **kwargs)
        assert original_read(folder / 'supervisor.json')['status'] == 'TERMINAL_CLEAN'
        assert not (folder / 'supervisor-invalidation.json').exists()
        if operation == 'acquire': a.acquisition_complete(root, spec)
    else:
        with pytest.raises((a.BoundaryError, OSError)): a.supervise(root, operation, **kwargs)
        assert state['injected']
        invalidated = original_read(folder / 'supervisor-invalidation.json')
        assert invalidated['status'] == 'INVALIDATED_NO_RETRY' and invalidated['prior_records_preserved']
        if not fault.endswith('error'): assert invalidated['observed_at'] > invalidated['deadline']
        expected = 'FAILED' if fault in {'result-read', 'read-error'} else 'TERMINAL_CLEAN'
        assert original_read(folder / 'supervisor.json')['status'] == expected
        preserved = (folder / 'supervisor.json').read_bytes()
        with pytest.raises(a.BoundaryError, match='supervisor_invalidated'): a.acquisition_complete(root, spec)
        with pytest.raises(a.BoundaryError, match='supervisor_invalidated'):
            a.supervise(root, 'verify-only', ps=ps, popen=launch, clock=clock, sleeper=clock.sleep)
        assert (folder / 'supervisor.json').read_bytes() == preserved
    assert state['launches'] == 1 and process.closed
