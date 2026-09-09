"""Bounded JUnit parsing; count testcase leaves once, never suite aggregates."""
import io
import re
import zipfile
import xml.etree.ElementTree as ET
from .ci_protocol import CIError


class NoDTD(ET.TreeBuilder):
    def doctype(self, *_):
        raise CIError('CI: XML entities and DTDs are not accepted in test reports.')


def junit_counts(archive):
    counts = {'total': 0, 'passed': 0, 'failures': 0, 'errors': 0, 'skipped': 0}
    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            files = bundle.infolist()
            if len(files) > 2000 or len({f.filename for f in files}) != len(files) or sum(f.file_size for f in files) > 32 * 1024 * 1024:
                raise CIError('CI: test report archive exceeds safety limits.')
            for member in files:
                if not member.filename.lower().endswith('.xml') or member.is_dir(): continue
                content = bundle.read(member)
                if re.search(br'<!\s*(DOCTYPE|ENTITY)', content, re.I):
                    raise CIError('CI: XML entities and DTDs are not accepted in test reports.')
                root = ET.fromstring(content, parser=ET.XMLParser(target=NoDTD()))
                if root.tag.split('}')[-1] not in {'testsuites', 'testsuite'}: continue
                for case in root.iter():
                    if case.tag.split('}')[-1] != 'testcase': continue
                    if counts['total'] >= 1_000_000: raise CIError('CI: too many test report entries.')
                    states = {child.tag.split('}')[-1] for child in case}
                    outcome = 'errors' if 'error' in states else 'failures' if 'failure' in states else 'skipped' if 'skipped' in states else 'passed'
                    counts['total'] += 1
                    counts[outcome] += 1
    except (zipfile.BadZipFile, ET.ParseError, RuntimeError, OSError, ValueError) as error:
        if isinstance(error, CIError): raise
        raise CIError('CI: invalid ZIP or JUnit XML report.') from None
    if not counts['total']: raise CIError('CI: the report contains no test cases; this is not a passing evaluation.')
    return counts
