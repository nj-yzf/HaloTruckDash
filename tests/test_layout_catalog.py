import unittest
from unittest.mock import patch
from halo_dashboard.layout import normalize, preset_layout
from halo_dashboard.layout_catalog import LayoutCatalog
from halo_dashboard.layout_library import LayoutLibrary

class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.library = LayoutLibrary()
        self.catalog = LayoutCatalog(self.library)

    def test_list_has_only_defaults_and_saved_layouts(self):
        self.library.save('白天', preset_layout(1))
        self.library.save('夜间', preset_layout(2))
        self.assertEqual(list(self.catalog.choices()), ['默认布局1', '默认布局2', '白天', '夜间'])
        for variant in (1, 2):
            self.assertEqual(self.catalog.resolve(f'默认布局{variant}'),
                             (f'preset{variant}', normalize(preset_layout(variant))))
        self.assertEqual(self.catalog.resolve('白天'), ('custom', normalize(preset_layout(1))))
        with self.assertRaises(ValueError):
            self.catalog.resolve('自由布局')
        self.library.delete('夜间')
        with self.assertRaises(ValueError):
            self.catalog.resolve('夜间')

    def test_legacy_names_colliding_with_defaults_are_still_accessible(self):
        for name in ('默认布局1', '默认布局2', '自由布局', '自定义 · 默认布局1'):
            self.library.save(name, {'items': []})
        choices = self.catalog.choices()
        self.assertEqual(len(choices), 6)
        for name in self.library.entries():
            label = self.catalog.label_for_saved(name)
            self.assertEqual(choices[label], ('saved', name))
            self.assertEqual(self.catalog.resolve(label), ('custom', {'items': []}))
        self.assertEqual(choices['默认布局1'], ('preset', 1))

    def test_default_copies_receive_unique_names(self):
        self.library.save('默认布局1（副本）', preset_layout(1))
        self.assertEqual(self.catalog.copy_name('默认布局1（副本）'), '默认布局1（副本） 2')
        self.assertNotIn(self.catalog.copy_name('我的布局'), self.library.entries())

    def test_defaults_remain_usable_if_saved_library_is_unreadable(self):
        with patch.object(self.library, 'entries', side_effect=ValueError('损坏的布局库')):
            self.assertEqual(self.catalog.resolve('默认布局1')[0], 'preset1')

if __name__ == '__main__':
    unittest.main()
