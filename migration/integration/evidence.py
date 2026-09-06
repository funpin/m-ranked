"""Retain verifiable, sanitized JUnit evidence outside the disposable build tree."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET


def retain_spring_junit(output: Path, secret_values=()) -> dict:
    output = Path(output)
    source = output / 'backend-build/surefire-reports'
    destination = output / 'spring-junit'
    paths = sorted(source.glob('TEST-*.xml'))
    if not paths:
        raise ValueError('no Spring JUnit XML to retain')
    known = tuple(sorted({str(value) for value in secret_values if value}, key=len, reverse=True))

    def redact(value):
        if value is None:
            return None
        for secret in known:
            value = value.replace(secret, '[redacted]')
        value = re.sub(r'(?i)([a-z][a-z0-9+.-]*://)[^\s/@:]+:[^\s/@]+@', r'\1[redacted]@', value)
        value = re.sub(r'''(?ix)(\b(?:password|passwd|pwd|pgpassword|rediscli_auth|[a-z_]*secret|[a-z_]*token)\s*[=:]\s*)(?:"[^"\r\n]*"|'[^'\r\n]*'|[^\s,;&<]+)''', r'\1[redacted]', value)
        value = re.sub(r'(?i)(authorization\s*[:=]\s*)(?:basic|bearer)\s+[^\s<]+', r'\1[redacted]', value)
        return value

    destination.mkdir(parents=True, exist_ok=True)
    inventory = []
    for path in paths:
        original = path.read_bytes()
        tree = ET.fromstring(original)
        # JVM properties can contain arbitrary environment/credential values.
        # Test identities, outcomes, durations and diagnostics remain intact.
        removed = 0
        for parent in tree.iter():
            for child in list(parent):
                if child.tag == 'properties':
                    parent.remove(child)
                    removed += 1
        for node in tree.iter():
            node.text, node.tail = redact(node.text), redact(node.tail)
            for key, value in node.attrib.items():
                node.set(key, redact(value))
        sanitized = ET.tostring(tree, encoding='utf-8', xml_declaration=True)
        target = destination / path.name
        target.write_bytes(sanitized)
        cases = list(tree.iter('testcase'))
        inventory.append({'file': path.name, 'sourceSha256': hashlib.sha256(original).hexdigest(),
            'sha256': hashlib.sha256(sanitized).hexdigest(), 'jvmPropertySectionsRemoved': removed,
            'tests': len(cases), 'failures': sum(case.find('failure') is not None for case in cases),
            'errors': sum(case.find('error') is not None for case in cases),
            'skipped': sum(case.find('skipped') is not None for case in cases)})
    report = {'reportVersion': 1, 'retainedAt': datetime.now(timezone.utc).isoformat(),
              'source': 'backend-build/surefire-reports', 'destination': 'spring-junit',
              'sanitization': {'knownSecretValuesSupplied': len(known), 'jvmPropertiesRemoved': True,
                               'structuredCredentialsRedacted': True}, 'files': inventory}
    (destination/'manifest.json').write_text(json.dumps(report, indent=2)+'\n')
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--secrets-file', type=Path)
    args = parser.parse_args()
    secrets = []
    if args.secrets_file:
        secrets = [line.split('=', 1)[1] for line in args.secrets_file.read_text().splitlines()
                   if '=' in line and any(word in line.split('=', 1)[0] for word in ('PASSWORD', 'SECRET', 'TOKEN'))]
    report = retain_spring_junit(args.output, secrets)
    print(f'Retained {len(report["files"])} sanitized JUnit XML files')


if __name__ == '__main__':
    main()
