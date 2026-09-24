"""Git history scenarios for git-pathslice."""
import hashlib
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
        self.clones = 0
        self.repo = os.path.join(self.tmp, "repo")
        os.makedirs(self.repo)
        self.git("init", "-q", "-b", "main")
        self.commit("init", {"docs/index.md": "intro\n", "docs/old.md": "old page\n", "src/a.py": "x=1\n"})

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def git(self, *args, cwd=None, binary=False, env=None):
        p = subprocess.run(["git", *args], cwd=cwd or self.repo, env=env or self.env,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if p.returncode != 0:
            raise AssertionError("git %s failed: %s" % (" ".join(args), p.stderr.decode()))
        return p.stdout if binary else p.stdout.decode()

    def slice(self, *args, cwd=None, check=True, env=None):
        p = subprocess.run([sys.executable, SLICE, *args], cwd=cwd or self.repo, env=env or self.env,
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

    def show(self, rev, path, binary=False, cwd=None):
        return self.git("show", "%s:%s" % (rev, path), binary=binary, cwd=cwd)

    def exists(self, rev, path):
        p = subprocess.run(["git", "cat-file", "-e", "%s:%s" % (rev, path)], cwd=self.repo, env=self.env,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return p.returncode == 0

    def proposed(self, branch, base="main"):
        """Files a pull request from branch into base would change."""
        return self.git("diff", "--name-only", "%s...%s" % (base, branch)).split()

    def switch(self, branch, create=False, start=None, cwd=None):
        self.git("switch", "-q", *(["-c", branch] + ([start] if start else []) if create else [branch]), cwd=cwd)

    def later(self, subject="docs: later note", files=None):
        """Commit a documentation change to dev and return to main."""
        self.switch("dev")
        self.commit(subject, files or {"docs/later.md": "later\n"})
        self.switch("main")

    def remote(self):
        bare = os.path.join(self.tmp, "remote.git")
        self.git("init", "-q", "--bare", "-b", "main", bare)
        self.git("remote", "add", "origin", bare)
        self.git("push", "-q", "origin", "main", "dev")
        return bare

    def clone(self, bare, *options):
        self.clones += 1
        other = os.path.join(self.tmp, "clone%d" % self.clones)
        self.git("clone", "-q", *options, bare, other)
        return other

    def review(self, bare, files):
        """Commit a review suggestion to the remote export branch from another clone."""
        reviewer = self.clone(bare)
        self.git("switch", "-q", BRANCH, cwd=reviewer)
        self.commit("Apply suggestion from review", files, cwd=reviewer)
        self.git("push", "-q", "origin", BRANCH, cwd=reviewer)
        return self.git("rev-parse", BRANCH, cwd=bare).strip()

    def legacy_record(self, branch, source_ref="dev", name="docs"):
        """Write a branch record as git pathslice 0.2 did."""
        empty = self.git("hash-object", "-t", "tree", "-w", os.devnull).strip()
        record = json.dumps({"slice": name, "source_ref": source_ref, "branch": branch})
        sha = self.git("commit-tree", empty, "-m", record).strip()
        self.git("update-ref", "refs/pathslices/branches/" + branch.replace("/", "%2F"), sha)

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

    def gh_calls(self, calls):
        with open(calls) as f:
            return [json.loads(line) for line in f]

    def without_gh(self):
        """The environment with gh removed from PATH."""
        tools = os.path.join(self.tmp, "without-gh")
        os.makedirs(tools)
        os.symlink(shutil.which("git", path=self.env["PATH"]), os.path.join(tools, "git"))
        dirs = [d for d in self.env["PATH"].split(os.pathsep) if not os.path.exists(os.path.join(d, "gh"))]
        return dict(self.env, PATH=os.pathsep.join([tools] + dirs))

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

    def lineage(self, upstream=True):
        """feature is developed on dev, whose documentation is not yet on main."""
        self.switch("dev", create=True)
        self.commit("dev: code", {"src/a.py": "x=2\n"})
        self.commit("dev: document the interface", {"docs/api.md": "api\n"})
        self.switch("feature", create=True)
        self.commit("feature: code and documentation", {"src/b.py": "y=1\n", "docs/feature.md": "feature\n"})
        self.switch("main")
        self.slice("add", "docs", "docs/", "--base", "main", *(["--upstream", "dev"] if upstream else []))


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
        for trailer in ("Pathslice-Source: dev " + self.sha("dev"), "Pathslice-Base: main", "Pathslice-Path: docs/"):
            self.assertIn(trailer, body)
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

    def test_old_commit_dates(self):
        self.switch("dev", create=True)
        self.env.update({"GIT_AUTHOR_DATE": "@70000000 +0000", "GIT_COMMITTER_DATE": "@70000000 +0000"})
        self.commit("docs: old note", {"docs/old.md": "old page, 1972\n"})
        for key in ("GIT_AUTHOR_DATE", "GIT_COMMITTER_DATE"):
            del self.env[key]
        self.slice("add", "docs", "docs/", "--base", "main")
        self.slice("update", "docs")
        self.assertEqual(self.git("log", "-1", "--format=%at", BRANCH).strip(), "70000000")

    def test_definition_is_read_from_the_source(self):
        self.switch("dev", create=True)
        self.slice("add", "docs", "docs/", "--base", "main", "--shared")
        self.commit("Define the documentation slice", {"docs/index.md": "intro, clarified\n"})
        self.switch("main")
        self.assertIn("no slices defined", self.slice("list").stdout)
        self.slice("update", "docs", "--from", "dev")
        self.assertEqual(self.proposed(BRANCH), ["docs/index.md"])

    def test_paths_given_in_a_subdirectory_are_stored_from_the_root(self):
        self.slice("add", "docs", "index.md", "--base", "main", cwd=os.path.join(self.repo, "docs"))
        self.assertEqual(self.git("config", "pathslice.docs.path").strip(), "docs/index.md")

    def test_default_source_from_a_subdirectory(self):
        self.dev()
        self.switch("dev")
        src = os.path.join(self.repo, "src")
        self.assertIn("docs: clarify intro", self.slice("log", "docs", cwd=src).stdout)
        self.slice("update", "docs", cwd=src)
        self.assertEqual(self.proposed(BRANCH), ["docs/feature.md", "docs/index.md", "docs/old.md"])

    def test_slice_name_with_a_comma(self):
        self.dev()
        self.slice("add", "api,docs", "docs/", "--base", "main")
        self.slice("update", "api,docs", "--from", "dev")
        self.later()
        self.assertIn("1 file updated", self.slice("update", "api,docs", "--from", "dev").stdout)

    def test_separate_git_directory(self):
        store, tree = os.path.join(self.tmp, "store.git"), os.path.join(self.tmp, "tree")
        os.makedirs(tree)
        env = dict(self.env, GIT_DIR=store, GIT_WORK_TREE=tree)
        self.git("init", "-q", "--bare", "-b", "main", store)
        self.git("config", "core.bare", "false", env=env)
        for branch, content in (("main", "intro\n"), ("dev", "intro, clarified\n")):
            if branch == "dev":
                self.git("switch", "-q", "-c", "dev", cwd=tree, env=env)
            self.write({"docs/index.md": content}, cwd=tree)
            self.git("add", "-A", cwd=tree, env=env)
            self.git("commit", "-q", "-m", branch, cwd=tree, env=env)
        self.slice("add", "docs", "docs/", "--base", "main", cwd=tree, env=env)
        self.slice("update", "docs", cwd=tree, env=env)
        self.assertEqual(self.git("show", BRANCH + ":docs/index.md", cwd=tree, env=env), "intro, clarified\n")


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
        self.lineage(upstream=False)
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
        self.slice("add", "docs", "docs/", "--base", "main", "--upstream", "dev")
        branch = "pathslice/docs/feature"
        for resolution, proposed in (("agreed wording\n", ["docs/feature.md"]),
                                     ("agreed wording, with the feature\n", ["docs/feature.md", "docs/shared.md"])):
            with self.subTest(resolution=resolution):
                self.switch("feature")
                self.merge("dev", resolve={"docs/shared.md": resolution})
                self.switch("main")
                self.slice("update", "docs", "--from", "feature", "--rebuild")
                self.assertEqual(self.proposed(branch), proposed)
                self.assertEqual(self.show(branch, "docs/shared.md"), resolution)
                self.switch("feature")
                self.git("reset", "-q", "--hard", "HEAD^")
                self.switch("main")

    def test_changes_the_upstream_received_stay_in_the_export(self):
        self.lineage()
        self.slice("update", "docs", "--from", "feature")
        branch = "pathslice/docs/feature"
        self.switch("dev")
        self.merge("feature")
        self.switch("feature")
        self.merge("dev")
        self.commit("feature: more documentation", {"docs/more.md": "more\n"})
        self.switch("main")
        self.slice("update", "docs", "--from", "feature")
        self.assertEqual(self.proposed(branch), ["docs/feature.md", "docs/more.md"])

    def test_changes_that_build_on_the_upstream_are_left_out(self):
        self.lineage()
        self.switch("feature")
        self.commit("feature: extend the interface", {"docs/api.md": "api, extended\n"})
        self.switch("main")
        out = self.slice("update", "docs", "--from", "feature").stdout
        self.assertIn("not exported, because the changes build on dev changes that main lacks:\n  docs/api.md", out)
        self.assertEqual(self.proposed("pathslice/docs/feature"), ["docs/feature.md"])

    def test_added_paths_reach_the_export(self):
        self.dev()
        self.slice("update", "docs", "--from", "dev")
        self.git("config", "--add", "pathslice.docs.path", "src/")
        out = self.slice("update", "docs", "--from", "dev").stdout
        self.assertIn("1 file updated", out)
        self.assertNotIn("lacks", out)
        self.assertEqual(self.show(BRANCH, "src/a.py"), "x=3\n")

    def test_setting_an_upstream_removes_its_changes(self):
        self.lineage(upstream=False)
        self.slice("update", "docs", "--from", "feature")
        branch = "pathslice/docs/feature"
        self.assertEqual(self.proposed(branch), ["docs/api.md", "docs/feature.md"])
        self.git("config", "pathslice.docs.upstream", "dev")
        out = self.slice("update", "docs", "--from", "feature").stdout
        self.assertNotIn("lacks", out)
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
        self.later()
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
        self.switch("main")
        self.later()
        out = self.slice("update", "docs", "--from", "dev").stdout
        self.assertIn("has changes that dev lacks in:\n  docs/index.md", out)
        self.assertEqual(self.show(BRANCH, "docs/index.md"), "intro, reviewed\n")
        self.assertTrue(self.exists(BRANCH, "docs/later.md"))
        updated = self.sha(BRANCH)
        self.assertIn("is up to date", self.slice("update", "docs", "--from", "dev").stdout)
        self.assertEqual(self.sha(BRANCH), updated)
        self.later("docs: take the review suggestion", {"docs/index.md": "intro, reviewed\n"})
        out = self.slice("update", "docs", "--from", "dev").stdout
        self.assertIn("is up to date", out)
        self.assertNotIn("lacks", out)

    def test_exports_without_a_recorded_target_are_continued(self):
        self.dev()
        self.slice("update", "docs", "--from", "dev")
        # Make the export commit again without its Pathslice-Target trailer, as version 0.3.0 wrote it.
        info = self.git("log", "-1", "--date=raw", "--format=%an%n%ae%n%ad%n%cn%n%ce%n%cd%n%T%n%P", BRANCH).split("\n")
        message = os.path.join(self.tmp, "message")
        with open(message, "w") as f:
            f.writelines(line for line in self.git("log", "-1", "--format=%B", BRANCH).splitlines(True)
                         if not line.startswith("Pathslice-Target:"))
        env = dict(self.env, GIT_AUTHOR_NAME=info[0], GIT_AUTHOR_EMAIL=info[1], GIT_AUTHOR_DATE="@" + info[2],
                   GIT_COMMITTER_NAME=info[3], GIT_COMMITTER_EMAIL=info[4], GIT_COMMITTER_DATE="@" + info[5])
        self.git("update-ref", "refs/heads/" + BRANCH,
                 self.git("commit-tree", info[6], "-p", info[7], "-F", message, env=env).strip())
        self.switch(BRANCH)
        self.commit("Apply suggestion from review", {"docs/index.md": "intro, reviewed\n"})
        self.switch("main")
        self.later()
        out = self.slice("update", "docs", "--from", "dev").stdout
        self.assertIn("has changes that dev lacks in:\n  docs/index.md", out)
        self.assertEqual(self.show(BRANCH, "docs/index.md"), "intro, reviewed\n")
        self.assertTrue(self.exists(BRANCH, "docs/later.md"))
        self.assertIn("Pathslice-Target: ", self.git("log", "-1", "--format=%B", BRANCH))
        # The recorded tree is not part of the branch's history; without it, the update computes it again.
        self.git("prune", "--expire=now")
        updated = self.sha(BRANCH)
        self.assertIn("is up to date", self.slice("update", "docs", "--from", "dev").stdout)
        self.assertEqual(self.sha(BRANCH), updated)

    def test_conflicting_review_commit_is_refused_until_rebuilt(self):
        self.dev()
        self.slice("update", "docs", "--from", "dev")
        self.switch(BRANCH)
        self.commit("Apply suggestion from review", {"docs/index.md": "review wording\n"})
        self.switch("main")
        self.later("docs: rewrite intro", {"docs/index.md": "intro, rewritten\n"})
        p = self.slice("update", "docs", "--from", "dev", check=False)
        self.assertEqual(p.returncode, 1)
        self.assertIn("conflict with its new changes in:\n  docs/index.md", p.stderr)
        self.slice("update", "docs", "--from", "dev", "--rebuild")
        self.assertEqual(self.sha(BRANCH + "^"), self.sha("main"))
        self.assertEqual(self.show(BRANCH, "docs/index.md"), "intro, rewritten\n")

    def test_rebuild_with_nothing_to_export_starts_at_the_base(self):
        self.dev()
        self.slice("update", "docs", "--from", "dev")
        self.switch(BRANCH)
        self.commit("Apply suggestion from review", {"docs/index.md": "intro, reviewed\n"})
        self.switch("main")
        self.later("docs: withdraw the changes", {"docs/index.md": "intro\n", "docs/old.md": "old page\n",
                                                  "docs/feature.md": None})
        p = self.slice("update", "docs", "--from", "dev", check=False)
        self.assertIn("--rebuild", p.stderr)
        self.assertIn("with nothing to export", self.slice("update", "docs", "--from", "dev", "--rebuild").stdout)
        self.assertEqual(self.sha(BRANCH), self.sha("main"))
        self.assertIn("nothing to export", self.slice("update", "docs", "--from", "dev").stdout)

    def test_merged_export_starts_again_from_the_base(self):
        self.dev()
        self.slice("update", "docs", "--from", "dev")
        exported = self.sha(BRANCH)
        self.merge(BRANCH)
        self.assertIn("nothing to export", self.slice("update", "docs", "--from", "dev").stdout)
        self.assertEqual(self.sha(BRANCH), exported)
        self.later()
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
        self.commit("main: edit the intro again", {"docs/index.md": "intro, clarified and edited\n"})
        out = self.slice("status", "docs", "--from", "dev").stdout
        self.assertIn("nothing to export", out)
        self.later()
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

    def test_conflicts_between_the_branch_and_the_base_are_reported(self):
        self.dev()
        self.slice("update", "docs", "--from", "dev")
        self.commit("main: reword the intro", {"docs/index.md": "intro, reworded on main\n"})
        out = self.slice("update", "docs", "--from", "dev").stdout
        self.assertIn("is up to date", out)
        self.assertIn("conflicts with main in:\n  docs/index.md", out)
        self.assertIn("conflicts with main in:", self.slice("status", "docs", "--from", "dev").stdout)

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

    def test_withdrawn_changes_leave_an_empty_branch_that_is_not_merged(self):
        self.dev()
        self.slice("update", "docs", "--from", "dev")
        self.later("docs: withdraw the changes", {"docs/index.md": "intro\n", "docs/old.md": "old page\n",
                                                  "docs/feature.md": None})
        self.assertIn("3 files updated", self.slice("update", "docs", "--from", "dev").stdout)
        emptied = self.sha(BRANCH)
        self.assertEqual(self.proposed(BRANCH), [])
        self.assertIn("up to date", self.slice("status", "docs", "--from", "dev").stdout)
        self.later()
        self.slice("update", "docs", "--from", "dev")
        self.assertEqual(self.sha(BRANCH + "^"), emptied)


class TestBranchSafety(Base):
    def test_checked_out_export_branch_is_refused(self):
        self.dev()
        self.slice("update", "docs", "--from", "dev")
        self.git("worktree", "add", "-q", os.path.join(self.tmp, "other"), BRANCH)
        self.later()
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
        self.slice("update", "docs", "--from", "dev")
        self.git("cherry-pick", BRANCH)
        self.git("branch", "notes", "main")
        self.switch("notes")
        self.commit("Meeting notes", {"notes.txt": "notes\n"})
        self.switch("main")
        notes = self.sha("notes")
        for extra in ([], ["--rebuild"]):
            p = self.slice("update", "docs", "--from", "dev", "--branch", "notes", *extra, check=False)
            self.assertEqual(p.returncode, 1)
            self.assertIn("is not an export of slice docs", p.stderr)
        self.assertEqual(self.sha("notes"), notes)

    def test_another_base_needs_another_branch(self):
        self.dev()
        self.slice("update", "docs", "--from", "dev")
        self.git("branch", "release", "main~1")
        p = self.slice("update", "docs", "--from", "dev", "--onto", "release", check=False)
        self.assertEqual(p.returncode, 1)
        self.assertIn("exports slice docs onto main", p.stderr)

    def test_branches_for_different_bases_are_told_apart(self):
        self.dev()
        self.slice("update", "docs", "--from", "dev")
        self.git("branch", "release", "main~1")
        self.slice("update", "docs", "--from", "dev", "--onto", "release", "--branch", "docs-for-release")
        self.later()
        self.assertIn("%s: 1 file updated" % BRANCH, self.slice("update", "docs", "--from", "dev").stdout)
        out = self.slice("update", "docs", "--from", "dev", "--onto", "release").stdout
        self.assertIn("docs-for-release: 1 file updated", out)
        self.assertEqual(self.proposed("docs-for-release", "release"),
                         ["docs/feature.md", "docs/index.md", "docs/later.md", "docs/old.md"])

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
        scope = hashlib.sha256(json.dumps(["docs", ["docs/"], "main"]).encode()).hexdigest()
        self.switch("specs-export", create=True, start="main")
        self.commit("Add feature and documentation\n\nSliced-From: %s\nPathslice: %s %s" % (source, scope, source),
                    {"docs/index.md": "intro, clarified\n", "docs/feature.md": "feature\n", "docs/old.md": None})
        legacy = self.sha("HEAD")
        self.switch("main")
        self.legacy_record("specs-export")
        self.later()
        self.switch("specs-export")
        self.assertIn("slice docs: dev -> main  (branch specs-export)", self.slice("status", "docs").stdout)
        self.switch("main")
        self.slice("update", "docs", "--from", "dev")
        self.assertEqual(self.sha("specs-export^"), legacy)
        self.assertEqual(self.proposed("specs-export"),
                         ["docs/feature.md", "docs/index.md", "docs/later.md", "docs/old.md"])
        self.assertIn("- docs: later note", self.git("log", "-1", "--format=%B", "specs-export"))

    def test_several_version_0_2_exports_need_a_branch(self):
        self.dev()
        self.legacy_record("export-a")
        self.legacy_record("export-b")
        p = self.slice("update", "docs", "--from", "dev", check=False)
        self.assertEqual(p.returncode, 1)
        self.assertIn("several branches export slice docs from dev", p.stderr)

    def test_stale_source_cannot_replace_a_newer_export(self):
        self.dev()
        bare = self.remote()
        self.slice("update", "docs", "--from", "dev", "--push")
        other = self.clone(bare)
        self.git("branch", "dev", "origin/dev", cwd=other)
        self.slice("add", "docs", "docs/", "--base", "main", cwd=other)
        self.later()
        self.git("push", "-q", "origin", "dev")
        self.slice("update", "docs", "--from", "dev", "--push")
        self.git("fetch", "-q", "origin", cwd=other)
        p = self.slice("update", "docs", "--from", "dev", "--push", cwd=other, check=False)
        self.assertEqual(p.returncode, 1)
        self.assertIn("which is newer than dev", p.stderr)
        self.assertEqual(self.git("rev-parse", BRANCH, cwd=bare).strip(), self.sha(BRANCH))

    def test_missing_source_commit_stops_the_update(self):
        self.dev()
        bare = self.remote()
        self.slice("update", "docs", "--from", "dev", "--push")
        self.review(bare, {"docs/feature.md": "feature, reviewed\n"})
        self.git("fetch", "-q", "origin")
        self.later()
        self.slice("update", "docs", "--from", "dev", "--push")
        self.switch("dev")
        self.git("commit", "-q", "--amend", "-m", "docs: later note, reworded")
        self.git("push", "-q", "--force", "origin", "dev")
        self.switch("main")
        fresh = self.clone(bare, "--no-local")
        self.git("branch", "dev", "origin/dev", cwd=fresh)
        self.slice("add", "docs", "docs/", "--base", "main", cwd=fresh)
        p = self.slice("update", "docs", "--from", "dev", cwd=fresh, check=False)
        self.assertEqual(p.returncode, 1)
        self.assertIn("which this repository does not have", p.stderr)


class TestPublication(Base):
    def test_pushes_include_commits_added_on_the_remote(self):
        self.dev()
        bare = self.remote()
        self.assertIn("pushed %s to origin" % BRANCH, self.slice("update", "docs", "--from", "dev", "--push").stdout)
        self.review(bare, {"docs/feature.md": "feature, reviewed\n"})
        self.later()
        self.git("fetch", "-q", "origin")
        self.slice("update", "docs", "--from", "dev", "--push")
        self.assertEqual(self.git("rev-parse", BRANCH, cwd=bare).strip(), self.sha(BRANCH))
        self.assertEqual(self.show(BRANCH, "docs/feature.md", cwd=bare), "feature, reviewed\n")
        self.assertEqual(self.show(BRANCH, "docs/later.md", cwd=bare), "later\n")
        self.assertIn("already up to date", self.slice("update", "docs", "--from", "dev", "--push").stdout)

    def test_rejected_push_can_be_retried(self):
        self.dev()
        bare = self.remote()
        hook = os.path.join(bare, "hooks", "pre-receive")
        with open(hook, "w") as f:
            f.write("#!/bin/sh\nexit 1\n")
        os.chmod(hook, 0o755)
        self.assertNotEqual(self.slice("update", "docs", "--from", "dev", "--push", check=False).returncode, 0)
        os.remove(hook)
        self.slice("update", "docs", "--from", "dev", "--push")
        self.assertEqual(self.git("rev-parse", BRANCH, cwd=bare).strip(), self.sha(BRANCH))

    def test_remote_branch_deleted_after_its_merge(self):
        self.dev()
        bare = self.remote()
        self.slice("update", "docs", "--from", "dev", "--push")
        self.merge(BRANCH)
        self.git("push", "-q", "origin", "main")
        self.git("branch", "-D", BRANCH, cwd=bare)
        self.later()
        self.slice("update", "docs", "--from", "dev", "--push")
        self.assertEqual(self.proposed(BRANCH), ["docs/later.md"])
        self.assertEqual(self.git("rev-parse", BRANCH, cwd=bare).strip(), self.sha(BRANCH))

    def test_branch_started_again_after_a_squash_merge_can_be_pushed_later(self):
        self.dev()
        bare = self.remote()
        self.slice("update", "docs", "--from", "dev", "--push")
        self.git("merge", "-q", "--squash", BRANCH)
        self.git("commit", "-q", "-m", "Documentation (#7)")
        self.git("push", "-q", "origin", "main")
        self.later()
        self.slice("update", "docs", "--from", "dev")
        self.slice("update", "docs", "--from", "dev", "--push")
        self.assertEqual(self.git("rev-parse", BRANCH, cwd=bare).strip(), self.sha(BRANCH))
        self.assertEqual(self.proposed(BRANCH), ["docs/later.md"])

    def test_unseen_remote_commits_are_not_replaced(self):
        self.dev()
        bare = self.remote()
        self.slice("update", "docs", "--from", "dev", "--push")
        reviewed = self.review(bare, {"docs/feature.md": "feature, reviewed\n"})
        self.later()
        p = self.slice("update", "docs", "--from", "dev", "--rebuild", "--push", check=False)
        self.assertNotEqual(p.returncode, 0)
        self.assertEqual(self.git("rev-parse", BRANCH, cwd=bare).strip(), reviewed)

    def test_unrecognised_remote_branch_is_refused(self):
        self.dev()
        bare = self.remote()
        self.git("push", "-q", "origin", "main:refs/heads/" + BRANCH)
        self.git("fetch", "-q", "origin")
        p = self.slice("update", "docs", "--from", "dev", "--push", check=False)
        self.assertEqual(p.returncode, 1)
        self.assertIn("is not an export of slice docs", p.stderr)
        self.assertEqual(self.git("rev-parse", BRANCH, cwd=bare).strip(), self.sha("main"))

    def test_publish_replaces_local_exports_with_the_remote_branch(self):
        self.dev()
        bare = self.remote()
        self.fake_gh()
        self.slice("update", "docs", "--from", "dev", "--push")
        self.review(bare, {"docs/feature.md": "feature, reviewed\n"})
        self.later()
        self.slice("update", "docs", "--from", "dev")
        p = self.slice("publish", "docs", "--from", "dev")
        self.assertIn("replacing 1 local commit(s) made by git pathslice", p.stderr)
        self.assertEqual(self.show(BRANCH, "docs/feature.md", cwd=bare), "feature, reviewed\n")
        self.assertEqual(self.show(BRANCH, "docs/later.md", cwd=bare), "later\n")

    def test_amended_export_commit_is_kept(self):
        self.dev()
        bare = self.remote()
        self.fake_gh()
        self.slice("update", "docs", "--from", "dev", "--push")
        self.review(bare, {"docs/feature.md": "feature, reviewed\n"})
        self.switch(BRANCH)
        self.write({"docs/index.md": "intro, amended\n"})
        self.git("commit", "-q", "-a", "--amend", "--no-edit",
                 env=dict(self.env, GIT_COMMITTER_DATE="@2000000000 +0000"))
        amended = self.sha(BRANCH)
        self.switch("main")
        p = self.slice("publish", "docs", "--from", "dev", check=False)
        self.assertEqual(p.returncode, 1)
        self.assertIn("neither on origin/%s nor made by git pathslice" % BRANCH, p.stderr)
        self.assertEqual(self.sha(BRANCH), amended)

    def test_publish_without_update_keeps_the_local_branch(self):
        self.dev()
        bare = self.remote()
        self.fake_gh()
        self.slice("update", "docs", "--from", "dev", "--push")
        reviewed = self.review(bare, {"docs/feature.md": "feature, reviewed\n"})
        self.later()
        self.slice("update", "docs", "--from", "dev")
        local = self.sha(BRANCH)
        p = self.slice("publish", "docs", "--from", "dev", "--no-update", check=False)
        self.assertEqual(p.returncode, 1)
        self.assertEqual(self.sha(BRANCH), local)
        self.assertEqual(self.git("rev-parse", BRANCH, cwd=bare).strip(), reviewed)

    def test_withdrawn_changes_are_published(self):
        self.dev()
        bare = self.remote()
        self.fake_gh()
        self.slice("publish", "docs", "--from", "dev")
        self.later("docs: withdraw the changes", {"docs/index.md": "intro\n", "docs/old.md": "old page\n",
                                                  "docs/feature.md": None})
        self.assertIn("no changes remain", self.slice("publish", "docs", "--from", "dev").stdout)
        self.assertEqual(self.git("rev-parse", BRANCH, cwd=bare).strip(), self.sha(BRANCH))

    def test_publish_creates_then_reuses_the_pull_request(self):
        self.dev()
        bare = self.remote()
        calls = self.fake_gh()
        self.slice("publish", "docs", "--from", "dev", "--branch", "review/docs", "--draft")
        self.later()
        self.assertIn("using existing PR", self.slice("pr", "docs", "--from", "dev").stdout)
        self.assertEqual(self.show("review/docs", "docs/later.md", cwd=bare), "later\n")
        created = [cmd for cmd in self.gh_calls(calls) if cmd[:2] == ["pr", "create"]]
        self.assertEqual(len(created), 1)
        self.assertIn("--draft", created[0])

    def test_publish_pushes_when_no_pull_request_can_be_opened(self):
        self.dev()
        bare = self.remote()
        hook = os.path.join(bare, "hooks", "post-receive")
        with open(hook, "w") as f:
            f.write("#!/bin/sh\necho 'Open a pull request at https://example.invalid/new'\n")
        os.chmod(hook, 0o755)
        p = self.slice("publish", "docs", "--from", "dev", env=self.without_gh())
        self.assertIn("remote: Open a pull request at https://example.invalid/new", p.stdout)
        self.assertIn("no pull request was opened from %s into main: gh, the GitHub CLI, is not installed"
                      % BRANCH, p.stderr)
        self.assertEqual(self.git("rev-parse", BRANCH, cwd=bare).strip(), self.sha(BRANCH))
        self.fake_gh()
        self.env["GH_TEST_FAIL"] = "1"
        self.later()
        p = self.slice("publish", "docs", "--from", "dev")
        self.assertIn("no pull request was opened from %s into main: gh failed: service unavailable" % BRANCH,
                      p.stderr)
        self.assertEqual(self.git("rev-parse", BRANCH, cwd=bare).strip(), self.sha(BRANCH))

    def test_pull_request_after_a_merge_lists_only_new_commits(self):
        self.dev()
        self.remote()
        calls = self.fake_gh()
        self.slice("publish", "docs", "--from", "dev")
        self.merge(BRANCH)
        self.git("push", "-q", "origin", "main")
        os.remove(calls.replace(".jsonl", ".created"))
        self.later()
        self.slice("publish", "docs", "--from", "dev")
        body = [cmd for cmd in self.gh_calls(calls) if cmd[:2] == ["pr", "create"]][-1]
        body = body[body.index("--body") + 1]
        self.assertIn("docs: later note", body)
        self.assertNotIn("clarify intro", body)


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
        self.assertIn("files in the export:\n    docs/feature.md\n    docs/index.md\n    docs/old.md", out)

    def test_status_arguments_are_checked(self):
        self.dev()
        for args, message in ((["status", "nosuch", "--from", "dev"], "no slice named 'nosuch'"),
                              (["status", "--from", "dev", "--branch", "x"], "--branch needs a slice name")):
            p = self.slice(*args, check=False)
            self.assertEqual(p.returncode, 1)
            self.assertIn(message, p.stderr)


if __name__ == "__main__":
    unittest.main()
