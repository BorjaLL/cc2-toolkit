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
        self.assertIn('unknown to ElegooSlicer', rows['future_process_key']['reason'])

    def test_machine_material_and_unsupported_values_are_excluded(self):
        source = dict(CAT, machine_start_gcode='M600', filament_flow_ratio=['9'],
                      raft_first_layer_expansion='-1', wipe_tower_filament='2', wall_filament='0')
        kept = ds.process(source, printer='u1')
        self.assertEqual(kept, CAT)

    def test_ooze_prevention_refused_on_single_nozzle_machine(self):
        # bd_3d-printing-nbfrz: designer ooze_prevention=1 + prime tower on the CC2 (one nozzle)
        # stopped the CLI with exit -51; absent from the flat profile it leaked back from the 3MF.
        semm = {'single_extruder_multi_material': '1'}
        source = dict(CAT, ooze_prevention='1', enable_prime_tower='1')
        self.assertNotIn('ooze_prevention', ds.process(source, semm))
        self.assertIn('-51', ds.reason('ooze_prevention', '1', semm))
        self.assertEqual(ds.process(source, {'single_extruder_multi_material': '0'})['ooze_prevention'], '1')
        with tempfile.TemporaryDirectory() as root:
            model = os.path.join(root, 'probe.3mf')
            with zipfile.ZipFile(model, 'w') as z:
                z.writestr('Metadata/project_settings.config', json.dumps(source))
            with FakeSlicer(root) as fake:
                with open(fake.files['machine'], 'w') as f:
                    json.dump(dict({'name': 'fake machine'}, **semm), f)
                out = os.path.join(root, 'out')
                run_main([model, '--out', out, '--dry-run'])
                with open(os.path.join(out, '_profiles/flat_process.json')) as f:
                    process = json.load(f)
                self.assertEqual(process['ooze_prevention'], '0')
                self.assertEqual(process['enable_prime_tower'], '1')
                out2 = os.path.join(root, 'out2')
                run_main([model, '--out', out2, '--dry-run', '--proc', 'ooze_prevention=1'])
                with open(os.path.join(out2, '_profiles/flat_process.json')) as f:
                    self.assertEqual(json.load(f)['ooze_prevention'], '1')   # --proc still wins


# Bambu-only process keys (bd_3d-printing-typ94) and per-plate process values (g0vh1).
BAMBU = {'ironing_direction': '45', 'infill_direction': '45', 'top_one_wall_type': 'not apply',
         'sparse_infill_anchor': '600', 'sparse_infill_anchor_max': '5', 'initial_layer_flow_ratio': '1',
         'prime_tower_rib_wall': '0', 'prime_tower_rib_width': '5', 'prime_tower_max_speed': '45',
         'enable_support_ironing': '1', 'skirt_per_object': '1', 'print_sequence': 'by layer',
         'counter_coef_1': ['0'], 'process_notes': '', 'brand_new_bambu_key': '1',
         'wall_infill_order': 'inner wall/outer wall/infill'}


def three_mf(path, settings, plates=()):
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('Metadata/project_settings.config', json.dumps(settings))
        if plates:
            blocks = ''.join('<plate>' + ''.join(f'<metadata key="{k}" value="{v}"/>' for k, v in p.items()) +
                             '</plate>' for p in plates)
            z.writestr('Metadata/model_settings.config', f'<config>{blocks}</config>')


class BambuOnlyKeysTest(unittest.TestCase):
    def test_translate_gives_destination_meaning(self):
        cc2, u1 = ds.translate(BAMBU, 'cc2'), ds.translate(BAMBU, 'u1')
        # Bambu ironing angle = (ironing_direction + infill_direction) % 180; absolute on U1,
        # fixed (absolute) on the CC2, whose plain ironing_angle is an offset from solid infill.
        self.assertEqual(u1['ironing_direction']['to'], {'ironing_angle': '90'})
        self.assertEqual(cc2['ironing_direction']['to'], {'ironing_angle': '90', 'ironing_angle_fixed': '1'})
        self.assertEqual(ds.translate({'ironing_direction': '90', 'infill_direction': '135'}, 'u1')
                         ['ironing_direction']['to'], {'ironing_angle': '45'})
        # both loaders read 'not apply' as on: the translation keeps it off
        self.assertEqual(u1['top_one_wall_type'], {'to': {'only_one_wall_top': '0'}, 'reason': None})
        self.assertIsNotNone(ds.translate({'top_one_wall_type': 'topmost'})['top_one_wall_type']['reason'])
        self.assertEqual(u1['sparse_infill_anchor']['to'], {'infill_anchor': '600'})
        self.assertEqual(u1['prime_tower_rib_wall']['to'], {'wipe_tower_wall_type': 'rectangle'})
        self.assertEqual(u1['prime_tower_max_speed']['to'], {'wipe_tower_max_purge_speed': '45'})
        self.assertEqual(u1['enable_support_ironing']['to'], {'support_ironing': '1'})
        self.assertEqual(u1['skirt_per_object']['to'], {'skirt_type': 'combined'})   # by layer: one skirt
        self.assertEqual(ds.translate({'skirt_per_object': '1', 'print_sequence': 'by object'})
                         ['skirt_per_object']['to'], {'skirt_type': 'perobject'})
        self.assertEqual(u1['initial_layer_flow_ratio'], {'to': {}, 'reason': None})   # 1 = neutral
        squish = ds.translate({'initial_layer_flow_ratio': '1.2'})['initial_layer_flow_ratio']
        self.assertEqual(squish['to'], {'bottom_solid_infill_flow_ratio': '1.2'})
        self.assertIn('bottom surface', squish['reason'])
        # a destination key the designer set explicitly is never replaced by a translation
        self.assertEqual(ds.translate({'sparse_infill_anchor': '600', 'infill_anchor': '2'})
                         ['sparse_infill_anchor']['to'], {})

    def test_process_withholds_translated_keys(self):
        kept = ds.process(BAMBU, printer='u1')
        for key in ('ironing_direction', 'top_one_wall_type', 'sparse_infill_anchor', 'prime_tower_rib_wall'):
            self.assertNotIn(key, kept)
        self.assertEqual(kept['ironing_angle'], '90')
        self.assertEqual(kept['only_one_wall_top'], '0')
        self.assertIn('wall_infill_order', kept)   # left to the destination loader (same rule as Bambu)
        self.assertEqual(ds.withheld(BAMBU), set(ds.translate(BAMBU)))

    def test_u1_auto_and_legacy_values_that_crash_or_refuse(self):
        # Bambu 2.5 prime_tower_brim_width -1: Snapmaker refuses the slice (min 0); Elegoo accepts
        self.assertNotIn('prime_tower_brim_width', ds.process({'prime_tower_brim_width': '-1'}, printer='u1'))
        self.assertEqual(ds.process({'prime_tower_brim_width': '-1'}, printer='cc2'), {'prime_tower_brim_width': '-1'})
        self.assertEqual(ds.process({'prime_tower_brim_width': '3'}, printer='u1'), {'prime_tower_brim_width': '3'})
        # the loader renames wipe_tower_extruder to wipe_tower_filament, which segfaults (pnw5)
        self.assertIn('pnw5', ds.reason('wipe_tower_extruder', '0', printer='u1'))
        self.assertIn('>= 1', ds.reason('perimeter_extruder', '0', printer='u1'))

    def test_audit_reports_mapped_loader_family_and_unknown(self):
        out = {'ironing_angle': '90', 'only_one_wall_top': '0', 'infill_anchor': '600', 'infill_anchor_max': '5',
               'wipe_tower_wall_type': 'rectangle', 'wipe_tower_rib_width': '5', 'wipe_tower_max_purge_speed': '45',
               'support_ironing': '1', 'skirt_type': 'combined', 'wall_sequence': 'inner wall/outer wall',
               'infill_direction': '45', 'print_sequence': 'by layer'}
        rows = {r['key']: r for r in ds.audit(BAMBU, out, printer='u1')}
        for key in ('ironing_direction', 'top_one_wall_type', 'sparse_infill_anchor', 'prime_tower_rib_wall',
                    'skirt_per_object', 'initial_layer_flow_ratio', 'wall_infill_order'):
            self.assertEqual(rows[key]['status'], 'mapped', key)
        self.assertEqual(rows['ironing_direction']['our_value'], {'ironing_angle': '90'})
        self.assertIn('loader', rows['wall_infill_order']['mapping'])
        self.assertIn('circle', rows['counter_coef_1']['reason'])
        self.assertIn('metadata', rows['process_notes']['reason'])
        self.assertIn('unknown to Snapmaker Orca', rows['brand_new_bambu_key']['reason'])
        # an output that lost the translation is a replacement, never 'mapped'
        lost = {r['key']: r for r in ds.audit(BAMBU, dict(out, only_one_wall_top='1'), printer='u1')}
        self.assertEqual(lost['top_one_wall_type']['status'], 'replaced-with-reason')
        self.assertIn('only_one_wall_top=0', lost['top_one_wall_type']['reason'])
        # a recipe lock on the destination key names the lock as the reason
        locked = {r['key']: r for r in ds.audit(BAMBU, dict(out, only_one_wall_top='1'),
                                                {'only_one_wall_top': 'explicit recipe setting'}, printer='u1')}
        self.assertEqual(locked['top_one_wall_type']['reason'], 'explicit recipe setting')

    def test_flat_profile_bambu_names_do_not_undo_translation(self):
        # The Elegoo stock profile itself carries top_one_wall_type / ironing_direction after their
        # destination keys; the CLI renames them in file order, so they must leave the flat profile.
        with tempfile.TemporaryDirectory() as root:
            model = os.path.join(root, 'm.3mf')
            three_mf(model, {'top_one_wall_type': 'not apply', 'ironing_direction': '45', 'infill_direction': '45'})
            with FakeSlicer(root) as fake:
                with open(fake.files['process'], 'w') as f:
                    json.dump({'name': 'fake process', 'only_one_wall_top': '1', 'ironing_angle': '0',
                               'top_one_wall_type': 'all top', 'ironing_direction': '45'}, f)
                out = os.path.join(root, 'out')
                run_main([model, '--out', out, '--dry-run'])
                with open(os.path.join(out, '_profiles/flat_process.json')) as f:
                    process = json.load(f)
        self.assertNotIn('top_one_wall_type', process)
        self.assertNotIn('ironing_direction', process)
        self.assertEqual(process['only_one_wall_top'], '0')
        self.assertEqual((process['ironing_angle'], process['ironing_angle_fixed']), ('90', '1'))

    def test_plate_process_values(self):
        plates = [{'plater_id': '1', 'first_layer_print_sequence': '2 3 4 1', 'print_sequence': 'by object'},
                  {'plater_id': '2', 'first_layer_print_sequence': '2 4 1 3', 'print_sequence': '',
                   'spiral_mode': 'true'}]
        with tempfile.TemporaryDirectory() as root:
            model = os.path.join(root, 'm.3mf')
            three_mf(model, {'print_sequence': 'by layer', 'first_layer_print_sequence': ['0']}, plates)
            self.assertEqual(ds.read(model)['print_sequence'], 'by layer')
            one = ds.read(model, 1)
            self.assertEqual((one['print_sequence'], one['first_layer_print_sequence']), ('by object', ['2', '3', '4', '1']))
            two = ds.read(model, [2])
            self.assertEqual((two['print_sequence'], two['spiral_mode']), ('by layer', '1'))   # '' = global
            self.assertEqual(ds.sliced_plates(model, 'plate_2'), [2])
            self.assertIsNone(ds.sliced_plates(model, None))
            merged, conflicts = ds.plate_process(zipfile.ZipFile(model).read('Metadata/model_settings.config').decode(),
                                                 [1, 2])
            self.assertEqual(merged, {})
            self.assertEqual(conflicts, {'first_layer_print_sequence', 'print_sequence', 'spiral_mode'})

    def test_u1_report_plate_rows(self):
        plates = [{'plater_id': '1', 'filament_maps': '2 1', 'filament_map_mode': 'Auto For Flush',
                   'filament_volume_maps': '0 1', 'first_layer_print_sequence': '2 1', 'thumbnail_file': 'x.png'},
                  {'plater_id': '2', 'filament_maps': '1 1'}]
        with tempfile.TemporaryDirectory() as root:
            model = os.path.join(root, 'm.3mf')
            three_mf(model, {'first_layer_print_sequence': ['0']}, plates)
            prepared = os.path.join(root, 'u1.3mf')
            with zipfile.ZipFile(prepared, 'w') as z:
                z.writestr('Metadata/model_settings.config',
                           '<config><object id="2"><metadata key="extruder" value="1"/>'
                           '<part id="1" subtype="normal_part"><metadata key="extruder" value="2"/></part>'
                           '<part id="2" subtype="normal_part"></part></object></config>')
            g = os.path.join(root, 'plate_1.gcode')
            with open(g, 'w') as f:
                f.write('; CONFIG_BLOCK_START\n; first_layer_print_sequence = 2,1\n; CONFIG_BLOCK_END\n'
                        '; filament used [mm] = 10.0, 5.0, 0.00, 0.00\n')
            rows = ds.report(g, [model], printer='u1', prepared=[prepared], plate=1)['settings']
            plate = {(r['scope'].split('/')[-1], r['key']): r for r in rows if '/plate:' in r.get('scope', '')}
            self.assertEqual(plate[('plate:1', 'first_layer_print_sequence')]['status'], 'mapped')
            self.assertEqual(plate[('plate:1', 'filament_maps')]['status'], 'mapped')
            self.assertIn('T0, T1', plate[('plate:1', 'filament_maps')]['evidence'])
            # filament 2 asked for a high-flow nozzle: no U1 counterpart
            self.assertIn('high-flow', plate[('plate:1', 'filament_volume_maps')]['reason'])
            self.assertIn('not in this slice', plate[('plate:2', 'filament_maps')]['reason'])
            self.assertIn('UI metadata', plate[('plate:1', 'thumbnail_file')]['reason'])
            # a G-code printing a filament the plate objects do not use is not proven
            with open(g, 'w') as f:
                f.write('; filament used [mm] = 10.0, 5.0, 3.0, 0.00\n')
            rows = ds.report(g, [model], printer='u1', prepared=[prepared], plate=1)['settings']
            maps = next(r for r in rows if r['key'] == 'filament_maps' and r['scope'].endswith('plate:1'))
            self.assertEqual(maps['status'], 'replaced-with-reason')

    def test_paint_states(self):
        self.assertEqual(ds._paint_states('4'), {1})     # leaf state 1
        self.assertEqual(ds._paint_states('8'), {2})
        self.assertEqual(ds._paint_states('0C'), {3})    # 11 + group 0 = state 3


if __name__ == '__main__':
    unittest.main()
