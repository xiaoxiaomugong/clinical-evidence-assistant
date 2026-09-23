"""Candidate governance tests use local synthetic PDFs and actual SQLite files."""
import csv
import hashlib
import importlib.util
import json
import sqlite3

import pymupdf
import pytest

from tests.test_quality_tools import make_index


def candidate_builder():
    spec = importlib.util.find_spec("scripts.prepare_corpus_candidate")
    assert spec is not None, "immutable corpus candidate preparation is not implemented"
    from scripts.prepare_corpus_candidate import prepare_candidate
    return prepare_candidate


def write_pdf(path, title):
    with pymupdf.open() as document:
        page = document.new_page()
        page.insert_textbox(pymupdf.Rect(40, 40, 550, 140), title, fontsize=18)
        page.insert_textbox(pymupdf.Rect(40, 170, 550, 750),
                            "Abstract\nAdults were randomized and clinical outcomes measured. " * 30, fontsize=10)
        document.save(str(path))


def fixture_inputs(tmp_path):
    source = tmp_path / "source.sqlite3"
    make_index(source, [{"title": "A randomized study of adult clinical outcomes", "level": "Other"},
                        {"title": "Another study of adult clinical outcomes", "level": "Other"}])
    collection = tmp_path / "collection"
    collection.mkdir()
    write_pdf(collection / "1.pdf", "A randomized study of adult clinical outcomes")
    write_pdf(collection / "2.pdf", "Unrelated article about astronomy and distant stars")
    with (collection / "selected_manifest.csv").open("w") as handle:
        writer = csv.DictWriter(handle, fieldnames=["pmid", "title", "dest_pdf"])
        writer.writeheader()
        writer.writerows([{"pmid": "1", "title": "A randomized study of adult clinical outcomes", "dest_pdf": "1.pdf"},
                          {"pmid": "2", "title": "Another study of adult clinical outcomes", "dest_pdf": "2.pdf"}])
    metadata = tmp_path / "metadata.json"
    metadata.write_text(json.dumps([
        {"id": "pmid:1", "study_type": "Randomized Controlled Trial", "evidence_level": "Other",
         "title": "A randomized study of adult clinical outcomes", "abstract": "Adults were assessed for clinical outcomes. " * 10},
        {"id": "pmid:2", "study_type": "Journal Article", "evidence_level": "Other",
         "title": "Another study of adult clinical outcomes", "abstract": "Adults were followed for clinical outcomes. " * 10},
    ]))
    return source, collection, metadata


def test_candidate_preserves_source_and_does_not_label_wrong_pdf_as_fulltext(tmp_path):
    prepare = candidate_builder()
    source, collection, metadata = fixture_inputs(tmp_path)
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    output = tmp_path / "candidate"
    result = prepare(source, collection, metadata, output)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    manifest = json.loads((output / "corpus.manifest.json").read_text())
    records = {row["canonical_source_id"]: row for row in manifest["records"]}
    assert records["pmid:1"]["content_status"] == "full_text"
    assert records["pmid:1"]["evidence_level"] == "RCT"
    assert records["pmid:1"]["identity_status"] == "verified_title"
    assert records["pmid:2"]["content_status"] == "abstract_fallback"
    assert records["pmid:2"]["pdf_identity_status"] == "unverified"
    assert records["pmid:2"]["disposition"] == "abstract_fallback"
    assert records["pmid:2"]["authorization"] == "unknown"
    for row in records.values():
        assert len(row["file_sha256"]) == 64
        assert len(row["metadata_sha256"]) == 64
        assert row["parser_version"]
        assert row["classification_basis"]
    assert result["source_unchanged"] is True
    with sqlite3.connect(str(output / "corpus.sqlite3")) as connection:
        assert connection.execute("SELECT evidence_level FROM documents WHERE pmid='1'").fetchone()[0] == "RCT"
        assert connection.execute("SELECT extraction_status FROM documents WHERE pmid='2'").fetchone()[0] == "abstract_fallback"
        assert connection.execute("SELECT COUNT(*) FROM chunks WHERE doc_id='pmid:2'").fetchone()[0] == 1
    with pytest.raises(FileExistsError):
        prepare(source, collection, metadata, output)


def test_candidate_rejects_manifest_id_mismatch_without_touching_source(tmp_path):
    prepare = candidate_builder()
    source, collection, metadata = fixture_inputs(tmp_path)
    path = collection / "selected_manifest.csv"
    path.write_text(path.read_text().replace("2,Another", "3,Another"))
    with pytest.raises(ValueError, match="manifest.*index"):
        prepare(source, collection, metadata, tmp_path / "candidate")


@pytest.mark.parametrize("citation_page", [1, 2])
def test_cited_title_in_wrong_pdf_never_verifies_article_identity(tmp_path, citation_page):
    prepare = candidate_builder()
    source, collection, metadata = fixture_inputs(tmp_path)
    path = collection / "2.pdf"
    path.unlink()
    with pymupdf.open() as document:
        page = document.new_page()
        page.insert_textbox(pymupdf.Rect(40, 40, 550, 130),
                            "Unrelated article about astronomy and distant stars", fontsize=18)
        page.insert_textbox(pymupdf.Rect(40, 150, 550, 430),
                            "Abstract\nAstronomical observations of distant stars. " * 20, fontsize=10)
        if citation_page == 2:
            page = document.new_page()
        page.insert_text((40, 470), "References", fontsize=16)
        page.insert_text((40, 500), "Another study of adult clinical outcomes", fontsize=10)
        document.save(str(path))
    output = tmp_path / "candidate"
    prepare(source, collection, metadata, output)
    records = json.loads((output / "corpus.manifest.json").read_text())["records"]
    cited = next(row for row in records if row["canonical_source_id"] == "pmid:2")
    assert cited["content_status"] == "abstract_fallback"
    assert cited["pdf_identity_status"] == "unverified"
    assert cited["identity_status"] != "verified_title"
