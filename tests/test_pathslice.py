"""Git history scenarios for git-pathslice."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SLICE = os.path.join(os.path.dirname(HERE), "git-pathslice")
BRANCH = "pathslice/docs/dev"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="gitpathslice-")
        env = {k: v for k, v in os.environ.items()
               if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_PREFIX")}
        env.update({
            "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
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

    def git(self, *args, cwd=None, binary=False):
        p = subprocess.run(["git", *args], cwd=cwd or self.repo, env=self.env,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if p.returncode != 0:
            raise AssertionError("git %s failed: %s" % (" ".join(args), p.stderr.decode()))
        return p.stdout if binary else p.stdout.decode()

    def slice(self, *args, cwd=None, check=True):
        p = subprocess.run([sys.executable, SLICE, *args], cwd=cwd or self.repo, env=self.env,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if check and p.returncode != 0:
            raise AssertionError("git pathslice %s failed (rc %d):\n%s\n%s"
                                 % (" ".join(args), p.returncode, p.stdout, p.stderr))
        return p

    def write(self, files, cwd=None):
        for path, content in files.items():
            full = os.path.join(cwd or self.repo, path)
            if content is None:
                self.git("rm", "-q", path, cwd=cwd)
                continue
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "wb" if isinstance(content, bytes) else "w") as f:
                f.write(content)

    def commit(self, msg, files, cwd=None):
        self.write(files, cwd)
        self.git("add", "-A", cwd=cwd)
        self.git("commit", "-q", "-m", msg, cwd=cwd)
        return self.sha("HEAD", cwd)

    def merge(self, branch, resolve=None):
        """Merge branch into the current branch, resolving conflicts with the given contents."""
        p = subprocess.run(["git", "merge", "-q", "--no-ff", "--no-edit", branch], cwd=self.repo, env=self.env,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if p.returncode != 0:
            if resolve is None:
                raise AssertionError("merge of %s failed: %s" % (branch, p.stdout.decode()))
            self.commit("Merge %s" % branch, resolve)
        return self.sha("HEAD")

    def sha(self, rev, cwd=None):
        return self.git("rev-parse", "--verify", rev + "^{commit}", cwd=cwd).strip()

    def show(self, rev, path, binary=False):
        return self.git("show", "%s:%s" % (rev, path), binary=binary)

    def exists(self, rev, path):
        p = subprocess.run(["git", "cat-file", "-e", "%s:%s" % (rev, path)], cwd=self.repo, env=self.env,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return p.returncode == 0

    def proposed(self, branch, base="main"):
        """Files a pull request from branch into base would change."""
        return self.git("diff", "--name-only", "%s...%s" % (base, branch)).split()

    def switch(self, branch, create=False, start=None):
        self.git("switch", "-q", *(["-c", branch] + ([start] if start else []) if create else [branch]))

    def remote(self):
        bare = os.path.join(self.tmp, "remote.git")
        self.git("init", "-q", "--bare", "-b", "main", bare)
        self.git("remote", "add", "origin", bare)
        self.git("push", "-q", "origin", "main", "dev")
        return bare

    def clone(self, bare, name):
        other = os.path.join(self.tmp, name)
        self.git("clone", "-q", bare, other)
        return other

    def fake_gh(self):
        gh = os.path.join(self.tmp, "gh")
        calls = os.path.join(self.tmp, "gh-calls.jsonl")
        self.env.update({"PATH": self.tmp + os.pathsep + self.env["PATH"], "GH_TEST_CALLS": calls})
        with open(gh, "w") as f:
            f.write("#!" + sys.executable + "\n" + textwrap.dedent('''
                import json, os, pathlib, sys
                args = sys.argv[1:]
                calls = pathlib.Path(os.environ["GH_TEST_CALLS"])
                with calls.open("a") as out:
                    out.write(json.dumps(args) + "\\n")
                if os.environ.get("GH_TEST_FAIL"):
                    sys.stderr.write("service unavailable")
                    sys.exit(1)
                created = calls.with_suffix(".created")
                if args[:2] == ["pr", "create"]:
                    created.touch()
                if created.exists():
                    print("https://example.invalid/pull/1")
                '''))
        os.chmod(gh, 0o755)
        return calls

    def dev(self):
        """dev changes documentation and code; main gains an unrelated page."""
        self.switch("dev", create=True)
        self.commit("docs: clarify intro", {"docs/index.md": "intro, clarified\n"})
        self.commit("Add feature and documentation", {"src/a.py": "x=2\n", "docs/feature.md": "feature\n",
                                                      "docs/old.md": None})
        self.commit("code only", {"src/a.py": "x=3\n"})
        self.switch("main")
        self.commit("main docs change", {"docs/changelog.md": "changelog\n"})
        self.slice("add", "docs", "docs/", "--base", "main")

    def lineage(self):
        """feature is developed on dev, whose documentation is not yet on main."""
        self.switch("dev", create=True)
        self.commit("dev: code", {"src/a.py": "x=2\n"})
        self.commit("dev: document the interface", {"docs/api.md": "api\n"})
        self.switch("feature", create=True)
        self.commit("feature: code and documentation", {"src/b.py": "y=1\n", "docs/feature.md": "feature\n"})
        self.switch("main")
        self.slice("add", "docs", "docs/", "--base", "main", "--upstream", "dev")


class TestExport(Base):
    def test_mixed_commits_contribute_only_the_slice(self):
        self.dev()
        out = self.slice("update", "docs", "--from", "dev").stdout
        self.assertIn("%s: 3 files on main" % BRANCH, out)
        self.assertEqual(self.sha(BRANCH + "^"), self.sha("main"))
        self.assertEqual(self.show(BRANCH, "src/a.py"), "x=1\n")
        self.assertEqual(self.show(BRANCH, "docs/index.md"), "intro, clarified\n")
        self.assertTrue(self.exists(BRANCH, "docs/feature.md"))
        self.assertTrue(self.exists(BRANCH, "docs/changelog.md"))
        self.assertFalse(self.exists(BRANCH, "docs/old.md"))
        body = self.git("log", "-1", "--format=%B", BRANCH)
        self.assertIn("- docs: clarify intro", body)
        self.assertIn("- Add feature and documentation", body)
        self.assertNotIn("code only", body)
        self.assertIn("Pathslice-Source: dev " + self.sha("dev"), body)
        self.assertEqual(self.git("symbolic-ref", "--short", "HEAD").strip(), "main")
        self.assertEqual(self.git("status", "--porcelain"), "")

    def test_repeated_exports_are_stable_and_reproducible(self):
        self.dev()
        self.slice("update", "docs", "--from", "dev")
        first = self.sha(BRANCH)
        self.assertIn("is up to date", self.slice("update", "docs", "--from", "dev").stdout)
        self.assertEqual(self.sha(BRANCH), first)
        self.git("branch", "-D", BRANCH)
        self.env.update({"GIT_COMMITTER_NAME": "CI", "GIT_COMMITTER_EMAIL": "ci@example.com",
                         "GIT_AUTHOR_NAME": "CI", "GIT_AUTHOR_EMAIL": "ci@example.com"})
        self.slice("update", "docs", "--from", "dev")
        self.assertEqual(self.sha(BRANCH), first)

    def test_nothing_to_export(self):
        self.switch("dev", create=True)
        self.commit("code only", {"src/a.py": "x=2\n"})
        self.slice("add", "docs", "docs/", "--base", "main")
        self.assertIn("nothing to export", self.slice("update", "docs").stdout)
        self.assertEqual(self.git("branch", "--list", BRANCH), "")

    def test_binary_file(self):
        png = b"\x89PNG\r\n\x1a\n\x00\x01\x02\xff\xfe\x00"
        self.switch("dev", create=True)
        self.commit("docs: add image", {"docs/img.png": png})
        self.slice("add", "docs", "docs/", "--base", "main")
        self.slice("update", "docs")
        self.assertEqual(self.show(BRANCH, "docs/img.png", binary=True), png)

    def test_definition_is_read_from_the_source(self):
        self.switch("dev", create=True)
        self.slice("add", "docs", "docs/", "--base", "main", "--shared")
        self.commit("Define the documentation slice", {"docs/index.md": "intro, clarified\n"})
        self.switch("main")
        self.assertIn("no slices defined", self.slice("list").stdout)
        self.slice("update", "docs", "--from", "dev")
        self.assertEqual(self.proposed(BRANCH), ["docs/index.md"])

    def test_default_source_from_a_subdirectory(self):
        self.dev()
        self.switch("dev")
        src = os.path.join(self.repo, "src")
        self.assertIn("docs: clarify intro", self.slice("log", "docs", cwd=src).stdout)
        self.slice("update", "docs", cwd=src)
        self.assertEqual(self.proposed(BRANCH), ["docs/feature.md", "docs/index.md", "docs/old.md"])


class TestMeasurement(Base):
    def test_upstream_changes_are_not_exported(self):
        self.lineage()
        self.slice("update", "docs", "--from", "feature")
        branch = "pathslice/docs/feature"
        self.assertEqual(self.proposed(branch), ["docs/feature.md"])
        self.switch("dev")
        self.commit("dev: revise the interface", {"docs/api.md": "api v2\n"})
        self.switch("feature")
        self.merge("dev")
        self.switch("main")
        self.assertIn("is up to date", self.slice("update", "docs", "--from", "feature").stdout)
        self.assertEqual(self.proposed(branch), ["docs/feature.md"])

    def test_missing_upstream_is_reported(self):
        self.lineage()
        self.git("config", "--unset", "pathslice.docs.upstream")
        out = self.slice("status", "docs", "--from", "feature").stdout
        self.assertIn("feature shares commits with dev", out)
        self.assertIn("git config pathslice.docs.upstream BRANCH", out)
        self.assertIn("2 files to export", out)

    def test_merge_resolutions_are_exported(self):
        self.commit("Add the shared page", {"docs/shared.md": "original\n"})
        self.switch("dev", create=True)
        self.switch("feature", create=True)
        self.commit("feature: reword the shared page", {"docs/shared.md": "feature wording\n",
                                                        "docs/feature.md": "feature\n"})
        self.switch("main")
        self.commit("Agree the shared wording", {"docs/shared.md": "agreed wording\n"})
        self.switch("dev")
        self.merge("main")
        self.switch("feature")
        self.merge("dev", resolve={"docs/shared.md": "agreed wording\n"})
        self.switch("main")
        self.slice("add", "docs", "docs/", "--base", "main", "--upstream", "dev")
        self.slice("update", "docs", "--from", "feature")
        branch = "pathslice/docs/feature"
        self.assertEqual(self.proposed(branch), ["docs/feature.md"])
        self.assertEqual(self.show(branch, "docs/shared.md"), "agreed wording\n")

    def test_source_merged_into_its_upstream_keeps_its_export(self):
        self.lineage()
        self.slice("update", "docs", "--from", "feature")
        branch = "pathslice/docs/feature"
        exported = self.sha(branch)
        self.switch("dev")
        self.merge("feature")
        self.switch("main")
        self.assertIn("is up to date", self.slice("update", "docs", "--from", "feature").stdout)
        self.assertEqual(self.sha(branch), exported)
        self.assertEqual(self.proposed(branch), ["docs/feature.md"])

    def test_base_changes_merged_into_the_source_are_not_conflicts(self):
        self.commit("Add a page", {"docs/page.md": "one\ntwo\nX\nfour\nfive\n"})
        self.switch("dev", create=True)
        self.switch("feature", create=True)
        self.commit("feature: first line", {"docs/page.md": "ONE\ntwo\nX\nfour\nfive\n"})
        self.switch("main")
        self.commit("main: third line", {"docs/page.md": "one\ntwo\nY\nfour\nfive\n"})
        self.switch("feature")
        self.merge("main")
        self.switch("main")
        self.commit("main: third line again", {"docs/page.md": "one\ntwo\nZ\nfour\nfive\n"})
        self.slice("add", "docs", "docs/", "--base", "main", "--upstream", "dev")
        self.slice("update", "docs", "--from", "feature")
        self.assertEqual(self.show("pathslice/docs/feature", "docs/page.md"), "ONE\ntwo\nZ\nfour\nfive\n")

    def test_changes_already_on_the_base_are_not_exported(self):
        self.switch("dev", create=True)
        self.commit("docs: add a page", {"docs/page.md": "page\n"})
        self.switch("main")
        self.commit("docs: add a page (#12)", {"docs/page.md": "page\n"})
        self.slice("add", "docs", "docs/", "--base", "main")
        self.assertIn("nothing to export", self.slice("update", "docs", "--from", "dev").stdout)

    def test_conflicts_with_the_base_are_resolved_in_the_source(self):
        self.switch("dev", create=True)
        self.commit("docs: reword intro", {"docs/index.md": "dev intro\n"})
        self.switch("main")
        self.commit("docs: reword intro differently", {"docs/index.md": "main intro\n"})
        self.slice("add", "docs", "docs/", "--base", "main")
        p = self.slice("update", "docs", "--from", "dev", check=False)
        self.assertEqual(p.returncode, 1)
        self.assertIn("conflict with main in:\n  docs/index.md", p.stderr)
        self.assertIn("merge main into dev", p.stderr)
        self.switch("dev")
        self.merge("main", resolve={"docs/index.md": "resolved intro\n"})
        self.switch("main")
        self.slice("update", "docs", "--from", "dev")
        self.assertEqual(self.show(BRANCH, "docs/index.md"), "resolved intro\n")


class TestExportBranch(Base):
    def test_updates_are_added_to_the_branch(self):
        self.dev()
        self.slice("update", "docs", "--from", "dev")
        first = self.sha(BRANCH)
        self.switch("dev")
        self.commit("docs: later note", {"docs/later.md": "later\n"})
        self.switch("main")
        self.assertIn("1 file updated", self.slice("update", "docs", "--from", "dev").stdout)
        self.assertEqual(self.sha(BRANCH + "^"), first)
        body = self.git("log", "-1", "--format=%B", BRANCH)
        self.assertTrue(body.startswith("docs: update from dev\n\n- docs: later note ("), body)
        self.assertNotIn("clarify intro", body)

    def test_review_commits_are_kept_and_reported(self):
        self.dev()
        self.slice("update", "docs", "--from", "dev")
        self.switch(BRANCH)
        self.commit("Apply suggestion from review", {"docs/index.md": "intro, reviewed\n"})
        self.switch("dev")
        self.commit("docs: later note", {"docs/later.md": "later\n"})
        self.switch("main")
        out = self.slice("update", "docs", "--from", "dev").stdout
        self.assertIn("has changes that dev lacks in:\n  docs/index.md", out)
        self.assertEqual(self.show(BRANCH, "docs/index.md"), "intro, reviewed\n")
        self.assertTrue(self.exists(BRANCH, "docs/later.md"))
        updated = self.sha(BRANCH)
        self.assertIn("is up to date", self.slice("update", "docs", "--from", "dev").stdout)
        self.assertEqual(self.sha(BRANCH), updated)
        self.switch("dev")
        self.commit("docs: take the review suggestion", {"docs/index.md": "intro, reviewed\n"})
        self.switch("main")
        out = self.slice("update", "docs", "--from", "dev").stdout
        self.assertIn("is up to date", out)
        self.assertNotIn("lacks", out)

    def test_conflicting_review_commit_is_refused_until_rebuilt(self):
        self.dev()
        self.slice("update", "docs", "--from", "dev")
        self.switch(BRANCH)
        self.commit("Apply suggestion from review", {"docs/index.md": "review wording\n"})
        self.switch("dev")
        self.commit("docs: rewrite intro", {"docs/index.md": "intro, rewritten\n"})
        self.switch("main")
        p = self.slice("update", "docs", "--from", "dev", check=False)
        self.assertEqual(p.returncode, 1)
        self.assertIn("conflict with its new changes in:\n  docs/index.md", p.stderr)
        self.slice("update", "docs", "--from", "dev", "--rebuild")
        self.assertEqual(self.sha(BRANCH + "^"), self.sha("main"))
        self.assertEqual(self.show(BRANCH, "docs/index.md"), "intro, rewritten\n")

    def test_merged_export_starts_again_from_the_base(self):
        self.dev()
        self.slice("update", "docs", "--from", "dev")
        exported = self.sha(BRANCH)
        self.merge(BRANCH)
        self.assertIn("nothing to export", self.slice("update", "docs", "--from", "dev").stdout)
        self.assertEqual(self.sha(BRANCH), exported)
        self.switch("dev")
        self.commit("docs: later note", {"docs/later.md": "later\n"})
        self.switch("main")
        self.slice("update", "docs", "--from", "dev")
        self.assertEqual(self.sha(BRANCH + "^"), self.sha("main"))
        self.assertEqual(self.proposed(BRANCH), ["docs/later.md"])
        body = self.git("log", "-1", "--format=%B", BRANCH)
        self.assertIn("- docs: later note", body)
        self.assertNotIn("clarify intro", body)

    def test_squash_merged_export_starts_again_from_the_base(self):
        self.dev()
        self.slice("update", "docs", "--from", "dev")
        self.git("merge", "-q", "--squash", BRANCH)
        self.git("commit", "-q", "-m", "Documentation (#7)")
        self.assertIn("nothing to export", self.slice("update", "docs", "--from", "dev").stdout)
        self.switch("dev")
        self.commit("docs: later note", {"docs/later.md": "later\n"})
        self.switch("main")
        self.slice("update", "docs", "--from", "dev")
        self.assertEqual(self.sha(BRANCH + "^"), self.sha("main"))
        self.assertEqual(self.proposed(BRANCH), ["docs/later.md"])
        self.assertNotIn("clarify intro", self.git("log", "-1", "--format=%B", BRANCH))

    def test_base_changes_alone_leave_the_branch_unchanged(self):
        self.dev()
        self.slice("update", "docs", "--from", "dev")
        exported = self.sha(BRANCH)
        self.commit("main: another page", {"docs/another.md": "another\n"})
        self.assertIn("is up to date", self.slice("update", "docs", "--from", "dev").stdout)
        self.assertEqual(self.sha(BRANCH), exported)

    def test_branch_follows_a_newer_base_merged_into_the_source(self):
        self.dev()
        self.slice("update", "docs", "--from", "dev")
        exported = self.sha(BRANCH)
        self.commit("main: edit the changelog", {"docs/changelog.md": "changelog, edited\n"})
        self.switch("dev")
        self.merge("main")
        self.commit("docs: later note", {"docs/later.md": "later\n"})
        self.switch("main")
        self.assertIn("and follows main", self.slice("update", "docs", "--from", "dev").stdout)
        self.assertEqual(self.git("rev-list", "--parents", "-1", BRANCH).split()[1:], [exported, self.sha("main")])
        self.assertEqual(self.proposed(BRANCH), ["docs/feature.md", "docs/index.md", "docs/later.md", "docs/old.md"])
        self.assertEqual(self.show(BRANCH, "docs/changelog.md"), "changelog, edited\n")


class TestBranchSafety(Base):
    def test_checked_out_export_branch_is_refused(self):
        self.dev()
        self.slice("update", "docs", "--from", "dev")
        self.git("worktree", "add", "-q", os.path.join(self.tmp, "other"), BRANCH)
        self.switch("dev")
        self.commit("docs: later note", {"docs/later.md": "later\n"})
        self.switch("main")
        p = self.slice("update", "docs", "--from", "dev", check=False)
        self.assertEqual(p.returncode, 1)
        self.assertIn("checked out", p.stderr)

    def test_source_and_base_cannot_be_the_export_branch(self):
        self.dev()
        for name in ("dev", "main"):
            p = self.slice("update", "docs", "--from", "dev", "--branch", name, check=False)
            self.assertEqual(p.returncode, 1)
            self.assertIn("source or base branch", p.stderr)

    def test_ordinary_branch_is_not_taken_over(self):
        self.dev()
        self.git("branch", "notes", "dev~1")
        for extra in ([], ["--rebuild"]):
            p = self.slice("update", "docs", "--from", "dev", "--branch", "notes", *extra, check=False)
            self.assertEqual(p.returncode, 1)
            self.assertIn("is not an export of slice docs", p.stderr)
        self.assertEqual(self.sha("notes"), self.sha("dev~1"))

    def test_custom_branch_is_remembered_and_follows_renames(self):
        self.dev()
        self.slice("update", "docs", "--from", "dev", "--branch", "review/docs")
        self.switch("dev")
        self.commit("docs: later note", {"docs/later.md": "later\n"})
        self.slice("update", "docs")
        self.assertTrue(self.exists("review/docs", "docs/later.md"))
        self.git("branch", "-m", "review/docs", "review/specs")
        self.commit("docs: another note", {"docs/another.md": "another\n"})
        self.slice("update", "docs")
        self.assertTrue(self.exists("review/specs", "docs/another.md"))
        self.assertEqual(self.git("branch", "--list", "pathslice/*"), "")

    def test_export_made_by_version_0_2_is_continued(self):
        self.dev()
        source = self.sha("dev~1")
        self.switch("specs-export", create=True, start="main")
        self.commit("Add feature and documentation\n\nSliced-From: %s" % source,
                    {"docs/index.md": "intro, clarified\n", "docs/feature.md": "feature\n", "docs/old.md": None})
        legacy = self.sha("HEAD")
        self.switch("main")
        empty = self.git("hash-object", "-t", "tree", "-w", os.devnull).strip()
        record = json.dumps({"slice": "docs", "source_ref": "dev", "branch": "specs-export"})
        p = subprocess.run(["git", "commit-tree", empty, "-m", record], cwd=self.repo, env=self.env,
                           stdout=subprocess.PIPE, check=True)
        self.git("update-ref", "refs/pathslices/branches/specs-export", p.stdout.decode().strip())
        self.switch("dev")
        self.commit("docs: later note", {"docs/later.md": "later\n"})
        self.switch("main")
        self.slice("update", "docs", "--from", "dev")
        self.assertEqual(self.sha("specs-export^"), legacy)
        self.assertEqual(self.proposed("specs-export"),
                         ["docs/feature.md", "docs/index.md", "docs/later.md", "docs/old.md"])
        self.assertIn("- docs: later note", self.git("log", "-1", "--format=%B", "specs-export"))


class TestPublication(Base):
    def test_pushes_include_commits_added_on_the_remote(self):
        self.dev()
        bare = self.remote()
        self.assertIn("pushed %s to origin" % BRANCH, self.slice("update", "docs", "--from", "dev", "--push").stdout)
        reviewer = self.clone(bare, "reviewer")
        self.git("switch", "-q", BRANCH, cwd=reviewer)
        self.commit("Apply suggestion from review", {"docs/feature.md": "feature, reviewed\n"}, cwd=reviewer)
        self.git("push", "-q", "origin", BRANCH, cwd=reviewer)
        self.switch("dev")
        self.commit("docs: later note", {"docs/later.md": "later\n"})
        self.switch("main")
        self.git("fetch", "-q", "origin")
        self.slice("update", "docs", "--from", "dev", "--push")
        pushed = self.git("rev-parse", BRANCH, cwd=bare).strip()
        self.assertEqual(pushed, self.sha(BRANCH))
        self.assertEqual(self.git("show", "%s:docs/feature.md" % BRANCH, cwd=bare), "feature, reviewed\n")
        self.assertEqual(self.git("show", "%s:docs/later.md" % BRANCH, cwd=bare), "later\n")
        self.assertIn("already up to date", self.slice("update", "docs", "--from", "dev", "--push").stdout)

    def test_rebuild_does_not_replace_unseen_remote_commits(self):
        self.dev()
        bare = self.remote()
        self.slice("update", "docs", "--from", "dev", "--push")
        reviewer = self.clone(bare, "reviewer")
        self.git("switch", "-q", BRANCH, cwd=reviewer)
        self.commit("Apply suggestion from review", {"docs/feature.md": "feature, reviewed\n"}, cwd=reviewer)
        self.git("push", "-q", "origin", BRANCH, cwd=reviewer)
        reviewed = self.git("rev-parse", BRANCH, cwd=bare).strip()
        self.switch("dev")
        self.commit("docs: later note", {"docs/later.md": "later\n"})
        self.switch("main")
        p = self.slice("update", "docs", "--from", "dev", "--rebuild", "--push", check=False)
        self.assertNotEqual(p.returncode, 0)
        self.assertEqual(self.git("rev-parse", BRANCH, cwd=bare).strip(), reviewed)

    def test_publish_replaces_local_exports_with_the_remote_branch(self):
        self.dev()
        bare = self.remote()
        self.fake_gh()
        self.slice("update", "docs", "--from", "dev", "--push")
        reviewer = self.clone(bare, "reviewer")
        self.git("switch", "-q", BRANCH, cwd=reviewer)
        self.commit("Apply suggestion from review", {"docs/feature.md": "feature, reviewed\n"}, cwd=reviewer)
        self.git("push", "-q", "origin", BRANCH, cwd=reviewer)
        self.switch("dev")
        self.commit("docs: later note", {"docs/later.md": "later\n"})
        self.switch("main")
        self.slice("update", "docs", "--from", "dev")
        p = self.slice("publish", "docs", "--from", "dev")
        self.assertIn("replacing 1 local commit(s) made by git pathslice", p.stderr)
        self.assertEqual(self.git("show", "%s:docs/feature.md" % BRANCH, cwd=bare), "feature, reviewed\n")
        self.assertEqual(self.git("show", "%s:docs/later.md" % BRANCH, cwd=bare), "later\n")

    def test_publish_creates_then_reuses_the_pull_request(self):
        self.dev()
        bare = self.remote()
        calls = self.fake_gh()
        self.slice("publish", "docs", "--from", "dev", "--branch", "review/docs", "--draft")
        self.switch("dev")
        self.commit("docs: later note", {"docs/later.md": "later\n"})
        self.switch("main")
        self.assertIn("using existing PR", self.slice("pr", "docs", "--from", "dev").stdout)
        self.assertEqual(self.git("show", "review/docs:docs/later.md", cwd=bare), "later\n")
        self.env["GH_TEST_FAIL"] = "1"
        p = self.slice("publish", "docs", "--from", "dev", check=False)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("service unavailable", p.stderr)
        with open(calls) as f:
            commands = [json.loads(line) for line in f]
        created = [cmd for cmd in commands if cmd[:2] == ["pr", "create"]]
        self.assertEqual(len(created), 1)
        self.assertIn("--draft", created[0])


class TestInspection(Base):
    def test_status_and_log(self):
        self.dev()
        out = self.slice("status", "--from", "dev").stdout
        self.assertIn("slice docs: dev -> main  (branch %s)" % BRANCH, out)
        self.assertIn("branch: not created; 3 files to export", out)
        self.slice("update", "docs", "--from", "dev")
        self.assertIn("branch: up to date", self.slice("status", "docs", "--from", "dev").stdout)
        out = self.slice("log", "docs", "--from", "dev").stdout
        self.assertIn("source commits:", out)
        self.assertIn("docs: clarify intro", out)
        self.assertNotIn("code only", out)


if __name__ == "__main__":
    unittest.main()
