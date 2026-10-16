"""运行时文档入库的纯函数检查。不连接数据库。"""
import math
import sys
import unittest
from pathlib import Path

_HOLD = Path(__file__).resolve().parent
if str(_HOLD) not in sys.path:
    sys.path.insert(0, str(_HOLD))

import runtime_documents


class RuntimeDocumentSanitizeTest(unittest.TestCase):
    def test_non_finite_numbers_become_null(self):
        cleaned = runtime_documents._sanitize({"px": math.nan, "rows": [math.inf, 1.5], "name": "凯盛"})
        self.assertIsNone(cleaned["px"])
        self.assertIsNone(cleaned["rows"][0])
        self.assertEqual(cleaned["rows"][1], 1.5)
        self.assertEqual(cleaned["name"], "凯盛")


if __name__ == "__main__":
    unittest.main()
