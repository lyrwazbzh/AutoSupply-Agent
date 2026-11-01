from src.agent.tools.hitl_tools import parse_supplement_text


def test_parse_order_supplement_accepts_ui_example():
    parsed = parse_supplement_text(
        "零件ID=1，数量=100，单价=25.5",
        {"orderDetail": [{}]},
    )

    assert parsed["orderDetail"][0] == {
        "partId": 1,
        "quantity": 100,
        "unitPrice": 25.5,
    }


def test_parse_order_supplement_accepts_part_label_and_p_prefix():
    parsed = parse_supplement_text(
        "零部件ID：P001 数量：20 单价：12.8",
        {"orderDetail": [{}]},
    )

    assert parsed["orderDetail"][0] == {
        "partId": 1,
        "quantity": 20,
        "unitPrice": 12.8,
    }
