"""Focused CPU-only regression tests; imports no torch/model/GPU runtime."""
import csv
from pathlib import Path
import unittest
from split_inference.src.common.image_evidence_metadata import image_metadata


class ImageEvidenceMetadataTests(unittest.TestCase):
    def evidence(self, sid='149'):
        return {'sample_id': sid, 'member': 'example/member.JPEG',
                'jpeg_sha256': 'a' * 64, 'preprocessed_fp32_sha256': 'b' * 64}

    def test_matching_integer_index_and_decimal_csv_id(self):
        for sid in [0,149,299]:
            with self.subTest(sid=sid):
                result = image_metadata(sid, self.evidence(str(sid)))
                self.assertEqual(result['sample_id'], sid)
                self.assertIs(type(result['sample_id']), int)

    def test_actual_committed_csv_schema_and_selection_ids(self):
        root = Path(__file__).resolve().parents[1] / 'docs/imagenet_profile/20260915T112015Z'
        with (root / 'selected_image_evidence.csv').open() as f:
            records = list(csv.DictReader(f))
        members = (root / 'selected_imagenet_members.txt').read_text().splitlines()
        for sid in [0,149,299]:
            evidence = records[sid]
            self.assertIs(type(evidence['sample_id']), str)
            result = image_metadata(sid, evidence)
            self.assertEqual(result['member'], members[sid])
            self.assertEqual(result['sample_id'], sid)

    def test_mismatched_id_rejected(self):
        with self.assertRaisesRegex(ValueError, '149 does not match selected sample_id 0'):
            image_metadata(0, self.evidence())

    def test_missing_id_rejected(self):
        with self.assertRaisesRegex(ValueError, 'missing required sample_id'):
            image_metadata(0, {'member': 'image.JPEG'})

    def test_preserve_other_fields_single_id_and_no_input_mutation(self):
        evidence = self.evidence()
        evidence['extra'] = {'unchanged': [1,2,3]}
        before = dict(evidence)
        result = image_metadata(149, evidence)
        self.assertEqual(list(result).count('sample_id'), 1)
        self.assertEqual(set(result), set(evidence))
        self.assertEqual({k:v for k,v in result.items() if k != 'sample_id'},
                         {k:v for k,v in evidence.items() if k != 'sample_id'})
        self.assertEqual(evidence, before)
        self.assertIsNot(result, evidence)

    def test_malformed_csv_values_rejected(self):
        for raw in ['', ' 149', '149 ', '+149', '-1', '149.0', '0149', '00', '１４９', '1e2', '149\n', 149, 149.0, True, None]:
            with self.subTest(raw=raw), self.assertRaisesRegex(ValueError, 'canonical decimal CSV string'):
                image_metadata(149, self.evidence(raw))

    def test_evidence_id_range_rejected(self):
        for raw in ['300', '999']:
            with self.subTest(raw=raw), self.assertRaisesRegex(ValueError, 'outside 0..299'):
                image_metadata(149, self.evidence(raw))

    def test_selected_id_type_and_range_rejected(self):
        for sid in ['149', 149.0, True, None, -1, 300]:
            with self.subTest(sid=sid), self.assertRaisesRegex(ValueError, 'integer index in 0..299'):
                image_metadata(sid, self.evidence())


if __name__ == '__main__':
    unittest.main()
