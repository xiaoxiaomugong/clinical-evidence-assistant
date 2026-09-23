from scripts.index_pdf_collection import order_text_blocks
from scripts import index_pdf_collection
from evidence_assistant.retrievers.common import publication_type_to_level
import sqlite3


def test_publication_mapping_normalizes_labels_without_guessing_unknown_designs():
    assert publication_type_to_level([" Randomized Controlled Trial "]) == "RCT"
    assert publication_type_to_level(["Consensus Statement"]) == "Consensus"
    assert publication_type_to_level(["Consensus Development Conference, NIH"]) == "Consensus"
    assert publication_type_to_level(["Guideline", "Randomized Controlled Trial"]) == "Other"
    assert publication_type_to_level(["Journal Article", "Research Support, Non-U.S. Gov't"]) == "Other"


def test_index_distinguishes_title_only_from_abstract_and_blank_pdf(tmp_path, monkeypatch):
    collection = tmp_path / "collection"
    collection.mkdir()
    rows = [{"pmid": "1", "dest_pdf": "1.pdf", "title": "A title without an abstract"},
            {"pmid": "2", "dest_pdf": "2.pdf", "title": "Trial outcomes"}]
    monkeypatch.setattr(index_pdf_collection, "load_manifest", lambda _: rows)
    import pymupdf
    with pymupdf.open() as document:
        document.new_page()
        document.save(str(collection / "2.pdf"))
    metadata = {"2": {"abstract": "Adults in the randomized trial were evaluated for outcomes. " * 10,
                       "study_type": "Randomized Controlled Trial", "evidence_level": "RCT"}}
    output = tmp_path / "index.sqlite3"
    index_pdf_collection.build_index(collection, output, metadata)
    with sqlite3.connect(str(output)) as connection:
        statuses = connection.execute("SELECT pmid, extraction_status FROM documents ORDER BY pmid").fetchall()
        assert statuses == [("1", "title_only"), ("2", "abstract_fallback")]
        assert connection.execute("SELECT id FROM chunks WHERE doc_id = 'pmid:1'").fetchone()[0] == "pmid:1:title"


def test_manifest_allows_growth_but_rejects_duplicate_primary_ids(tmp_path):
    import pytest
    path = tmp_path / "selected_manifest.csv"
    path.write_text("pmid,title,dest_pdf\n1,First,1.pdf\n2,Second,2.pdf\n")
    assert len(index_pdf_collection.load_manifest(tmp_path)) == 2
    path.write_text("pmid,title,dest_pdf\n1,First,1.pdf\n1,Duplicate,2.pdf\n")
    with pytest.raises(ValueError, match="unique"):
        index_pdf_collection.load_manifest(tmp_path)


def test_index_requires_substantive_chunks_and_does_not_keep_conflicting_type(tmp_path):
    import pymupdf
    (tmp_path / "selected_manifest.csv").write_text("pmid,title,dest_pdf\n1,Clinical evidence,1.pdf\n")
    with pymupdf.open() as document:
        for _ in range(8):
            document.new_page().insert_text((40, 50), "A short page fragment without a substantive paragraph.")
        document.save(str(tmp_path / "1.pdf"))
    metadata = {"1": {"study_type": "Guideline, Randomized Controlled Trial", "evidence_level": "RCT",
                       "abstract": "Adults were randomized and clinical outcomes evaluated. " * 10}}
    path = tmp_path / "index.sqlite3"
    index_pdf_collection.build_index(tmp_path, path, metadata)
    with sqlite3.connect(str(path)) as connection:
        assert connection.execute("SELECT extraction_status, evidence_level FROM documents").fetchone() == ("abstract_fallback", "Other")


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
