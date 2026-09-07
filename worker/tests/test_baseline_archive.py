import io
import os
import tarfile
import tempfile
import unittest
from pathlib import Path

from worker.ctxbench_worker.runtime import extract_baseline, git, seal


class BaselineArchiveTests(unittest.TestCase):
    def archive(self, entries):
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode='w') as tar:
            for name, kind, content in entries:
                member = tarfile.TarInfo(name)
                member.type = kind
                if kind == tarfile.REGTYPE:
                    member.size = len(content.encode())
                    tar.addfile(member, io.BytesIO(content.encode()))
                else:
                    member.linkname = content
                    tar.addfile(member)
        buffer.seek(0)
        return tarfile.open(fileobj=buffer)

    def test_absolute_and_dangling_git_symlinks_are_preserved_as_leaf_links(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            try:
                (root / 'probe').symlink_to('/does-not-exist')
                (root / 'probe').unlink()
            except OSError:
                self.skipTest('OS does not permit unprivileged symlinks')
            with self.archive([('extra/kfd.h', tarfile.SYMTYPE, '/usr/include/kfd.h'),
                               ('source.py', tarfile.REGTYPE, 'baseline'),
                               ('relative', tarfile.SYMTYPE, '../missing')]) as tar:
                extract_baseline(tar, root)
            self.assertEqual(os.readlink(root / 'extra/kfd.h'), '/usr/include/kfd.h')
            self.assertEqual(os.readlink(root / 'relative'), '../missing')
            seal(root)
            self.assertEqual(git(root, 'show', 'HEAD:extra/kfd.h'), b'/usr/include/kfd.h')

    def test_archive_escape_and_link_parent_are_rejected_before_writes(self):
        for entries in ([('../escape', tarfile.REGTYPE, 'bad')], [('/escape', tarfile.REGTYPE, 'bad')],
                        [('.git/config', tarfile.REGTYPE, 'bad')], [('hard', tarfile.LNKTYPE, '/escape')],
                        [('folder', tarfile.SYMTYPE, '/escape'), ('folder/file', tarfile.REGTYPE, 'bad')],
                        [('same', tarfile.REGTYPE, 'first'), ('same', tarfile.REGTYPE, 'second')],
                        [('device', tarfile.CHRTYPE, '')]):
            with self.subTest(entries=entries), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                with self.archive(entries) as tar, self.assertRaises(ValueError):
                    extract_baseline(tar, root)
                self.assertEqual(list(root.iterdir()), [])
