# git pathslice

Export selected paths from a source branch as a separate pull request. Each
selected commit retains its message and author and committer metadata, with
provenance trailers added. The source branch and checkout remain unchanged.

Git handles patch generation, equivalence checks and three-way application.
Python manages configuration, export records and temporary worktrees; `gh`
manages pull requests.

## Installation

Requires Git 2.22 or later and Python 3.12 or later. PR commands require
GitHub CLI, authenticated with `gh auth login`.

```sh
git clone https://github.com/IsaacSST/git-pathslice.git
cd git-pathslice
mkdir -p ~/.local/bin
ln -s "$PWD/git-pathslice" ~/.local/bin/git-pathslice
export PATH="$HOME/.local/bin:$PATH"
git pathslice -h
```

Keep `~/.local/bin` on your shell's `PATH`. Use `-h` for help; Git's `--help`
option expects a manual page.

## Configuration

Define the slice and commit its shared configuration:

```sh
git pathslice add specs specs/ --base origin/main --shared
git add .gitpathslices
git commit -m "Define the specifications slice"
```

`.gitpathslices` uses Git configuration syntax and permits multiple `path`
entries. Local definitions in `.git/config` can add paths or override other
settings. Paths are Git pathspecs relative to the repository root; `add`
also accepts paths relative to the current directory.

## Use

Run from the implementation branch:

```sh
git pathslice log specs       # preview the selection
git pathslice update specs    # build locally
git pathslice pr specs        # fetch, build, push and create or update the PR
```

The first two commands are optional. `pr` reuses an open PR and exits without
publishing if there are no changes. Continue editing the source branch and
rerun `pr`; do not edit the derived branch, `pathslice/specs/<source-branch>`.

A source commit changing `src/pump.rs` and `specs/pump.md` contributes only
the specification change. The restricted patch and provenance trailers give
it a different commit hash; code retains the destination's version. Merge
the PR through the usual review process. Later exports omit recognised
changes already incorporated into the destination.

`log` and `update` use local refs; `pr` fetches first. Use `--from BRANCH`
to select another source or `--onto REF` to override the destination.
Unchanged exports retain their hashes. Destination changes alone do not
rebuild an open PR; `--force-rebuild` requests this and rewrites the export
commits. Conflicts with the destination are reported when Git supports the
check. Identical replay inputs reproduce the same hashes.

## Selection

Set the rule with `add --select RULE`:

| Rule | Commits exported |
| --- | --- |
| `all` | Any commit affecting the paths, restricted to those paths. |
| `pure` | Commits affecting only those paths. |
| `marked` | Commits with `Slice: NAME` or a subject matching `--subject REGEX`. |

`--all` overrides the rule. Excluded or manually skipped commits remain
eligible for later exports, including after an earlier export lands.

## Landing and checkpoints

`Sliced-From: SHA` identifies the source commit. The `Pathslice:` trailer
also identifies the scope: slice name, paths and destination ref. Landing
evidence applies only within that scope. Local records under
`refs/pathslices/` are updated atomically with the derived branch.

Normal merges are recognised through ancestry; independently applied commits
through path-restricted patch equivalence. Squash merges can be recognised
when a later destination revision matches every file changed by the export.
Squash recognition marks only recorded export commits as landed.

For existing history or a squash merge that cannot be recognised:

```sh
git pathslice landed specs SOURCE_REVISION
```

This declares the selected changes in that revision and its ancestors
accounted for. Verify the revision first. Declarations accumulate across
side branches; use `forget` to clear mistaken checkpoints before replacing
them. Changing the paths or destination starts a separate scope.

Export records and publication leases do not travel with an ordinary clone.
Squash merges without records or scoped trailers, or with additional edits
to the exported files, may require a checkpoint. Unscoped `Sliced-From:`
trailers alone do not establish that changes landed.

## Conflicts and publication

Resolve and stage conflicts in the reported worktree under `.git/pathslice/`,
then run from the source checkout:

```sh
git pathslice continue specs  # resume the update
git pathslice skip specs      # omit the conflicting commit
git pathslice abort specs     # discard the update
```

`continue` preserves commit metadata. `abort` retains the previous derived
branch. If `pr` stopped on a conflict, rerun it after `continue` to publish.

Pushes use an explicit lease against the last accepted export. Unexpected
remote changes are refused even after a background fetch. A new checkout
validates the remote export's scope and source history before replacing it.
Failed pushes leave the local export available for retry.

## Other commands

`list` and `status` inspect slices; `rm` removes definitions. `forget` removes
export records and checkpoints but retains publication leases. `update --push`
publishes without a PR; `pr --no-update` publishes the existing derived branch.
Use `git pathslice COMMAND -h` for options.

## Limits and tests

Source merge commits are not replayed. Changes made only in merge resolutions
may therefore be omitted without a conflict. Review the final diff.
Renames crossing a slice boundary become additions or deletions. Path
selection does not check dependencies between specifications and code.

Development uses Python 3.14. Compatibility checks cover Python 3.12
(used by RavensPort) and 3.14. Tests require Git 2.28 or later.

```sh
python3.14 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m mypy
.venv/bin/python -m ruff check git-pathslice tests
.venv/bin/python -m unittest discover -s tests -v
```

Tests use temporary Git repositories and local remotes. GitHub PR calls
are simulated.
