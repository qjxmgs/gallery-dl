import unittest
from pathlib import Path
from unittest.mock import patch
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication
from gui.app import Window

class LinksTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.root = Path(r'D:\Develop\QA\gallery-dl\card-tests')
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
