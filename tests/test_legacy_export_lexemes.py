import json
from migration.bridge.export_lexemes import representation


def test_safe_raw_json_is_preserved_as_exact_text_and_counters_are_not_duplicated():
    raw = '{ "z": [1, null], "a": "Привет,\\r\\n\\\"мир\\\"" }'
    fields, reason = representation("platform_snapshots", {"raw_json":raw,"age_seconds":1,"views_count":0})
    assert fields["raw_json"] == raw
    assert fields["age_hours"] == str(1/3600.0)
    assert "views_count" not in fields
    assert reason is None


def test_secrets_and_invalid_raw_are_classified_without_plaintext_storage():
    for raw, expected in [(json.dumps({"nested":{"access_token":"dont-store-me"}}),"UNSAFE_RAW_JSON"),
                          ('{"broken": dont-store-me}',"UNPARSEABLE_RAW_JSON")]:
        fields, reason = representation("platform_snapshots", {"raw_json":raw})
        assert reason == expected
        assert fields["raw_json"] is None
        assert len(fields["raw_json_sha256"]) == 64
        assert "dont-store-me" not in json.dumps(fields)


def test_legacy_deltas_nulls_zero_and_reaction_order_are_explicit_representation_fields():
    raw = '{"👍": 0, "❤": 2}'
    fields, reason = representation("reaction_snapshots", {"delta_total":-2,"delta_views":0,"delta_comments":None,"reactions_json":raw})
    assert fields == {"measured_at":None,"reactions_json":raw,"delta_total":-2,"delta_views":0,"delta_comments":None}
    assert reason is None
