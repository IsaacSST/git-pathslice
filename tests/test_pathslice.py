"""Scenario tests for git-pathslice.  Run with: python3 -m unittest discover -s tests -v"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SLICE = os.path.join(os.path.dirname(HERE), "git-pathslice")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="gitpathslice-")
        env = {k: v for k, v in os.environ.items()
               if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_PREFIX")}
        env.update({
            "HOME": self.tmp, "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "Dev", "GIT_AUTHOR_EMAIL": "dev@example.com",
            "GIT_COMMITTER_NAME": "Dev", "GIT_COMMITTER_EMAIL": "dev@example.com",
        })
        self.env = env
        self.repo = os.path.join(self.tmp, "repo")
        os.makedirs(self.repo)
        self.git("init", "-q", "-b", "main")
        self.commit("init", {"docs/index.md": "intro\n", "docs/old.md": "old page\n", "src/a.py": "x=1\n"})

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # helpers ------------------------------------------------------------
    def git(self, *args, cwd=None, input=None, check=True, binary=False):
        p = subprocess.run(["git", *args], cwd=cwd or self.repo, env=self.env,
                           input=input if binary or input is None else input.encode(),
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if check and p.returncode != 0:
            raise AssertionError("git %s failed: %s" % (" ".join(args), p.stderr.decode()))
        return p.stdout if binary else p.stdout.decode()

    def slice(self, *args, cwd=None, check=True):
        p = subprocess.run([sys.executable, SLICE, *args], cwd=cwd or self.repo, env=self.env,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if check and p.returncode != 0:
            raise AssertionError("git pathslice %s failed (rc %d):\n%s\n%s" % (" ".join(args), p.returncode, p.stdout, p.stderr))
        return p

    def write(self, files):
        for path, content in files.items():
            full = os.path.join(self.repo, path)
            if content is None:
                self.git("rm", "-q", path)
                continue
            os.makedirs(os.path.dirname(full), exist_ok=True)
            mode = "wb" if isinstance(content, bytes) else "w"
            with open(full, mode) as f:
                f.write(content)

    def commit(self, msg, files, author=None):
        self.write(files)
        self.git("add", "-A")
        args = ["commit", "-q", "-m", msg]
        if author:
            args += ["--author", author]
        self.git(*args)
        return self.sha("HEAD")

    def sha(self, rev):
        return self.git("rev-parse", "--verify", rev + "^{commit}").strip()

    def show(self, rev, path, binary=False):
        return self.git("show", "%s:%s" % (rev, path), binary=binary)

    def exists(self, rev, path):
        p = subprocess.run(["git", "cat-file", "-e", "%s:%s" % (rev, path)], cwd=self.repo, env=self.env,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return p.returncode == 0

    def count(self, a, b):
        return int(self.git("rev-list", "--count", "%s..%s" % (a, b)).strip())

    def subjects(self, a, b):
        return self.git("log", "--reverse", "--format=%s", "%s..%s" % (a, b)).splitlines()

    def state_files(self):
        root = os.path.join(self.repo, ".git", "pathslice", "state")
        found = []
        for d, _, fs in os.walk(root):
            found += [os.path.join(d, f) for f in fs]
        return found

    def worktrees(self):
        return [l for l in self.git("worktree", "list", "--porcelain").splitlines() if l.startswith("worktree ")]

    def standard_dev(self):
        """dev: docs-only, mixed (+feature, -old, index edit, code), code-only.  main: own docs change."""
        self.git("switch", "-q", "-c", "dev")
        self.d1 = self.commit("docs: clarify intro", {"docs/index.md": "intro, clarified\n"},
                              author="Other <other@example.com>")
        self.d2 = self.commit("feat: thing + docs", {"src/a.py": "x=2\n", "docs/feature.md": "new feature page\n",
                                                     "docs/old.md": None, "docs/index.md": "intro, clarified, more\n"})
        self.d3 = self.commit("code only", {"src/a.py": "x=2\ny=3\n"})
        self.git("switch", "-q", "main")
        self.m1 = self.commit("main docs change", {"docs/changelog.md": "changelog\n"})
        self.slice("add", "docs", "docs/", "--base", "main")

    def assert_standard_result(self, branch="pathslice/docs/dev"):
        self.assertEqual(self.count("main", branch), 2)
        self.assertEqual(self.subjects("main", branch), ["docs: clarify intro", "feat: thing + docs"])
        self.assertEqual(self.show(branch, "src/a.py"), "x=1\n")
        self.assertEqual(self.show(branch, "docs/index.md"), "intro, clarified, more\n")
        self.assertTrue(self.exists(branch, "docs/feature.md"))
        self.assertTrue(self.exists(branch, "docs/changelog.md"))
        self.assertFalse(self.exists(branch, "docs/old.md"))


class TestUpdate(Base):
    def test_basic(self):
        self.standard_dev()
        out = self.slice("update", "docs", "--from", "dev").stdout
        self.assertIn("pathslice/docs/dev: main + 2 commits", out)
        self.assert_standard_result()
        body = self.git("log", "-1", "--format=%B", "pathslice/docs/dev~1")
        self.assertIn("Sliced-From: " + self.d1, body)
        self.assertEqual(self.git("log", "-1", "--format=%an", "pathslice/docs/dev~1").strip(), "Other")
        self.assertEqual(self.sha("refs/pathslices/docs/dev/source"), self.d3)
        self.assertEqual(len(self.worktrees()), 1)
        self.assertEqual(self.state_files(), [])
        # the user's checkout is untouched
        self.assertEqual(self.git("symbolic-ref", "--short", "HEAD").strip(), "main")
        self.assertEqual(self.git("status", "--porcelain"), "")

    def test_rerun_is_stable(self):
        """Rebuilding with nothing changed must reproduce the same commit ids,
        so there is nothing to force-push and no pull-request churn."""
        self.standard_dev()
        self.slice("update", "docs", "--from", "dev")
        first = self.sha("pathslice/docs/dev")
        self.slice("update", "docs", "--from", "dev")
        self.assert_standard_result()
        self.assertEqual(self.sha("pathslice/docs/dev"), first)

    def test_rebuild_is_committer_independent(self):
        """A rebuild by someone else (or by CI) yields the same commit ids."""
        self.standard_dev()
        self.slice("update", "docs", "--from", "dev")
        first = self.sha("pathslice/docs/dev")
        self.git("branch", "-D", "pathslice/docs/dev")
        self.slice("forget", "docs", "--from", "dev")
        self.env.update({"GIT_COMMITTER_NAME": "CI", "GIT_COMMITTER_EMAIL": "ci@example.com",
                         "GIT_AUTHOR_NAME": "CI", "GIT_AUTHOR_EMAIL": "ci@example.com"})
        self.slice("update", "docs", "--from", "dev")
        self.assertEqual(self.sha("pathslice/docs/dev"), first)

    def test_default_from_is_current_branch(self):
        self.standard_dev()
        self.git("switch", "-q", "dev")
        self.slice("update", "docs")
        self.assert_standard_result()

    def test_nothing_pending(self):
        self.git("switch", "-q", "-c", "dev")
        self.commit("code only", {"src/a.py": "x=2\n"})
        self.git("switch", "-q", "main")
        self.slice("add", "docs", "docs/", "--base", "main")
        out = self.slice("update", "docs", "--from", "dev").stdout
        self.assertIn("main + 0 commits", out)
        self.assertEqual(self.sha("pathslice/docs/dev"), self.sha("main"))

    def test_run_from_subdirectory(self):
        self.standard_dev()
        out = self.slice("log", "docs", "--from", "dev", cwd=os.path.join(self.repo, "src")).stdout
        self.assertIn("pending: 2 commits", out)
        self.slice("update", "docs", "--from", "dev", cwd=os.path.join(self.repo, "src"))
        self.assert_standard_result()

    def test_binary_file(self):
        png = b"\x89PNG\r\n\x1a\n\x00\x01\x02\xff\xfe\x00"
        self.git("switch", "-q", "-c", "dev")
        self.commit("docs: add image", {"docs/img.png": png})
        self.git("switch", "-q", "main")
        self.slice("add", "docs", "docs/", "--base", "main")
        self.slice("update", "docs", "--from", "dev")
        self.assertEqual(self.show("pathslice/docs/dev", "docs/img.png", binary=True), png)

    def test_message_body_preserved(self):
        self.git("switch", "-q", "-c", "dev")
        msg = "docs: clarify\n\n# not a comment\n\nSecond paragraph.\n"
        self.commit(msg, {"docs/index.md": "intro, clarified\n"})
        self.git("switch", "-q", "main")
        self.slice("add", "docs", "docs/", "--base", "main")
        self.slice("update", "docs", "--from", "dev")
        body = self.git("log", "-1", "--format=%B", "pathslice/docs/dev")
        self.assertTrue(body.startswith(msg.rstrip("\n")), body)
        self.assertIn("Sliced-From:", body)

    def test_checked_out_branch_is_refused(self):
        self.standard_dev()
        self.slice("update", "docs", "--from", "dev")
        self.git("worktree", "add", "-q", os.path.join(self.tmp, "other"), "pathslice/docs/dev")
        p = self.slice("update", "docs", "--from", "dev", check=False)
        self.assertEqual(p.returncode, 1)
        self.assertIn("checked out", p.stderr)

    def test_custom_branch_name(self):
        self.standard_dev()
        self.slice("update", "docs", "--from", "dev", "--branch", "docs/dev")
        self.assert_standard_result("docs/dev")


class TestLanding(Base):
    """After the derived branch lands in main, the next update must not replay it again."""

    def land_then_continue(self):
        self.git("switch", "-q", "dev")
        self.d4 = self.commit("docs: later note", {"docs/later.md": "later\n"})
        self.git("switch", "-q", "main")
        self.slice("update", "docs", "--from", "dev")
        self.assertEqual(self.subjects("main", "pathslice/docs/dev"), ["docs: later note"])
        self.assertTrue(self.exists("pathslice/docs/dev", "docs/feature.md"))

    def test_merge_commit(self):
        self.standard_dev()
        self.slice("update", "docs", "--from", "dev")
        self.git("merge", "-q", "--no-ff", "--no-edit", "pathslice/docs/dev")
        self.land_then_continue()
        self.assertEqual(self.sha("refs/pathslices/docs/dev/landed"), self.d3)

    def test_merge_commit_without_state_uses_trailers(self):
        self.standard_dev()
        self.slice("update", "docs", "--from", "dev")
        self.git("merge", "-q", "--no-ff", "--no-edit", "pathslice/docs/dev")
        self.slice("forget", "docs", "--from", "dev")
        out = self.slice("log", "docs", "--from", "dev").stdout
        self.assertEqual(out.count("landed (trailer)"), 2)
        self.land_then_continue()

    def test_squash(self):
        self.standard_dev()
        self.slice("update", "docs", "--from", "dev")
        self.git("merge", "-q", "--squash", "pathslice/docs/dev")
        self.git("commit", "-q", "-m", "Docs from dev (#1)")
        self.land_then_continue()

    def test_squash_then_more_docs_on_main(self):
        self.standard_dev()
        self.slice("update", "docs", "--from", "dev")
        self.git("merge", "-q", "--squash", "pathslice/docs/dev")
        self.git("commit", "-q", "-m", "Docs from dev (#1)")
        self.commit("main edits the same file again", {"docs/index.md": "intro, clarified, more, and main\n"})
        self.land_then_continue()
        self.assertEqual(self.show("pathslice/docs/dev", "docs/index.md"), "intro, clarified, more, and main\n")

    def test_rebase_merge_uses_patch_ids(self):
        self.standard_dev()
        self.slice("update", "docs", "--from", "dev")
        for c in self.git("rev-list", "--reverse", "main..pathslice/docs/dev").split():
            self.git("cherry-pick", "-n", c)
            self.git("commit", "-q", "-m", "landed without trailer")
        self.slice("forget", "docs", "--from", "dev")
        out = self.slice("log", "docs", "--from", "dev").stdout
        self.assertEqual(out.count("landed (patch-id)"), 2)
        self.land_then_continue()

    def test_merge_then_merge_back_into_dev(self):
        self.standard_dev()
        self.slice("update", "docs", "--from", "dev")
        self.git("merge", "-q", "--no-ff", "--no-edit", "pathslice/docs/dev")
        self.git("switch", "-q", "dev")
        self.git("merge", "-q", "--no-edit", "main")
        self.git("switch", "-q", "main")
        self.land_then_continue()

    def test_squash_then_merge_back_into_dev(self):
        self.standard_dev()
        self.slice("update", "docs", "--from", "dev")
        self.git("merge", "-q", "--squash", "pathslice/docs/dev")
        self.git("commit", "-q", "-m", "Docs from dev (#1)")
        self.git("switch", "-q", "dev")
        self.git("merge", "-q", "--no-edit", "main")
        self.git("switch", "-q", "main")
        self.land_then_continue()

    def test_source_rebased_before_landing(self):
        self.standard_dev()
        self.slice("update", "docs", "--from", "dev")
        self.commit("unrelated main change", {"src/b.py": "b=1\n"})
        self.git("switch", "-q", "dev")
        self.git("rebase", "-q", "main")
        self.git("switch", "-q", "main")
        self.slice("update", "docs", "--from", "dev")
        self.assert_standard_result()
        self.assertTrue(self.exists("pathslice/docs/dev", "src/b.py"))

    def test_manual_landed(self):
        self.standard_dev()
        # main already has d1's content, but in a commit whose patch differs, so patch ids do not match
        self.commit("hand-applied intro change", {"docs/index.md": "intro, clarified\n", "docs/changelog.md": "changelog 2\n"})
        self.slice("landed", "docs", self.d1, "--from", "dev")
        out = self.slice("log", "docs", "--from", "dev").stdout
        self.assertIn("pending: 1 commit", out)
        self.assertNotIn("docs: clarify intro", out)
        self.slice("update", "docs", "--from", "dev")
        self.assertEqual(self.subjects("main", "pathslice/docs/dev"), ["feat: thing + docs"])
        self.assertEqual(self.show("pathslice/docs/dev", "docs/index.md"), "intro, clarified, more\n")


class TestConflicts(Base):
    def conflicting_setup(self):
        self.git("switch", "-q", "-c", "dev")
        self.c1 = self.commit("docs: reword intro", {"docs/index.md": "intro, reworded on dev\n"})
        self.c2 = self.commit("docs: feature page", {"docs/feature.md": "feature\n"})
        self.git("switch", "-q", "main")
        self.commit("main rewords intro too", {"docs/index.md": "intro, reworded on main\n"})
        self.slice("add", "docs", "docs/", "--base", "main")
        p = self.slice("update", "docs", "--from", "dev", check=False)
        self.assertEqual(p.returncode, 1)
        self.assertIn("conflict while replaying", p.stderr)
        self.assertIn("docs: reword intro", p.stderr)
        self.wt = os.path.join(self.repo, ".git", "pathslice", "wt", "docs", "dev")
        self.assertTrue(os.path.isdir(self.wt))
        with open(os.path.join(self.wt, "docs", "index.md")) as f:
            self.assertIn("<<<<<<<", f.read())
        self.assertEqual(len(self.state_files()), 1)
        # the user's own checkout is untouched
        self.assertEqual(self.git("status", "--porcelain"), "")

    def test_continue(self):
        self.conflicting_setup()
        with open(os.path.join(self.wt, "docs", "index.md"), "w") as f:
            f.write("intro, reworded on both\n")
        self.git("add", "docs/index.md", cwd=self.wt)
        self.slice("continue", "docs", "--from", "dev")
        self.assertEqual(self.subjects("main", "pathslice/docs/dev"), ["docs: reword intro", "docs: feature page"])
        self.assertEqual(self.show("pathslice/docs/dev", "docs/index.md"), "intro, reworded on both\n")
        self.assertIn("Sliced-From: " + self.c1, self.git("log", "-1", "--format=%B", "pathslice/docs/dev~1"))
        self.assertFalse(os.path.exists(self.wt))
        self.assertEqual(self.state_files(), [])

    def test_continue_without_resolving_fails(self):
        self.conflicting_setup()
        p = self.slice("continue", "docs", "--from", "dev", check=False)
        self.assertEqual(p.returncode, 1)
        self.assertTrue(os.path.isdir(self.wt))

    def test_skip(self):
        self.conflicting_setup()
        self.slice("skip", "docs", "--from", "dev")
        self.assertEqual(self.subjects("main", "pathslice/docs/dev"), ["docs: feature page"])
        self.assertEqual(self.show("pathslice/docs/dev", "docs/index.md"), "intro, reworded on main\n")

    def test_abort(self):
        self.conflicting_setup()
        self.slice("abort", "docs", "--from", "dev")
        self.assertFalse(os.path.exists(self.wt))
        self.assertEqual(self.state_files(), [])
        self.assertEqual(len(self.worktrees()), 1)
        p = subprocess.run(["git", "rev-parse", "--verify", "-q", "pathslice/docs/dev"], cwd=self.repo, env=self.env,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertNotEqual(p.returncode, 0)

    def test_update_refused_while_in_progress(self):
        self.conflicting_setup()
        p = self.slice("update", "docs", "--from", "dev", check=False)
        self.assertEqual(p.returncode, 1)
        self.assertIn("in progress", p.stderr)


class TestSelection(Base):
    def test_pure(self):
        self.standard_dev()
        self.slice("rm", "docs")
        self.slice("add", "docs", "docs/", "--base", "main", "--select", "pure")
        out = self.slice("log", "docs", "--from", "dev").stdout
        self.assertIn("skip (mixed)", out)
        self.slice("update", "docs", "--from", "dev")
        self.assertEqual(self.subjects("main", "pathslice/docs/dev"), ["docs: clarify intro"])
        self.slice("update", "docs", "--from", "dev", "--all")
        self.assert_standard_result()

    def test_marked(self):
        self.git("switch", "-q", "-c", "dev")
        self.commit("docs: clarify intro", {"docs/index.md": "intro, clarified\n"})
        self.commit("feat: thing + docs", {"src/a.py": "x=2\n", "docs/feature.md": "feature\n"})
        self.commit("update guide\n\nSlice: docs\n", {"docs/guide.md": "guide\n"})
        self.commit("more notes", {"docs/notes.md": "notes\n"})
        self.git("switch", "-q", "main")
        self.slice("add", "docs", "docs/", "--base", "main", "--select", "marked", "--subject", "^docs:")
        out = self.slice("log", "docs", "--from", "dev").stdout
        self.assertEqual(out.count("skip (unmarked)"), 2)
        self.slice("update", "docs", "--from", "dev")
        self.assertEqual(self.subjects("main", "pathslice/docs/dev"), ["docs: clarify intro", "update guide"])


class TestConfig(Base):
    def test_shared_definition(self):
        self.standard_dev()
        self.slice("rm", "docs")
        self.slice("add", "docs", "docs/", "--base", "main", "--select", "pure", "--shared")
        with open(os.path.join(self.repo, ".gitpathslices")) as f:
            content = f.read()
        self.assertIn('[pathslice "docs"]', content)
        self.assertIn("path = docs/", content)
        self.assertIn("[shared]", self.slice("list").stdout)
        self.slice("update", "docs", "--from", "dev")
        self.assertEqual(self.subjects("main", "pathslice/docs/dev"), ["docs: clarify intro"])
        self.slice("rm", "docs", "--shared")
        self.assertIn("no slices defined", self.slice("list").stdout)

    def test_multiple_paths_and_subdir_add(self):
        self.git("switch", "-q", "-c", "dev")
        self.commit("docs + readme", {"docs/index.md": "intro, clarified\n", "README.md": "readme\n", "src/a.py": "x=2\n"})
        self.git("switch", "-q", "main")
        self.slice("add", "docs", "docs/", "README.md", "--base", "main")
        self.slice("update", "docs", "--from", "dev")
        self.assertEqual(self.show("pathslice/docs/dev", "README.md"), "readme\n")
        self.assertEqual(self.show("pathslice/docs/dev", "docs/index.md"), "intro, clarified\n")
        self.assertEqual(self.show("pathslice/docs/dev", "src/a.py"), "x=1\n")

    def test_duplicate_add_refused(self):
        self.slice("add", "docs", "docs/")
        p = self.slice("add", "docs", "docs/", check=False)
        self.assertEqual(p.returncode, 1)
        self.assertIn("already defined", p.stderr)

    def test_status(self):
        self.standard_dev()
        out = self.slice("status", "--from", "dev").stdout
        self.assertIn("branch: not built yet", out)
        self.assertIn("pending: 2 commits", out)
        self.slice("update", "docs", "--from", "dev")
        out = self.slice("status", "--from", "dev").stdout
        self.assertIn("branch: 2 ahead of main", out)


class TestStability(Base):
    """A pull request under review must not be disturbed by unrelated movement on base."""

    def test_base_moves_branch_stands_still(self):
        self.standard_dev()
        self.slice("update", "docs", "--from", "dev")
        first = self.sha("pathslice/docs/dev")
        self.commit("main moves on", {"src/c.py": "c=1\n"})
        self.commit("main edits its own docs", {"docs/changelog.md": "changelog 2\n"})
        out = self.slice("update", "docs", "--from", "dev").stdout
        self.assertIn("unchanged", out)
        self.assertEqual(self.sha("pathslice/docs/dev"), first)

    def test_force_rebuild_moves_it(self):
        self.standard_dev()
        self.slice("update", "docs", "--from", "dev")
        first = self.sha("pathslice/docs/dev")
        self.commit("main moves on", {"src/c.py": "c=1\n"})
        self.slice("update", "docs", "--from", "dev", "--force-rebuild")
        self.assertNotEqual(self.sha("pathslice/docs/dev"), first)
        self.assertTrue(self.exists("pathslice/docs/dev", "src/c.py"))
        self.assert_standard_result()

    def test_new_source_commit_still_rebuilds(self):
        self.standard_dev()
        self.slice("update", "docs", "--from", "dev")
        self.git("switch", "-q", "dev")
        self.commit("docs: later note", {"docs/later.md": "later\n"})
        self.git("switch", "-q", "main")
        self.slice("update", "docs", "--from", "dev")
        self.assertEqual(self.subjects("main", "pathslice/docs/dev"),
                         ["docs: clarify intro", "feat: thing + docs", "docs: later note"])

    def test_warns_when_kept_branch_conflicts_with_base(self):
        self.standard_dev()
        self.slice("update", "docs", "--from", "dev")
        self.commit("main rewrites the same file", {"docs/index.md": "totally different\n"})
        p = self.slice("update", "docs", "--from", "dev")
        self.assertIn("unchanged", p.stdout)
        self.assertIn("no longer applies cleanly", p.stderr)


class TestPush(Base):
    def test_push_to_remote(self):
        bare = os.path.join(self.tmp, "remote.git")
        self.git("init", "-q", "--bare", bare)
        self.git("remote", "add", "origin", bare)
        self.git("push", "-q", "origin", "main")
        self.standard_dev()
        out = self.slice("update", "docs", "--from", "dev", "--push").stdout
        self.assertIn("pushed pathslice/docs/dev to origin", out)
        self.assertEqual(self.git("rev-parse", "pathslice/docs/dev", cwd=bare).strip(), self.sha("pathslice/docs/dev"))
        # nothing changed: no push at all, so the PR is not disturbed
        out = self.slice("update", "docs", "--from", "dev", "--push").stdout
        self.assertIn("already up to date on origin", out)
        # rebuilt branch is force-pushed
        self.git("switch", "-q", "dev")
        self.commit("docs: later note", {"docs/later.md": "later\n"})
        self.git("switch", "-q", "main")
        out = self.slice("update", "docs", "--from", "dev", "--push").stdout
        self.assertIn("pushed pathslice/docs/dev", out)
        self.assertEqual(self.git("rev-parse", "pathslice/docs/dev", cwd=bare).strip(), self.sha("pathslice/docs/dev"))


if __name__ == "__main__":
    unittest.main()
