import importlib
import sys
import unittest
from unittest.mock import patch

class SelectionGroupsTest(unittest.TestCase):
    def test_import_does_not_fetch_or_start_thread(self):
        sys.modules.pop('holdingStocks.selection_groups', None)
        with patch('urllib.request.urlopen') as fetch, patch('threading.Thread') as thread:
            importlib.import_module('holdingStocks.selection_groups')
            fetch.assert_not_called()
            thread.assert_not_called()

    def test_click_reads_database_then_starts_exactly_one_worker(self):
        module = importlib.import_module('holdingStocks.selection_groups')
        with module._LOCK:
            module._JOBS.clear()
        with patch.object(module, 'backend', return_value={'payload': '{"picks":{"items":[]}}'}) as fetch, patch.object(module.threading, 'Thread') as thread:
            job = module.start_replay('saved-group')
            fetch.assert_called_once_with('selection-groups/saved-group')
            thread.return_value.start.assert_called_once()
            self.assertEqual('running', module.replay_status(job['id'])['status'])
            with self.assertRaises(ValueError):
                module.start_replay('saved-group')
        with module._LOCK:
            module._JOBS.clear()
