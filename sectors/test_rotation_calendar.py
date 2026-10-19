import unittest
from sectors.rotation_cache import trading_columns_only


class TestRotationCalendar(unittest.TestCase):
    def test_closures_removed_with_aligned_values(self):
        payload = {'session': '2026-10-19', 'kinds': {'概念': {
            'dates': ['10月19日', '10月18日', '10月16日', '10月01日'],
            'by_metric': {'涨幅': {'top': [[1], [2], [3], [4]], 'bottom': [[5], [6], [7], [8]]}},
        }}}
        result = trading_columns_only(payload)['kinds']['概念']
        self.assertEqual(result['dates'], ['10月19日', '10月16日'])
        self.assertEqual(result['by_metric']['涨幅']['top'], [[1], [3]])
        self.assertEqual(result['by_metric']['涨幅']['bottom'], [[5], [7]])
        self.assertEqual(len(payload['kinds']['概念']['dates']), 4)

    def test_year_boundary(self):
        payload = {'session': '2026-01-05', 'kinds': {'概念': {
            'dates': ['01月05日', '01月02日', '12月31日'], 'by_metric': {},
        }}}
        self.assertEqual(trading_columns_only(payload)['kinds']['概念']['dates'], ['01月05日', '12月31日'])


if __name__ == '__main__':
    unittest.main()
