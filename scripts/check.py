"""Validate the crater-skill package offline without an account, network, or GPU."""
from pathlib import Path
import re

MAX_SKILL_LINES = 300

root = Path(__file__).resolve().parents[1]
entry = root / 'SKILL.md'
references = sorted((root / 'references').glob('*.md'))
watch_script = root / 'scripts/watch.py'

if not entry.is_file():
    raise SystemExit('Missing root SKILL.md')
if not references:
    raise SystemExit('Expected at least one reference document under references/')
if not watch_script.is_file():
    raise SystemExit('Missing scripts/watch.py')

private_text = re.compile(
    r'-----BEGIN (?:OPENSSH |EC |RSA )?PRIVATE KEY-----|'
    r'\b(?:gh[pousr]_[A-Za-z0-9]{24,}|github_pat_[A-Za-z0-9_]{30,}|hf_[A-Za-z0-9]{24,})\b|'
    r'\beyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+|'
    r'https?://[^/\s]+:[^/@\s]+@|[?&](?:X-Amz-Signature|access_token)=|'
    r'/home/(?!<)[^/\s]+/|https?://(?:10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+)(?=[:/])'
)

markdown_docs = [entry, root / 'README.md', *references]
code_files = [*(root / 'scripts').glob('*.py'), *(root / 'tests').glob('*.py')]

for path in [*markdown_docs, *code_files]:
    text = path.read_text(encoding='utf-8')
    if path.resolve() != Path(__file__).resolve() and private_text.search(text):
        raise SystemExit(f'Review private material in {path.relative_to(root)}')

entry_text = entry.read_text(encoding='utf-8')
entry_lines = entry_text.splitlines()
if len(entry_lines) > MAX_SKILL_LINES:
    raise SystemExit(f'SKILL.md exceeds {MAX_SKILL_LINES} lines ({len(entry_lines)}); keep it concise')

fm = re.match(r'^---\n(.*?)\n---\n', entry_text, re.S)
if not fm:
    raise SystemExit('SKILL.md is missing YAML frontmatter')
fields = {}
for line in fm.group(1).splitlines():
    if ':' in line and not line.startswith(' '):
        key, val = line.split(':', 1)
        fields[key.strip()] = val.strip()
if fields.get('name') != 'crater-skill' or not fields.get('description'):
    raise SystemExit('SKILL.md frontmatter must declare name: crater-skill and a non-empty description')

entry_targets = set()
for doc in markdown_docs:
    text = doc.read_text(encoding='utf-8')
    for target in re.findall(r'\]\(([^)]+)\)', text):
        if target.startswith(('https://', 'http://', '#')):
            continue
        rel = target.split('#', 1)[0]
        if not rel:
            continue
        resolved = (doc.parent / rel).resolve()
        if not resolved.is_relative_to(root) or not resolved.is_file():
            raise SystemExit(f'Broken package link in {doc.relative_to(root)}: {target}')
        if doc == entry:
            entry_targets.add(resolved)

expected_direct = {p.resolve() for p in references} | {watch_script.resolve()}
missing_direct = expected_direct - entry_targets
if missing_direct:
    names = ', '.join(str(p.relative_to(root)) for p in sorted(missing_direct))
    raise SystemExit(f'Every reference and helper script must be linked 1-hop from SKILL.md; missing: {names}')

print(f'Validated crater-skill ({len(entry_lines)} lines, {len(references)} references, 1 watcher script)')
