"""HTTPS, data-only release checks and cancellable verified ZIP downloads."""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import tempfile
import threading
import time
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
import zipfile

from .version import VERSION

FORMAT = 'halo-truck-dash-update'
MAX_MANIFEST = 128 * 1024
MAX_PACKAGE = 256 * 1024 * 1024


class UpdateCancelled(Exception):
    pass


def version_tuple(value):
    if not isinstance(value, str) or not re.fullmatch(r'v?(0|[1-9]\d{0,5})\.(0|[1-9]\d{0,5})\.(0|[1-9]\d{0,5})', value):
        raise ValueError('版本号必须为稳定版数字格式，例如0.5.0')
    return tuple(int(part) for part in value.removeprefix('v').split('.'))


def https_url(value):
    if not isinstance(value, str) or not value or len(value) > 4096 or any(ord(c) < 33 or ord(c) > 126 for c in value):
        raise ValueError('请填写有效的HTTPS更新地址；空格和中文需进行URL编码')
    try:
        parts = urlsplit(value)
        port = parts.port
        if parts.scheme != 'https' or not parts.hostname or parts.username is not None or parts.password is not None or parts.fragment or '\\' in value:
            raise ValueError()
        if port is not None and not 1 <= port <= 65535:
            raise ValueError()
    except ValueError as exc:
        raise ValueError('更新地址必须为不含账号、密码或片段的HTTPS网址') from exc
    return value


class HTTPSRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Reject downgrade/file redirects BEFORE issuing a second request.
        https_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def open_https(url, accept):
    request = Request(https_url(url), headers={
        'User-Agent': f'HaloTruckDash/{VERSION}', 'Accept': accept,
        'Cache-Control': 'no-cache', 'Accept-Encoding': 'identity',
    })
    return build_opener(HTTPSRedirectHandler()).open(request, timeout=15)


@dataclass(frozen=True)
class Release:
    version: str
    url: str
    size: int
    sha256: str
    notes: str

    def newer_than(self, current=VERSION):
        return version_tuple(self.version) > version_tuple(current)

    @property
    def filename(self):
        return f'HaloTruckDash-v{self.version}.zip'


def parse_manifest(data, source_url, requested_url=None):
    https_url(source_url)
    if not isinstance(data, dict) or data.get('format') != FORMAT or type(data.get('schema')) is not int or data['schema'] != 1:
        raise ValueError('不是支持的Halo Truck Dash更新清单（需要schema 1）')
    version = '.'.join(map(str, version_tuple(data.get('version'))))
    package = data.get('windows_x64')
    if not isinstance(package, dict) or not isinstance(package.get('url'), str) or not package['url']:
        raise ValueError('更新清单缺少Windows 64位下载地址')
    asset_base = source_url
    origin = urlsplit(https_url(requested_url or source_url))
    github_asset = re.fullmatch(r'/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/releases/(?:latest/download|download/([^/]+))/[^/]+', origin.path)
    if origin.hostname == 'github.com' and github_asset:
        # GitHub may finally redirect JSON to a signed CDN object URL whose
        # siblings are not release assets. Resolve relative assets at the
        # pinned GitHub tag instead. The default publisher tag is v<VERSION>.
        owner, repository, pinned_tag = github_asset.groups()
        tag = pinned_tag or f'v{version}'
        asset_base = f'https://github.com/{owner}/{repository}/releases/download/{tag}/latest.json'
    url = https_url(urljoin(asset_base, package['url']))
    size = package.get('size')
    if type(size) is not int or not 0 < size <= MAX_PACKAGE:
        raise ValueError('更新包大小无效或超过256MB')
    digest = package.get('sha256')
    if not isinstance(digest, str) or not re.fullmatch(r'[0-9a-fA-F]{64}', digest):
        raise ValueError('更新清单缺少有效的SHA256校验值')
    notes = data.get('notes', '')
    if not isinstance(notes, str) or len(notes) > 8000:
        raise ValueError('更新说明格式无效或过长')
    return Release(version, url, size, digest.lower(), notes)


def check_cancel(cancel):
    if cancel.is_set():
        raise UpdateCancelled('操作已取消')


def fetch_release(url, cancel=None, opener=open_https):
    cancel = cancel or threading.Event()
    check_cancel(cancel)
    with opener(https_url(url), 'application/json') as response:
        # Resolve relative assets against the pinned release URL after redirects,
        # so /releases/latest cannot mix a manifest with a later release's ZIP.
        source_url = https_url(response.geturl())
        chunks, received = [], 0
        deadline = time.monotonic() + 60
        while True:
            check_cancel(cancel)
            if time.monotonic() > deadline:
                raise TimeoutError('检查更新超时，请稍后重试')
            block = response.read(min(16384, MAX_MANIFEST + 1 - received))
            if not block:
                break
            chunks.append(block)
            received += len(block)
            if received > MAX_MANIFEST:
                raise ValueError('更新清单超过128KB')
    check_cancel(cancel)
    try:
        data = json.loads(b''.join(chunks).decode('utf-8-sig'))
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ValueError('更新地址没有返回有效的UTF-8 JSON清单') from exc
    return parse_manifest(data, source_url, requested_url=url)


def file_digest(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def validate_package(path):
    try:
        with zipfile.ZipFile(path) as package:
            files = package.infolist()
            if len(files) > 2000 or sum(item.file_size for item in files) > 512 * 1024 * 1024:
                raise ValueError('更新包解压大小或文件数异常')
            for item in files:
                name = item.filename.replace('\\', '/')
                parts = PurePosixPath(name).parts
                if name.startswith('/') or '..' in parts or ':' in name:
                    raise ValueError('更新包包含无效文件路径')
                if parts and parts[0].casefold() == 'data':
                    raise ValueError('更新包不应包含用户data目录')
            executable = package.getinfo('HaloTruckDash.exe')
            if executable.is_dir() or executable.file_size < 1:
                raise ValueError('更新包缺少有效的HaloTruckDash.exe')
            if package.testzip() is not None:
                raise ValueError('更新包ZIP完整性检查失败')
    except (zipfile.BadZipFile, KeyError, RuntimeError, NotImplementedError) as exc:
        raise ValueError('下载内容不是有效的Halo Truck Dash便携ZIP包') from exc


def download_release(release, directory, cancel=None, progress=lambda received, total: None, opener=open_https):
    cancel = cancel or threading.Event()
    check_cancel(cancel)
    # Revalidate even if called outside the GUI; all output names are generated
    # locally from a validated version, never from a server-provided filename.
    version_tuple(release.version)
    https_url(release.url)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / release.filename
    if destination.is_file() and destination.stat().st_size == release.size and file_digest(destination) == release.sha256:
        validate_package(destination)
        check_cancel(cancel)
        progress(release.size, release.size)
        return destination
    temporary = None
    try:
        with opener(release.url, 'application/zip') as response:
            https_url(response.geturl())
            length = response.headers.get('Content-Length')
            if length is not None and int(length) != release.size:
                raise ValueError('服务器返回的更新包大小与清单不一致，请重新检查更新')
            received, digest = 0, hashlib.sha256()
            deadline = time.monotonic() + 600
            with tempfile.NamedTemporaryFile(prefix=release.filename + '.', suffix='.part', dir=directory, delete=False) as stream:
                temporary = Path(stream.name)
                while True:
                    check_cancel(cancel)
                    if time.monotonic() > deadline:
                        raise TimeoutError('更新包下载超时，请稍后重试')
                    block = response.read(65536)
                    if not block:
                        break
                    received += len(block)
                    if received > release.size or received > MAX_PACKAGE:
                        raise ValueError('下载内容超过声明大小，已终止')
                    stream.write(block)
                    digest.update(block)
                    progress(received, release.size)
            check_cancel(cancel)
            if received != release.size or digest.hexdigest() != release.sha256:
                raise ValueError('更新包下载不完整或SHA256校验失败，请重新下载')
        validate_package(temporary)
        check_cancel(cancel)
        temporary.replace(destination)
        return destination
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
