"""GUI date presets and an isolated adapter preserving extractor filenames."""
from datetime import date

DATE_FORMATS = (
    ('日期＋原文件名（2026-11-13）', '%Y-%m-%d'),
    ('紧凑日期＋原文件名（20261113）', '%Y%m%d'),
    ('日期＋时间＋原文件名（20261113_143025）', '%Y%m%d_%H%M%S'),
)
DEFAULT_DATE_FORMAT = DATE_FORMATS[2][1]
DATE_FORMAT_ENV = 'GALLERY_DL_GUI_DATE_FORMAT'


def dated_path_format(base, date_format):
    if date_format not in {value for _, value in DATE_FORMATS}:
        raise ValueError('Unknown publication date format')

    class PublicationDatePathFormat(base):
        def build_filename(self, kwdict):
            original = super().build_filename(kwdict)
            published = kwdict.get('date')
            if isinstance(published, date):
                return published.strftime(date_format) + '_' + original
            return original

    return PublicationDatePathFormat
