from scripts.index_pdf_collection import order_text_blocks


def test_order_text_blocks_reads_left_column_before_right_column():
    blocks = [
        (320.0, 100.0, 560.0, 140.0, "right first" * 15),
        (40.0, 100.0, 280.0, 140.0, "left first" * 15),
        (320.0, 180.0, 560.0, 220.0, "right second" * 15),
        (40.0, 180.0, 280.0, 220.0, "left second" * 15),
    ]

    ordered = order_text_blocks(blocks, page_width=600.0)

    assert [block[4] for block in ordered] == [
        "left first" * 15,
        "left second" * 15,
        "right first" * 15,
        "right second" * 15,
    ]


def test_order_text_blocks_keeps_full_width_anchor_between_regions():
    blocks = [
        (40.0, 80.0, 280.0, 110.0, "upper left " * 15),
        (320.0, 80.0, 560.0, 110.0, "upper right " * 15),
        (30.0, 160.0, 570.0, 210.0, "full width table"),
        (40.0, 250.0, 280.0, 280.0, "lower left " * 15),
        (320.0, 250.0, 560.0, 280.0, "lower right " * 15),
    ]

    ordered = order_text_blocks(blocks, page_width=600.0)

    assert [block[4] for block in ordered] == [
        "upper left " * 15,
        "upper right " * 15,
        "full width table",
        "lower left " * 15,
        "lower right " * 15,
    ]
