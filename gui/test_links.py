import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication
from gui.app import Window

class LinksTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.root = Path(r'D:\Develop\QA\gallery-dl') / datetime.now().strftime('%Y%m%d-%H%M%S')
        cls.root.mkdir(parents=True, exist_ok=True)

    def test_selection_migration_edit_and_restore(self):
        settings = QSettings(str(self.root / 'links.ini'), QSettings.Format.IniFormat)
        settings.clear()
        settings.setValue('links', '\n'.join('https://x.com/'+x for x in ['a','b','c','d','a']))
        w = Window(settings)
        w.show()
        self.app.processEvents()
        self.assertEqual(len(w.links.cards), 4)
        w.links.cards[2].check.setChecked(False)
        self.assertEqual(w.links.all.checkState(), Qt.CheckState.PartiallyChecked)
        w.directory.setText(str(self.root / 'downloads'))
        w.incremental.setChecked(False)
        with patch.object(w, 'next_url'):
            w.start()
        self.assertEqual(w.pending, ['https://x.com/a','https://x.com/b','https://x.com/d'])
        self.assertFalse(w.links.isEnabled())
        w.busy(False)
        editor = w.links.cards[0].editor
        before = w.links.cards[0].geometry()
        editor.setFocus()
        editor.setText('bad')
        self.assertFalse(editor.commit())
        self.assertEqual(w.links.cards[0].url, 'https://x.com/a')
        editor.setText('https://x.com/new')
        self.assertTrue(editor.commit())
        self.app.processEvents()
        self.assertEqual(before, w.links.cards[0].geometry())
        w.close()
        restored = Window(settings)
        self.assertEqual(restored.links.selected_urls(), ['https://x.com/new','https://x.com/b','https://x.com/d'])
        restored.links.clear()
        with patch('gui.app.QMessageBox.warning') as warning:
            restored.start()
            self.assertIn('请至少勾选', warning.call_args.args[2])
        restored.close()
        empty = Window(settings)
        self.assertEqual(empty.links.entries(), [])
        empty.close()

    def test_paste_and_select_all(self):
        from gui.link_list import LinkList
        links = LinkList()
        self.app.clipboard().setText('https://x.com/a\nhttps://x.com/a\nhttps://x.com/b')
        links.paste()
        self.assertEqual(len(links.cards), 2)
        links.all.click()
        self.assertEqual(links.selected_urls(), [])
        links.all.click()
        self.assertEqual(len(links.selected_urls()), 2)
        links.remove_card(links.cards[0])
        self.assertEqual(links.selected_urls(), ['https://x.com/b'])
        links.close()

    def test_card_folder_and_actions(self):
        settings = QSettings(str(self.root / 'folders.ini'), QSettings.Format.IniFormat)
        w = Window(settings)
        self.addCleanup(w.close)
        w.directory.setText(str(self.root / 'folder-downloads'))
        w.links.setPlainText('https://x.com/example')
        w.show()
        self.app.processEvents()
        card = w.links.cards[0]
        folder = Path(w.directory.text()) / 'twitter' / 'example'
        folder.mkdir(parents=True, exist_ok=True)
        with patch('gui.app.QDesktopServices.openUrl', return_value=True) as opened:
            card.folder.click()
            self.assertEqual(Path(opened.call_args.args[0].toLocalFile()), folder.resolve())
        card.remove.show()
        self.app.processEvents()
        self.assertLess(card.remove.geometry().bottom(), card.folder.y())
        self.assertEqual(card.remove.x(), card.folder.x())
        actual = Path(w.directory.text()) / 'actual-site' / 'account'
        actual.mkdir(parents=True, exist_ok=True)
        w.active_url = card.url
        w.handle_event({'type': 'start', 'path': str(actual / 'image.jpg')})
        with patch('gui.app.QDesktopServices.openUrl', return_value=True) as opened:
            card.folder.click()
            self.assertEqual(Path(opened.call_args.args[0].toLocalFile()), actual.resolve())
        restored = Window(settings)
        self.addCleanup(restored.close)
        self.assertEqual(restored.link_directories, w.link_directories)
        w.directory.setText(str(self.root / 'missing-root'))
        with patch('gui.app.QDesktopServices.openUrl') as opened, patch('gui.app.QMessageBox.information') as info:
            card.folder.click()
            opened.assert_not_called()
            info.assert_called_once()

    def test_scrollbar_uses_outer_gutter_without_shrinking_cards(self):
        from PySide6.QtCore import QPoint
        from PySide6.QtTest import QTest
        w = Window(QSettings(str(self.root / 'gutter.ini'), QSettings.Format.IniFormat))
        self.addCleanup(w.close)
        w.links.setPlainText('https://x.com/one')
        w.show()
        QTest.qWait(30)
        width = w.links.cards[0].width()
        w.links.setPlainText('\n'.join('https://x.com/user' + str(i) for i in range(30)))
        QTest.qWait(30)
        links = w.links
        bar = links.external_scrollbar
        self.assertTrue(bar.isVisible())
        self.assertEqual(links.cards[0].width(), width)
        edge = links.mapTo(bar.parentWidget(), QPoint(links.width(), 0)).x()
        self.assertGreater(bar.x(), edge)
        self.assertLessEqual(bar.geometry().right(), bar.parentWidget().width())
        native = links.scroll.verticalScrollBar()
        bar.setValue(bar.maximum())
        self.assertEqual(native.value(), native.maximum())
        native.setValue(native.maximum() // 2)
        self.assertEqual(bar.value(), native.value())
        w.rules_toggle.click()
        QTest.qWait(30)
        self.assertEqual(bar.pageStep(), native.pageStep())
        w.links.setPlainText('https://x.com/one')
        QTest.qWait(30)
        self.assertFalse(bar.isVisible())
        self.assertEqual(links.cards[0].width(), width)

    def test_drag_swap_insert_and_persistence(self):
        settings = QSettings(str(self.root / 'reorder.ini'), QSettings.Format.IniFormat)
        w = Window(settings)
        self.addCleanup(w.close)
        links = w.links
        links.setPlainText('\n'.join('https://x.com/' + c for c in 'abcd'))
        w.show()
        self.app.processEvents()
        original = list(links.cards)
        original[1].check.setChecked(False)
        target = original[2]
        for fraction, expected in [(0.14, ('insert', 2)), (0.16, ('swap', 2)),
                                   (0.84, ('swap', 2)), (0.86, ('insert', 3))]:
            self.assertEqual(links.target_at(target.y() + target.height() * fraction), expected)

        def drop(source, target, fraction):
            from PySide6.QtCore import QPoint
            links.drag_card = source
            links.update_drop(target.mapToGlobal(QPoint(20, int(target.height() * fraction))))
            self.assertFalse(links.drop_indicator.isHidden())
            if fraction < .15 or fraction > .85:
                self.assertEqual(links.drop_indicator.height(), 3)
            links.finish_drag()
            self.app.processEvents()
            self.assertTrue(links.drop_indicator.isHidden())
            self.assertEqual([links.rows.itemAt(i).widget() for i in range(4)], links.cards)

        drop(original[0], original[2], .5)
        self.assertEqual(links.cards, [original[i] for i in [2, 1, 0, 3]])
        drop(original[2], original[3], .95)
        self.assertEqual(links.cards, [original[i] for i in [1, 0, 3, 2]])
        drop(original[2], original[1], .05)
        self.assertEqual(links.cards, [original[i] for i in [2, 1, 0, 3]])
        self.assertFalse(original[1].check.isChecked())
        self.assertEqual(links.selected_urls(), ['https://x.com/' + c for c in 'cad'])
        links.drag_card = original[0]
        links.drop_target = ('swap', 0)
        links.finish_drag(False)
        expected = links.entries()
        w.save_preferences()
        restored = Window(settings)
        self.addCleanup(restored.close)
        self.assertEqual(restored.links.entries(), expected)

    def test_mouse_drag_and_disabled_list(self):
        from PySide6.QtCore import QPoint
        from PySide6.QtTest import QTest
        from gui.link_list import LinkList
        links = LinkList()
        self.addCleanup(links.close)
        links.resize(380, 420)
        links.setPlainText('https://x.com/a\nhttps://x.com/b\nhttps://x.com/c')
        links.show()
        self.app.processEvents()
        first, second, third = links.cards
        start = QPoint(first.width() - 40, 12)
        end = first.mapFromGlobal(third.mapToGlobal(QPoint(100, 32)))
        QTest.mousePress(first, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(first, end)
        self.assertIs(links.drag_card, first)
        QTest.mouseRelease(first, Qt.MouseButton.LeftButton, pos=end)
        self.assertEqual(links.cards, [third, second, first])
        links.setEnabled(False)
        links.drag_card = first
        links.drop_target = ('swap', 0)
        links.finish_drag()
        self.assertEqual(links.cards, [third, second, first])
