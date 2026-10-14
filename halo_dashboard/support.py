"""Bounded logs, runtime snapshots and local, data-only feedback archives."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import platform
import re
import sys
import tempfile
import threading
import time
from urllib.parse import urlencode
import uuid
import zipfile

from .version import VERSION

LOG_BYTES = 2 * 1024 * 1024
LOG_BACKUPS = 3
EXPORT_LOG_BYTES = 256 * 1024
_secrets = set()
_secret_lock = threading.Lock()


def remember_devices(devices):
    """Keep identifiers in memory only, so even library errors can be redacted."""
    values = set()
    for info in devices:
        for field in ('serial_number', 'path'):
            value = info.get(field)
            if isinstance(value, bytes):
                values.update((value.decode('utf-8', errors='replace'), repr(value), value.hex()))
            elif value:
                values.add(str(value))
    with _secret_lock:
        _secrets.update(value for value in values if len(value) >= 3)


def redact_text(value):
    text = str(value)
    with _secret_lock:
        secrets = sorted(_secrets, key=len, reverse=True)
    for secret in secrets:
        text = text.replace(secret, '<device-id>')
    # Both current and older logs can contain paths, HID identifiers and screen text.
    text = re.sub(r'(?i)(?:\\\\\?\\hid#|hid#)[^\s\r\n\'"<>]*', '<hid-path>', text)
    text = re.sub(r'(?i)\b[A-Z]:[\\/][^\r\n\'"<>|]*', '<local-path>', text)
    text = re.sub(r'\\\\[^\s\\/]+\\[^\r\n\'"<>|]*', '<network-path>', text)
    text = re.sub(r'(?<!\w)/(?:Users|home|tmp|var|opt)/[^\r\n\'"<>]*', '<local-path>', text)
    # Older releases logged arbitrary screen content using repr().
    text = re.sub(r'\b(?:text|expected)=(?:\'(?:\\.|[^\'\\])*\'|"(?:\\.|[^"\\])*")',
                  '<screen-text>', text)
    return text


class PrivateFormatter(logging.Formatter):
    def format(self, record):
        return redact_text(super().format(record))


def configure_logging(state):
    state = Path(state)
    state.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger()
    for handler in logger.handlers[:]:
        if getattr(handler, 'halo_log', False):
            logger.removeHandler(handler)
            handler.close()
    handler = RotatingFileHandler(state / 'dashboard.log', maxBytes=LOG_BYTES,
                                  backupCount=LOG_BACKUPS, encoding='utf-8', delay=True)
    handler.halo_log = True
    handler.setFormatter(PrivateFormatter('%(asctime)s %(levelname)s [%(threadName)s] %(message)s'))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logging.info('Session started version=%s windows=%s python=%s frozen=%s',
                 VERSION, platform.platform(), platform.python_version(), getattr(sys, 'frozen', False))
    return handler


def install_exception_hooks():
    def unhandled(exc_type, value, traceback):
        logging.critical('Unhandled main-thread exception', exc_info=(exc_type, value, traceback))
    def thread_unhandled(args):
        logging.critical('Unhandled thread exception thread=%s', getattr(args.thread, 'name', 'unknown'),
                         exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
    sys.excepthook = unhandled
    threading.excepthook = thread_unhandled


def record_ui_exception(exc_type, value, traceback):
    logging.error('Unhandled UI callback exception', exc_info=(exc_type, value, traceback))


class RuntimeStatus:
    def __init__(self):
        self.lock = threading.Lock()
        self.started = time.monotonic()
        self.values = {'sync_active': False, 'device_connected': False, 'operation': 'idle',
                       'connect_attempts': 0, 'connections': 0, 'sync_failures': 0,
                       'sync_cycles': 0, 'last_success_elapsed_seconds': None}
        self.operation_started = None

    def update(self, **values):
        with self.lock:
            self.values.update(values)

    def increment(self, name):
        with self.lock:
            self.values[name] = self.values.get(name, 0) + 1
            if name == 'sync_cycles':
                self.values['last_success_elapsed_seconds'] = round(time.monotonic() - self.started, 2)

    @contextmanager
    def operation(self, name):
        with self.lock:
            self.values['operation'] = name
            self.operation_started = time.monotonic()
        try:
            yield
        finally:
            with self.lock:
                self.values['last_operation'] = name
                self.values['last_operation_seconds'] = round(time.monotonic() - self.operation_started, 3)
                self.values['operation'] = 'idle'
                self.operation_started = None

    def snapshot(self):
        with self.lock:
            return {**self.values, 'uptime_seconds': round(time.monotonic() - self.started, 2),
                    'operation_seconds': round(time.monotonic() - self.operation_started, 2)
                    if self.operation_started is not None else 0}


def plugin_information(assets, game_dirs):
    from .installer import PLUGIN_SHA256
    def inspect(path):
        try:
            if not path.is_file():
                return {'present': False}
            if path.stat().st_size > 8 * 1024 * 1024:
                return {'present': True, 'error': 'file exceeds inspection limit'}
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            return {'present': True, 'sha256': digest, 'matches_bundled_version': digest == PLUGIN_SHA256}
        except OSError as exc:
            return {'error': redact_text(exc)}
    return {'expected_sha256': PLUGIN_SHA256,
            'bundled': inspect(Path(assets) / 'assets' / 'scs-telemetry.dll'),
            'installed': {key: inspect(Path(value) / 'bin' / 'win_x64' / 'plugins' / 'scs-telemetry.dll')
                          for key, value in game_dirs.items() if key in ('ets2', 'ats') and value}}


def collect_diagnostics(state):
    """Independent of the HID writer: exporting still works if that thread stalls."""
    from .hardware import DeviceRegistry, diagnostics_document
    from .telemetry import Telemetry
    errors = []
    try:
        document = diagnostics_document(DeviceRegistry(Path(state) / 'validated-devices.json'))
    except Exception as exc:
        logging.exception('Feedback device enumeration failed')
        document = {'application': 'HaloTruckDash', 'version': VERSION, 'hid_queries_sent': False}
        errors.append('USB enumeration: ' + redact_text(exc))
    reader = None
    try:
        reader = Telemetry()
        document['telemetry'] = vars(reader.read())
    except Exception as exc:
        logging.exception('Feedback telemetry read failed')
        errors.append('Telemetry: ' + redact_text(exc))
    finally:
        if reader is not None:
            reader.close()
    document['collection_errors'] = errors
    return document


def export_feedback(state, document, runtime=None, options=None, plugins=None):
    state = Path(state)
    directory = state / 'feedback'
    directory.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    identifier = now.strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8]
    destination = directory / f'HaloTruckDash-feedback-{identifier}.zip'
    # Configuration is an explicit allowlist: no game paths, layout names or text.
    options = options or {}
    safe_options = {key: options[key] for key in ('mode', 'demo', 'hz', 'gear_mode', 'speed_unit', 'alerts')
                    if key in options and isinstance(options[key], (str, bool, int, float))}
    report = {'format': 'HaloTruckDash-feedback', 'format_version': 1, 'feedback_id': identifier,
              'created_utc': now.isoformat(), 'diagnostics': document,
              'runtime': runtime or {}, 'options': safe_options, 'plugins': plugins or {},
              'privacy': 'Local export only; no automatic upload. Paths and known USB identifiers redacted; no saved layouts or screen recovery content.'}
    for handler in logging.getLogger().handlers:
        handler.flush()
    handle, temporary = tempfile.mkstemp(prefix='feedback-', suffix='.tmp', dir=directory)
    os.close(handle)
    try:
        with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            def private(value):
                if isinstance(value, str):
                    return redact_text(value)
                if isinstance(value, dict):
                    return {key: private(item) for key, item in value.items()}
                if isinstance(value, list):
                    return [private(item) for item in value]
                return value
            archive.writestr('report.json', json.dumps(private(report), ensure_ascii=False, indent=2))
            archive.writestr('README.txt', '请在GitHub反馈中描述：发生时间、游戏、操作步骤、预期和实际表现。\n'
                              '将此ZIP手动附到问题中；程序不会自动上传。可先解压检查内容。\n'
                              '只含诊断、运行统计、插件校验与最近日志，不含配置文件、保存布局或原屏幕文字。\n')
            for index in range(LOG_BACKUPS, -1, -1):
                name = 'dashboard.log' + (f'.{index}' if index else '')
                path = state / name
                try:
                    with path.open('rb') as stream:
                        length = stream.seek(0, 2)
                        stream.seek(max(0, length - EXPORT_LOG_BYTES))
                        data = stream.read(EXPORT_LOG_BYTES).decode('utf-8', errors='replace')
                        if length > EXPORT_LOG_BYTES:
                            data = data.partition('\n')[2]  # Drop a partial first record.
                    archive.writestr('logs/' + name, redact_text(data))
                except FileNotFoundError:
                    continue
                except OSError as exc:
                    archive.writestr('logs/' + name + '.error.txt', redact_text(exc))
        Path(temporary).replace(destination)
    finally:
        Path(temporary).unlink(missing_ok=True)
    logging.info('Feedback archive exported id=%s', identifier)
    return destination


def feedback_url():
    return 'https://github.com/nj-yzf/HaloTruckDash/issues/new?' + urlencode(
        {'template': 'bug_report.yml', 'version': VERSION})
