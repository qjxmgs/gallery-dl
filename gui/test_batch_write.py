"""Disk evidence for bounded staging, retries and commit ordering."""
from datetime import datetime
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
from contextlib import ExitStack
from gui.batch_write import BatchWriter, MemoryFile


class BatchWriteTest(TestCase):
    def setUp(self):
        self.root = Path(r'D:\Develop\QA\gallery-dl') / (datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '-' + self._testMethodName)
        self.root.mkdir(parents=True)
        self.batch = BatchWriter(lambda *args, **kwargs: None, limit=16)

    def stream(self, name):
        path = str(self.root / name)
        stream = self.batch.files[path] = MemoryFile(self.batch, path)
        return stream

    def test_combined_threshold_and_large_file_spill(self):
        first = self.stream('one.part')
        with first:
            first.write(b'a' * 10)
        final = self.root / 'one.jpg'
        first.finalize = lambda: Path(first.path).replace(final)
        first.final_path = str(final)
        committed = []
        self.batch.defer(lambda: committed.append(final.read_bytes()))
        self.assertFalse(final.exists())
        second = self.stream('two.part')
        with second:
            second.write(b'b' * 10)
            self.assertFalse(second.memory)
            second.write(b'c' * 100)
        self.assertEqual(committed, [b'a' * 10])
        self.assertEqual(Path(second.path).read_bytes(), b'b' * 10 + b'c' * 100)
        self.assertEqual(self.batch.size, 0)

    def test_tail_flush_and_partial_resume(self):
        stream = self.stream('tail.part')
        with stream:
            stream.write(b'abc')
        self.assertFalse(Path(stream.path).exists())
        with stream:
            stream.seek(3)
            stream.write(b'def')
        saved = []
        self.batch.defer(lambda: saved.append(Path(stream.path).read_bytes()))
        self.batch.flush()
        self.assertEqual(saved, [b'abcdef'])
        self.assertEqual(self.batch.files, {})

    def test_failed_disk_write_never_reports_completion(self):
        stream = self.stream('error.part')
        with stream:
            stream.write(b'important')
        completed = []
        self.batch.defer(lambda: completed.append(True))
        with patch('builtins.open', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.batch.flush()
        self.assertFalse(completed)
        self.assertEqual(stream.stream.getvalue(), b'important')
        self.batch.flush()
        self.assertEqual(Path(stream.path).read_bytes(), b'important')
        self.assertEqual(completed, [True])

    def test_archive_waits_for_final_file(self):
        from gallery_dl import path, job, archive
        from gallery_dl.downloader.http import HttpDownloader
        with ExitStack() as stack:
            for owner, name in ((path, 'PathFormat'), (job.DownloadJob, 'handle_finalize'),
                                (HttpDownloader, 'download'), (archive.DownloadArchive, 'add'),
                                (archive.DownloadArchive, 'check')):
                stack.enter_context(patch.object(owner, name, getattr(owner, name)))
            self.batch.install()
            target = path.PathFormat.__new__(path.PathFormat)
            target._batch_http = True
            target.temppath = str(self.root / 'image.part')
            target.realpath = str(self.root / 'image.jpg')
            target.realdirectory = str(self.root)
            target.kwdict = {}
            target.delete = False
            with target.open('w+b') as fp:
                fp.write(b'image')
            target.finalize()
            records = archive.connect(str(self.root / 'archive.sqlite3'), '', '{id}')
            try:
                records.add({'id': 'one'})
                self.assertTrue(records.check({'id': 'one'}))
                self.assertEqual(records.connection.execute('SELECT count(*) FROM archive').fetchone()[0], 0)
                self.assertFalse(Path(target.realpath).exists())
                self.batch.flush()
                self.assertEqual(Path(target.realpath).read_bytes(), b'image')
                self.assertEqual(records.connection.execute('SELECT count(*) FROM archive').fetchone()[0], 1)
            finally:
                records.close()

