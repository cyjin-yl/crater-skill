"""Expose the crater-skill Git checkout directly to SKILL.md consumers."""
import argparse
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--dest', type=Path, default=Path.home() / '.omp/agent/skills')
destination = parser.parse_args().dest.expanduser().resolve()
destination.mkdir(parents=True, exist_ok=True)

repo = Path(__file__).resolve().parents[1]
link = destination / 'crater-skill'

if (link.exists() or link.is_symlink()) and link.resolve() != repo:
    raise SystemExit(f'Existing skill would conflict: {link}')
if not link.is_symlink() or link.resolve() != repo:
    link.symlink_to(repo, target_is_directory=True)

# Clean up stale sub-skill symlinks from earlier multi-skill layouts of this repo.
old_skills_prefix = str(repo / 'skills') + '/'
pruned = 0
for item in destination.iterdir():
    if item == link or not item.is_symlink():
        continue
    raw_target = item.readlink()
    resolved = (item.parent / raw_target).resolve(strict=False)
    if str(resolved).startswith(old_skills_prefix) and not resolved.exists():
        item.unlink()
        pruned += 1

suffix = f' (pruned {pruned} obsolete sub-skill links)' if pruned else ''
print(f'crater-skill available in {destination}{suffix}')
