"""One selection list for the main window and layout editor."""
from .layout import normalize, preset_layout

DEFAULT_NAMES = {'默认布局1': 1, '默认布局2': 2}
LEGACY_DRAFT_NAME = '自由布局'
LEGACY_NAMES = {'布局1': '默认布局1', '布局2': '默认布局2'}

def choices_for(entries):
    choices = {name: ('preset', variant) for name, variant in DEFAULT_NAMES.items()}
    for name in entries:
        label = name
        while label in choices:
            label = '自定义 · ' + label
        choices[label] = ('saved', name)
    return choices

class LayoutCatalog:
    def __init__(self, library):
        self.library = library

    def choices(self):
        return choices_for(self.library.entries())

    def resolve(self, label, speed_unit='km/h'):
        if label in DEFAULT_NAMES:
            variant = DEFAULT_NAMES[label]
            return f'preset{variant}', normalize(preset_layout(variant, speed_unit))
        choices = self.choices()
        if label not in choices:
            raise ValueError('该布局已不存在，请重新选择')
        kind, key = choices[label]
        if kind == 'saved':
            return 'custom', self.library.load(key)
        raise ValueError('未知布局类型')

    def label_for_saved(self, name):
        return next((label for label, choice in self.choices().items() if choice == ('saved', name)), None)

    def copy_name(self, base):
        names = set(self.library.entries()) | set(DEFAULT_NAMES)
        base = base[:60]
        name, counter = base, 2
        while name in names:
            suffix = f' {counter}'
            name = base[:60 - len(suffix)] + suffix
            counter += 1
        return name
