from pathlib import Path
import hashlib
import xml.etree.ElementTree as ET
import sys
import pytest

from migration.integration.evidence import retain_spring_junit


def test_retained_junit_preserves_outcomes_and_redacts_environment_and_diagnostics(tmp_path):
    source=tmp_path/'backend-build/surefire-reports'
    source.mkdir(parents=True)
    raw=b'''<testsuite tests="2" failures="1" skipped="1"><properties><property name="arbitrary" value="hidden-environment"/></properties>
    <testcase name="failed" time="1.2"><failure message="password=secret-password">opaque-key redis://user:redis-secret@host/0 Authorization: Bearer header-secret</failure></testcase>
    <testcase name="optional"><skipped message="no service configured"/></testcase></testsuite>'''
    (source/'TEST-example.xml').write_bytes(raw)
    report=retain_spring_junit(tmp_path, ['opaque-key'])
    retained=(tmp_path/'spring-junit/TEST-example.xml').read_text()
    for value in ('hidden-environment','secret-password','opaque-key','redis-secret','header-secret'):
        assert value not in retained
    tree=ET.fromstring(retained)
    assert tree.find('.//testcase').get('time')=='1.2'
    assert len(list(tree.iter('failure')))==1 and len(list(tree.iter('skipped')))==1
    assert report['files'][0]['sourceSha256']==hashlib.sha256(raw).hexdigest()
    assert {key:report['files'][0][key] for key in ('tests','failures','errors','skipped')}==dict(tests=2,failures=1,errors=0,skipped=1)
    assert (source/'TEST-example.xml').read_bytes()==raw


def test_retention_can_add_later_query_plan_result_without_losing_spring_cases(tmp_path):
    source=tmp_path/'backend-build/surefire-reports'
    source.mkdir(parents=True)
    (source/'TEST-spring.xml').write_text('<testsuite><testcase name="a"/></testsuite>')
    first=retain_spring_junit(tmp_path)
    (source/'TEST-plans.xml').write_text('<testsuite><testcase name="plan"/></testsuite>')
    second=retain_spring_junit(tmp_path)
    assert len(second['files'])==2
    assert next(row for row in second['files'] if row['file']=='TEST-spring.xml')==first['files'][0]


def test_failed_spring_command_retains_diagnostics_before_raising(tmp_path):
    from migration.integration.run import Gate
    gate=Gate(tmp_path)
    gate.secrets={'TEST_PASSWORD':'opaque-secret'}
    source=tmp_path/'backend-build/surefire-reports'
    source.mkdir(parents=True)
    (source/'TEST-failed.xml').write_text('<testsuite><testcase name="a"><failure>opaque-secret</failure></testcase></testsuite>')
    with pytest.raises(RuntimeError,match='spring failed'):
        gate.command('spring',[sys.executable,'-c','raise SystemExit(1)'])
    assert 'opaque-secret' not in (tmp_path/'spring-junit/TEST-failed.xml').read_text()
    assert gate.results[-1]['exitCode']==1


def test_private_temp_root_is_used_for_pytest_without_lengthening_browser_ipc_paths(tmp_path):
    from migration.integration.run import Gate
    gate = Gate(tmp_path / 'evidence')
    private = tmp_path / 'private-provenance-runtime'
    private.mkdir(mode=0o700)
    gate.pytest_tmpdir = str(private)
    probe = tmp_path / 'test_temp_probe.py'
    probe.write_text(
        'import os, tempfile\nfrom pathlib import Path\n'
        'def test_root():\n'
        '    assert Path(tempfile.gettempdir()).resolve() == Path(os.environ["EXPECTED_TEMP"]).resolve()\n'
    )
    env = {'EXPECTED_TEMP': str(private)}
    gate.command('python-probe', [sys.executable, '-m', 'pytest', '-q', str(probe)], env=env)
    # Non-pytest children (Node, Playwright, Java) keep their normal short temp
    # root; Unix-domain socket paths have a much smaller limit than file paths.
    gate.command('browser-probe', [sys.executable, '-c',
        'import os,tempfile; assert tempfile.gettempdir() != os.environ["EXPECTED_TEMP"]'], env=env)
    assert [result['exitCode'] for result in gate.results] == [0, 0]
