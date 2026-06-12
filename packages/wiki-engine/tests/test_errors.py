from wiki_engine import IngestError, SchemaError, WikiError


def test_specific_errors_subclass_wiki_error():
    assert issubclass(IngestError, WikiError)
    assert issubclass(SchemaError, WikiError)


def test_slugify_still_importable_from_package_root():
    from wiki_engine import slugify

    assert slugify("Acme Renewal") == "acme-renewal"
