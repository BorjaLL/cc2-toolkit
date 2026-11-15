"""Designer process precedence, explicit choices and complete replacement reports."""
import json
import os
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))
import designer_settings as ds
from test_tools import FakeSlicer, run_main

CAT = {'enable_support': '1', 'support_type': 'tree(auto)', 'support_style': 'tree_slim',
       'support_threshold_angle': '40', 'support_top_z_distance': '0.23',
       'support_interface_spacing': '0', 'support_interface_pattern': 'rectilinear_interlaced',
       'prime_tower_width': '37', 'flush_multiplier': '0.75', 'wall_loops': '4',
       'layer_height': '0.16', 'initial_layer_print_height': '0.24', 'ironing_type': 'top',
       'sparse_infill_density': '17%', 'sparse_infill_pattern': 'gyroid'}


class DesignerSettingsTest(unittest.TestCase):
    def test_candle_default_path_keeps_supports_on(self):
        candle = dict(CAT, support_style='default', support_threshold_angle='30', support_top_z_distance='0.1')
        with tempfile.TemporaryDirectory() as root:
            model = os.path.join(root, 'candle.3mf')
            with zipfile.ZipFile(model, 'w') as z:
                z.writestr('Metadata/project_settings.config', json.dumps(candle))
            with FakeSlicer(root):
                out = os.path.join(root, 'out')
                run_main([model, '--out', out, '--dry-run'])
                with open(os.path.join(out, '_profiles/flat_process.json')) as f:
                    process = json.load(f)
            self.assertEqual(process['enable_support'], '1')
            self.assertEqual(process['support_top_z_distance'], '0.1')

    def test_flat_profile_keeps_designer_supports_even_with_supports_flag(self):
        with tempfile.TemporaryDirectory() as root:
            model = os.path.join(root, 'cat.3mf')
            with zipfile.ZipFile(model, 'w') as z:
                z.writestr('Metadata/project_settings.config', json.dumps(CAT))
            with FakeSlicer(root):
                for flags in ([], ['--supports']):
                    out = os.path.join(root, 'out')
                    run_main([model, '--out', out, '--dry-run'] + flags)
                    with open(os.path.join(out, '_profiles/flat_process.json')) as f:
                        process = json.load(f)
                    for key, value in CAT.items():
                        self.assertEqual(process[key], value, key)
                run_main([model, '--out', out, '--dry-run', '--proc', 'support_top_z_distance=0.3', '--layer', '0.20'])
                with open(os.path.join(out, '_profiles/flat_process.json')) as f:
                    process = json.load(f)
                self.assertEqual(process['support_top_z_distance'], '0.3')
                self.assertEqual(process['layer_height'], '0.2')
                run_main([model, '--out', out, '--dry-run', '--supports', '--layer', '0.20',
                          '--proc', 'layer_height=0.12', '--proc', 'enable_support=0'])
                with open(os.path.join(out, '_profiles/flat_process.json')) as f:
                    process = json.load(f)
                self.assertEqual(process['layer_height'], '0.12')
                self.assertEqual(process['enable_support'], '0')

    def test_audit_includes_unknown_and_machine_keys_and_numeric_equivalence(self):
        source = dict(CAT, machine_max_acceleration_x='20000', future_process_key='yes')
        used = dict(CAT, support_top_z_distance='0.230', machine_max_acceleration_x='8000')
        rows = {r['key']: r for r in ds.audit(source, used)}
        self.assertEqual(len(rows), len(source))
        self.assertEqual(rows['support_top_z_distance']['status'], 'survives')
        self.assertIn('machine', rows['machine_max_acceleration_x']['reason'])
        self.assertIn('unverified', rows['future_process_key']['reason'])

    def test_machine_material_and_unsupported_values_are_excluded(self):
        source = dict(CAT, machine_start_gcode='M600', filament_flow_ratio=['9'],
                      raft_first_layer_expansion='-1', wipe_tower_filament='2', wall_filament='0')
        kept = ds.process(source, printer='u1')
        self.assertEqual(kept, CAT)


if __name__ == '__main__':
    unittest.main()
