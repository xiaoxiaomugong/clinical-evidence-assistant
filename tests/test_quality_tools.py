from scripts.audit_corpus import audit
from scripts.lint_knowledge_pages import lint
from config import settings


def test_corpus_audit_reports_bundled_assets():
    report = audit(settings.pdf_index_path)

    assert report["bundled"]["knowledge_pages"] >= 5
    assert report["bundled"]["knowledge_claims"] >= 15
    assert "quality_gates" in report


def test_current_knowledge_pages_have_no_schema_errors():
    issues = lint(settings.knowledge_dir)

    assert not [issue for issue in issues if issue["level"] == "error"]
