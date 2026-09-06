from pathlib import Path

import pytest

from operations.disaster_recovery.rehearse import Rehearsal


@pytest.mark.parametrize('container,database', [
    ('production-postgres-1','production'),
    ('mranked-review-it-postgres-1','production'),
    ('mranked-review-it-postgres-1','fixture_it; DROP DATABASE production'),
    ('127.0.0.1:5432','fixture_it'),
])
def test_rehearsal_rejects_nonfixture_sources_before_docker(container: str, database: str, tmp_path: Path):
    with pytest.raises(ValueError):
        Rehearsal(container,database,tmp_path)


def test_rehearsal_resource_names_and_reports_never_contain_credentials(tmp_path: Path):
    rehearsal=Rehearsal('mranked-review-it-postgres-1','fixture_it',tmp_path)
    assert rehearsal.prefix.startswith('mranked-dr-')
    assert rehearsal.report['productionAcceptance'] is False
    assert len(set(rehearsal.passwords.values()))==len(rehearsal.passwords)
    assert all(secret not in str(rehearsal.report) for secret in rehearsal.passwords.values())


@pytest.mark.parametrize('standby',[False,True])
def test_restore_waits_for_exact_recovery_state_even_when_sql_is_already_available(tmp_path: Path,monkeypatch,standby: bool):
    rehearsal=Rehearsal('mranked-review-it-postgres-1','fixture_it',tmp_path)
    monkeypatch.setattr(rehearsal,'run',lambda *args,**kwargs:'')
    queries=[]
    answers=iter(['f','f','t'])
    def query(container,statement):
        queries.append(statement)
        return next(answers)
    def wait(predicate,label):
        assert 'recovery-state readiness' in label
        assert not predicate()  # Connection is available; recovery has not reached its target.
        assert not predicate()
        assert predicate()
    monkeypatch.setattr(rehearsal,'query',query)
    monkeypatch.setattr(rehearsal,'wait',wait)
    rehearsal.start_restore('standby' if standby else 'pitr','own-data','own-wal',standby=standby)
    assert len(queries)==3
    assert all("pg_is_in_recovery()" in statement for statement in queries)
    assert all(("NOT pg_is_in_recovery()" in statement)==(not standby) for statement in queries)
    assert all(("transaction_read_only')='on'" in statement)==standby for statement in queries)
