from wiki_engine import slugify


def test_lowercases_and_hyphenates_spaces():
    assert slugify("Acme Renewal Terms") == "acme-renewal-terms"


def test_collapses_punctuation_runs_into_single_hyphen():
    assert slugify("Q3  Pipeline:  Watchdog!!") == "q3-pipeline-watchdog"


def test_trims_leading_and_trailing_separators():
    assert slugify("  /Follow-Up/  ") == "follow-up"


def test_empty_after_stripping_returns_empty_string():
    assert slugify("   ---   ") == ""
