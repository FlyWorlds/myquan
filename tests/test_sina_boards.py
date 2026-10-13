from __future__ import annotations

from sectors.sina_boards import parse_sina_board_script


def test_parse_sina_board_script() -> None:
    script = (
        'var S_Finance_bankuai_class = {'
        '"gn_test":"gn_test,测试概念,26,55.73,0.22,0.41,634659424,16097762040,'
        'sz301021,2.624,67.280,1.720,英诺激光"'
        "};"
    )

    rows = parse_sina_board_script(script)

    assert len(rows) == 1
    row = rows[0]
    assert row.code == "gn_test"
    assert row.name == "测试概念"
    assert row.count == 26
    assert row.chg_pct == 0.41
    assert row.amount == 16097762040
    assert row.leader_code == "sz301021"
    assert row.leader_name == "英诺激光"
