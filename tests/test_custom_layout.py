from copy import deepcopy
from datetime import datetime
import unittest
from halo_dashboard.layout import (DEFAULT_LAYOUT, render, render_preset, field_values,
                                  normalize, place_field, write_text, remove_at, gear_text, preset_layout,
                                  selected_between, move_items, remove_items, FIELD_WIDTHS, duration, owner_at)
from halo_dashboard.telemetry import Truck
from halo_dashboard.display import MODES, format_frame

class CustomLayoutTests(unittest.TestCase):
    def setUp(self):
        self.truck = Truck(connected=True, speed=80, limit=90, gear=12, rpm=1500,
            fuel=66, capacity=100, game_minutes=585, left=True, right=True, shifter_type='automatic')

    def test_presets_match_requested_spacing_and_all_modes_are_32_cells(self):
        self.assertEqual(render_preset(self.truck, 1), '< A12  080/090km/h  09:45  66% >')
        self.assertEqual(render_preset(self.truck, 2), '< A12  L090 080km/h  09:45 66% >')
        self.assertEqual(list(MODES), ['默认布局1', '默认布局2'])
        for mode in MODES.values():
            self.assertEqual(len(format_frame(self.truck, mode).text), 32)

    def test_free_fuel_caps_at_99_but_presets_keep_true_100(self):
        self.truck.fuel = 100
        self.assertIn('99%', render(self.truck, settings=preset_layout(1)))
        for variant in (1, 2):
            text = render_preset(self.truck, variant)
            self.assertEqual(len(text), 32)
            self.assertTrue(text.endswith('100%>'))
        self.truck.capacity = 0
        self.assertIn('--%', render(self.truck, settings=preset_layout(1)))
        self.assertIn('---%', render_preset(self.truck))

    def test_basic_controls_have_no_units_and_stable_width(self):
        values = field_values(self.truck)
        self.assertEqual({key: values[key] for key in ('speed', 'limit', 'fuel', 'time', 'gear', 'rpm')}, {'speed': '080', 'limit': '090', 'fuel': '66',
                                  'time': '09:45', 'gear': 'A12', 'rpm': '1500'})
        self.truck.gear = 5
        self.assertEqual(field_values(self.truck)['gear'], 'A5 ')
        self.truck.gear = 12
        self.assertEqual(field_values(self.truck, 'manual')['gear'], '12 ')

    def test_game_and_override_gear_modes(self):
        self.assertEqual(gear_text(self.truck), 'A12')
        for kind in ('manual', 'hshifter'):
            self.truck.shifter_type = kind
            self.assertEqual(gear_text(self.truck), '12')
        self.assertEqual(gear_text(self.truck, 'automatic'), 'A12')
        self.truck.gear = 0
        self.assertEqual(gear_text(self.truck), '0')
        self.assertEqual(gear_text(self.truck, 'automatic'), 'N')
        self.truck.gear = -2
        self.assertEqual(gear_text(self.truck), '-2')
        self.assertEqual(gear_text(self.truck, 'automatic'), 'R2')

    def test_moving_field_is_atomic_and_checks_overlap(self):
        model = place_field({'items': []}, 0, 'speed')
        model = place_field(model, 10, 'limit')
        saved = deepcopy(model)
        with self.assertRaises(ValueError):
            place_field(model, 9, 'speed', move_from=0)
        self.assertEqual(model, saved)
        moved = place_field(model, 1, 'speed', move_from=0)
        self.assertEqual(moved['items'][0]['start'], 1)
        self.assertEqual(len(moved['items']), 2)

    def test_boundary_drop_and_arrows_are_never_editable(self):
        with self.assertRaises(ValueError):
            place_field({'items': []}, 28, 'speed')
        model = place_field({'items': []}, 28, 'fuel')
        text = render(self.truck, settings=model)
        self.assertEqual(text[29:31], '66')
        self.assertEqual((text[0], text[31]), ('<', '>'))
        with self.assertRaises(ValueError):
            place_field(model, -1, 'rpm')

    def test_typing_spaces_brackets_and_units_does_not_touch_controls(self):
        model = place_field({'items': []}, 0, 'speed')
        model = write_text(model, 3, ' km/h [] %')
        self.assertEqual(render(self.truck, settings=model)[1:14], '080 km/h [] %')
        with self.assertRaises(ValueError):
            write_text(model, 0, 'x')
        self.assertEqual(remove_at(model, 1)['items'][0]['start'], 4)

    def test_full_row_text_and_bad_input(self):
        model = write_text({'items': []}, 0, '1234567890' * 3)
        self.assertEqual(render(self.truck, settings=model), '<' + '1234567890' * 3 + '>')
        for invalid in ('hello\nworld', '单位'):
            with self.assertRaises(ValueError):
                write_text({'items': []}, 0, invalid)
        with self.assertRaises(ValueError):
            write_text({'items': []}, 29, 'ab')

    def test_unknown_clock_and_pause_keep_positions(self):
        self.truck.game_minutes = None
        self.assertEqual(field_values(self.truck)['time'], '--:--')
        self.truck.game_minutes = 7 * 1440 + 585
        self.assertEqual(field_values(self.truck)['time'], '09:45')
        normal = format_frame(self.truck).text
        self.truck.paused = True
        self.assertEqual(format_frame(self.truck).text, normal)
        self.assertEqual(format_frame(self.truck).color, (143, 162, 184))

    def test_rejects_old_template_schema_and_duplicate_items(self):
        with self.assertRaises(ValueError):
            normalize({'left': '{speed}'})
        model = place_field({'items': []}, 0, 'speed')
        with self.assertRaises(ValueError):
            place_field(model, 0, 'limit')

    def test_group_selection_moves_controls_and_text_with_spacing_atomically(self):
        model = place_field({'items': []}, 1, 'speed')
        model = write_text(model, 5, 'km/h')
        model = place_field(model, 20, 'fuel')
        selected = selected_between(model, 2, 8)
        self.assertEqual(selected, {1, 5, 6, 7, 8})
        saved = deepcopy(model)
        for delta in (-2, 13, 24):
            with self.assertRaises(ValueError):
                move_items(model, selected, delta)
            self.assertEqual(model, saved)
        moved = move_items(model, selected, 3)
        self.assertEqual(render(self.truck, settings=moved)[5:13], '080 km/h')
        self.assertEqual(move_items(moved, {start + 3 for start in selected}, -3), model)
        self.assertEqual(remove_items(model, selected)['items'], [model['items'][-1]])

    def test_extended_fields_fixed_width_missing_state_and_clock(self):
        self.truck.on_job, self.truck.delivery_minutes = True, 1440 + 600
        self.truck.cruise, self.truck.cruise_speed = True, 83
        self.truck.distance, self.truck.route_seconds, self.truck.rest_minutes = 128.6, 8460, 310
        values = field_values(self.truck, now=datetime(2026, 10, 14, 23, 7))
        self.assertEqual(values['real_time'], '23:07')
        self.assertEqual(values['job_remaining'], '1d00h')
        self.assertEqual(values['nav_time'], '02:21')
        self.assertEqual(values['nav_distance'], '0129')
        self.assertEqual(values['cruise_speed'], '083')
        self.assertEqual(values['rest_time'], '05:10')
        self.assertEqual(values['fuel_liters'], '0066')
        for field, width in FIELD_WIDTHS.items():
            self.assertEqual(len(values[field]), width, field)
            self.assertEqual(len(render(self.truck, settings=place_field({'items': []}, 30 - width, field))), 32)
        self.truck.on_job, self.truck.cruise, self.truck.distance = False, False, 0
        values = field_values(self.truck)
        self.assertEqual(values['job_remaining'], '--:--')
        self.assertEqual(values['cruise_speed'], '---')
        self.assertEqual(values['nav_time'], '--:--')
        self.truck.on_job, self.truck.delivery_minutes = True, 1
        self.assertEqual(field_values(self.truck)['job_remaining'], '00:00')
        self.truck.delivery_minutes = None
        self.assertEqual(field_values(self.truck)['job_remaining'], '--:--')

    def test_five_cell_duration_boundaries_and_days(self):
        for minutes, expected in [(None, '--:--'), (-1, '00:00'), (0, '00:00'),
                                   (60, '01:00'), (1439, '23:59'), (1440, '24:00'),
                                   (1440.01, '1d00h'), (1441, '1d00h'),
                                   (2 * 1440 + 11 * 60, '2d11h'), (10 * 1440 - 1, '9d23h'),
                                   (10 * 1440, '010d+'), (1000 * 1440, '999d+')]:
            with self.subTest(minutes=minutes):
                self.assertEqual(duration(minutes), expected)
                self.assertEqual(len(duration(minutes)), 5)
        for field in ('nav_time', 'job_remaining', 'rest_time'):
            self.assertEqual(FIELD_WIDTHS[field], 5)
            # Older layouts keep their original anchor and simply free one cell.
            model = place_field({'items': []}, 24, field)
            self.assertIsNone(owner_at(model, 29))

if __name__ == '__main__':
    unittest.main()
