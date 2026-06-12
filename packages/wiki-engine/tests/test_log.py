from wiki_engine.log import LogEntry, format_entry, parse_log, today


def test_format_entry_uses_parseable_prefix():
    entry = LogEntry(date="2026-06-04", op="ingest", title="Acme AB")
    assert format_entry(entry) == "## [2026-06-04] ingest | Acme AB"


def test_parse_log_round_trips_entries():
    text = "# Log\n\n## [2026-06-01] ingest | First\n\n## [2026-06-02] query | Second\n"
    assert parse_log(text) == [
        LogEntry("2026-06-01", "ingest", "First"),
        LogEntry("2026-06-02", "query", "Second"),
    ]


def test_parse_log_ignores_non_entry_lines():
    assert parse_log("# Log\n\njust prose\n") == []


def test_today_is_iso_date():
    value = today()
    assert len(value) == 10 and value[4] == "-" and value[7] == "-"
