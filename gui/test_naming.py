"""Exercise date naming with the actual gallery-dl filename formatter."""
from datetime import datetime, timezone
import unittest

from gallery_dl import extractor, path
from gui.naming import DATE_FORMATS, dated_path_format


class DateNamingTest(unittest.TestCase):
    def setUp(self):
        self.extractor = extractor.find('https://example.com/image.jpg')
        self.metadata = {
            'domain': 'example.com', 'path': '', 'filename': '原图_123_02',
            'extension': 'jpg', 'date': datetime(2026, 11, 13, 14, 30, 25, tzinfo=timezone.utc),
        }
        self.original = path.PathFormat(
            self.extractor).build_filename(self.metadata)

    def test_three_formats_preserve_original_and_extension(self):
        for (_, fmt), prefix in zip(DATE_FORMATS, ('2026-11-13', '20261113', '20261113_143025')):
            with self.subTest(fmt=fmt):
                formatter = dated_path_format(
                    path.PathFormat, fmt)(self.extractor)
                self.assertEqual(formatter.build_filename(
                    self.metadata), prefix + '_' + self.original)
                self.assertEqual(formatter.build_filename(
                    self.metadata), prefix + '_' + self.original)

    def test_absent_or_unusable_date_keeps_original(self):
        formatter = dated_path_format(
            path.PathFormat, DATE_FORMATS[2][1])(self.extractor)
        for value in (None, '', 'invalid', 0):
            with self.subTest(value=value):
                self.assertEqual(formatter.build_filename(
                    dict(self.metadata, date=value)), self.original)
        metadata = dict(self.metadata)
        del metadata['date']
        self.assertEqual(formatter.build_filename(metadata), self.original)

    def test_original_formatter_unchanged(self):
        dated_path_format(path.PathFormat, DATE_FORMATS[2][1])
        self.assertEqual(path.PathFormat(self.extractor).build_filename(
            self.metadata), self.original)


if __name__ == '__main__':
    unittest.main()
