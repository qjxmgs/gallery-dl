"""Live sorting must preserve record identity and numeric ordering."""
import unittest

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from gui.records import RecordTable


class RecordsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.table = RecordTable()

    def tearDown(self):
        self.table.close()

    def test_numeric_sort_and_live_reverse_order(self):
        for number in range(1, 13):
            self.table.update_record(f'{number}.jpg', state='下载中')
        self.table.sortItems(0, Qt.SortOrder.DescendingOrder)
        self.table.update_record('new.jpg', state='下载中')
        self.assertEqual(self.table.item(0, 0).text(), '13')
        self.assertEqual(self.table.item(12, 0).text(), '1')
        self.table.update_record('1.jpg', state='已完成')
        self.assertEqual(self.table.item(12, 3).text(), '已完成')

    def test_size_and_filename_sort_keep_updates_on_correct_file(self):
        self.table.update_record('b.jpg', state='下载中', size=2048, size_text='2.0 KB')
        self.table.update_record('a.jpg', state='已跳过', size=1048576, size_text='1.0 MB')
        self.table.sortItems(2, Qt.SortOrder.AscendingOrder)
        self.assertEqual(self.table.item(0, 1).text(), 'b.jpg')
        self.table.update_record('b.jpg', state='已完成', size=2097152, size_text='2.0 MB')
        self.assertEqual(self.table.item(1, 1).text(), 'b.jpg')
        self.assertEqual(self.table.item(1, 3).text(), '已完成')
        self.table.sortItems(1, Qt.SortOrder.AscendingOrder)
        self.assertEqual(self.table.item(0, 1).text(), 'a.jpg')
        self.table.sortItems(3, Qt.SortOrder.AscendingOrder)
        self.assertEqual(self.table.state('a.jpg'), '已跳过')

    def test_retention_evicts_oldest_not_first_sorted_row(self):
        self.table.sortItems(0, Qt.SortOrder.DescendingOrder)
        for number in range(2001):
            self.table.update_record(f'{number}.jpg', state='已完成')
        self.assertNotIn('0.jpg', self.table.records)
        self.assertIn('2000.jpg', self.table.records)
        self.assertEqual(self.table.rowCount(), 2000)
        self.assertEqual(self.table.item(0, 0).text(), '2001')
        self.table.clear_records()
        self.table.update_record('reset.jpg', state='下载中')
        self.assertEqual(self.table.item(0, 0).text(), '1')
        self.assertEqual(self.table.horizontalHeader().sortIndicatorOrder(), Qt.SortOrder.DescendingOrder)
