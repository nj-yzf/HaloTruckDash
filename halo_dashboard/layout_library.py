"""Versioned, data-only layout files and an atomically saved named library."""
from copy import deepcopy
import json
import hashlib
import re
from pathlib import Path
import tempfile
from .layout import normalize

FORMAT = 'halo-truck-dash-layout'
LIBRARY_FORMAT = 'halo-truck-dash-library'
VERSION = 1
MAX_BYTES = 1024 * 1024

def valid_name(name):
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 60 or any(ord(c) < 32 for c in name):
        raise ValueError('布局名称需为1–60个可见字符')
    return name.strip()

def document(name, model):
    return {'format': FORMAT, 'version': VERSION, 'name': valid_name(name), 'layout': normalize(model)}

def parse_document(data):
    if not isinstance(data, dict) or data.get('format') != FORMAT or type(data.get('version')) is not int or data['version'] != VERSION:
        raise ValueError('不是支持的Halo布局文件（需要版本1）')
    return document(data.get('name'), data.get('layout'))

def read_json(path):
    path = Path(path)
    if path.stat().st_size > MAX_BYTES:
        raise ValueError('布局文件超过1MB，无法读取')
    try:
        return json.loads(path.read_text(encoding='utf-8-sig'))
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ValueError('布局文件不是有效的UTF-8 JSON') from exc

def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix=path.name + '.', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        temporary.replace(path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()

def import_layout(path):
    return parse_document(read_json(path))

def export_layout(path, name, model):
    atomic_json(path, document(name, model))

class LayoutLibrary:
    def __init__(self, path=None):
        self.path = Path(path) if path is not None else None
        self.directory = (self.path.with_suffix('') if self.path.suffix.lower() == '.json' else self.path) if self.path else None
        self.legacy_path = self.directory.with_suffix('.json') if self.directory else None
        self.memory = {}
        self.warnings = []

    def _legacy_entries(self):
        if not self.legacy_path.exists():
            return {}
        data = read_json(self.legacy_path)
        if not isinstance(data, dict) or data.get('format') != LIBRARY_FORMAT or type(data.get('version')) is not int or data['version'] != VERSION:
            raise ValueError('布局库版本或格式无效；原文件已保留')
        layouts = data.get('layouts')
        if not isinstance(layouts, list) or len(layouts) > 200:
            raise ValueError('布局库内容无效或超过200个布局')
        result = {}
        for source in layouts:
            entry = parse_document(source)
            if entry['name'] in result:
                raise ValueError('布局库存在重名项')
            result[entry['name']] = entry['layout']
        return result

    def _filename(self, name):
        stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name).strip(' .') or '布局'
        suffix = hashlib.sha256(name.encode('utf-8')).hexdigest()[:10]
        return f'{stem[:60]}-{suffix}.json'

    def _prepare(self):
        marker = self.directory / '.legacy-imported'
        if self.legacy_path.exists() and not marker.exists():
            old = self._legacy_entries()  # Validate before creating or replacing anything.
            self.directory.mkdir(parents=True, exist_ok=True)
            existing = self._records(migrate=False)
            for name, model in old.items():
                if name not in existing:
                    target = self.directory / self._filename(name)
                    if target.exists():
                        raise ValueError(f'迁移目标文件已存在，原文件已保留：{target.name}')
                    export_layout(target, name, model)
            atomic_json(marker, {'migrated': True})
        else:
            self.directory.mkdir(parents=True, exist_ok=True)

    def _records(self, migrate=True):
        if migrate:
            self._prepare()
        self.warnings = []
        paths = sorted(self.directory.glob('*.json'), key=lambda path: path.name.casefold())
        if len(paths) > 200:
            raise ValueError('布局文件超过200个，请先整理布局文件夹')
        result = {}
        for path in paths:
            try:
                if path.is_symlink() or not path.is_file():
                    raise ValueError('不是普通布局文件')
                entry = import_layout(path)
                if entry['name'] in result:
                    raise ValueError('布局名称重复，请修改文件内名称或移走重复文件')
                result[entry['name']] = (entry['layout'], path)
            except (OSError, ValueError) as exc:
                self.warnings.append(f'{path.name}：{exc}')
        return result

    def entries(self):
        if self.directory is None:
            return deepcopy(self.memory)
        return {name: deepcopy(model) for name, (model, _) in self._records().items()}

    def storage_directory(self):
        if self.directory is None:
            raise ValueError('当前为临时布局库，没有本地文件夹')
        self._prepare()
        return self.directory.resolve()

    def new_name(self):
        names = self.entries()
        index = 1
        while f'我的布局{index:02d}' in names:
            index += 1
        return f'我的布局{index:02d}'

    def save(self, name, model):
        entry = document(name, model)
        if self.directory is None:
            if entry['name'] not in self.memory and len(self.memory) >= 200:
                raise ValueError('最多保存200个布局')
            self.memory[entry['name']] = deepcopy(entry['layout'])
        else:
            records = self._records()
            if entry['name'] not in records and len(list(self.directory.glob('*.json'))) >= 200:
                raise ValueError('最多保存200个布局')
            if entry['name'] in records:
                target = records[entry['name']][1]
            else:
                target = self.directory / self._filename(entry['name'])
                if target.exists():
                    raise ValueError('同名文件无法读取，未覆盖；请检查布局文件夹')
            export_layout(target, entry['name'], entry['layout'])
        return entry['name']

    def load(self, name):
        entries = self.entries()
        if name not in entries:
            raise ValueError('请选择已保存的布局名称，再点击读取')
        return deepcopy(entries[name])

    def delete(self, name):
        if self.directory is None:
            if name not in self.memory:
                raise ValueError('该布局尚未保存')
            del self.memory[name]
        else:
            records = self._records()
            if name not in records:
                raise ValueError('该布局尚未保存')
            records[name][1].unlink()
