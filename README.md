# git pathslice

Export selected paths from a source branch as a separate pull request. Each
exported commit retains the original message and metadata for its author and
committer. Commit trailers (fields appended to the message) identify its
source. The source branch and checkout remain unchanged.

Git generates patches, checks whether equivalent changes are already present
and applies patches using three-way merges where supported. Python manages
configuration, export records and temporary worktrees. The GitHub CLI (`gh`)
manages pull requests.

## Installation

Requires Git 2.22 or later and Python 3.12 or later. Pull request (PR) commands
also require the GitHub CLI, authenticated with `gh auth login`.

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

A slice is a named selection of paths to export. Define a slice and commit its
shared configuration:

```sh
git pathslice add specs specs/ --base origin/main --shared
git add .gitpathslices
git commit -m "Define the specifications slice"
```

`add` stores the definition. `update` and `publish` create the slice branch.

`.gitpathslices` uses Git configuration syntax and permits multiple `path`
entries. Local definitions in `.git/config` can add paths or override other
settings. Paths use Git pathspec syntax, which supports file names, directories
and patterns, and are relative to the repository root. `add` also accepts paths
relative to the current directory.

## Use

Publish the configured specifications slice from your implementation branch:

```sh
git pathslice publish specs
```

`specs` names the slice defined above: it selects `specs/` and targets
`origin/main`. `publish` fetches the remote, prepares a separate slice branch,
pushes it, then creates a PR or reuses an open one. `pr` is an alias for
`publish`.

Each combination of slice and source branch initially uses the branch name
`pathslice/<slice>/<source>`. For a source branch named `feature`, the PR
proposes merging `pathslice/specs/feature` into `main`. Later runs update that
slice branch; the implementation branch remains unchanged. Only committed
changes are eligible; uncommitted edits are excluded.

A source commit changing `src/pump.rs` and `specs/pump.md` contributes only the
specification change. Restricting the patch to the selected paths and adding
source information to the message gives the exported commit a different hash.
Files outside the selected paths retain their destination versions. Merge the
PR through the usual review process. Later exports omit recognised changes
already incorporated into the destination.

While the PR is open, edit the source branch and rerun `publish` to update it.
It exits without publishing if there are no changes. For separate steps:

| Command | Behaviour |
| --- | --- |
| `log specs` | Preview which commits contribute changes, using local Git references. |
| `update specs` | Prepare the slice branch locally, without fetching. |
| `update specs --push` | Prepare and push the slice branch, without fetching or opening a PR. |

Use `--from BRANCH` to select another source or `--onto REF` to override the
destination, for example `--from feature --onto origin/main`.
`publish --no-update specs` uses the existing slice branch without exporting
new source changes. It still fetches, pushes and creates or reuses a PR.

Unchanged exports retain their commit hashes. Changes to the destination alone
do not rebuild the branch for an open PR. Use `--force-rebuild` to rebuild it
against the destination, rewriting the exported commits. Conflicts with the
destination are reported when the installed Git version supports this check.
Repeating an export with identical inputs produces the same commit hashes.

Slice branches are recorded locally. An existing branch can be updated only if
it is recorded for the same slice and source and has not subsequently been
changed outside pathslice. Neither the source nor the destination branch can be
used as the slice branch. These checks also apply to `--force-rebuild` and
`publish --no-update`. If the proposed name is already in use by an ordinary
branch, rename that branch or use `update --branch NAME` to choose a different
name for the slice branch. An ordinary branch created from a slice branch
remains independent.

## Working with Git

Pathslice installs no hooks. Ordinary Git commands remain available; pathslice
checks before changing branches and reports altered or missing exports in
`status`. It refuses to update branches checked out or used by a rebase or
bisect, including in other worktrees. Changes made directly on a slice branch
are preserved. Transfer any changes you wish to retain to the source branch
before rebuilding the export.

After cloning the repository or renaming a slice branch with `git branch -m`,
register the local branch with pathslice:

```sh
git pathslice adopt specs --from feature --branch review/specs
```

`adopt` records the branch as managed by pathslice without changing its
commits. It requires a matching local export record or verifies content and
commit metadata against the source patches. It refuses branches with
independent edits or conflict resolutions that it cannot verify. If the source
was renamed, supply its new name with `--from`. Renaming locally does not
rename a remote branch or an existing PR.

The recorded branch is used by later commands. `update`, `publish`, `log` and
`status` accept `--branch` to choose another; multiple exports for the same
slice and source require an explicit choice. Running from a managed slice
branch uses its recorded source. If Git deletes a recorded export, recreate it
explicitly with `update --branch NAME`.

To continue working on an export as an ordinary branch:

```sh
git pathslice release specs --from feature --branch review/specs
```

`release` stops pathslice from managing the branch. It retains the branch and
the records of changes already incorporated into the destination.

## Selection

Set the rule with `add --select RULE`:

| Rule | Commits exported |
| --- | --- |
| `all` | Any commit affecting the paths, restricted to those paths. |
| `pure` | Commits affecting only those paths. |
| `marked` | Commits with `Slice: NAME` or a subject matching `--subject REGEX`. |

`--all` overrides the rule. Excluded or manually skipped commits remain
eligible for later exports, including after an earlier export has been merged.

## Recognising previously incorporated changes

`Sliced-From: SHA` identifies the source commit. The `Pathslice:` trailer
identifies the slice name, selected paths and destination reference. Together,
these define the scope of an export. Evidence that changes have already been
incorporated into the destination applies only within that scope. Local records
under `refs/pathslices/` and the slice branch are updated in a single Git
transaction.

Normal merges are recognised through commit ancestry. Independently applied
commits are recognised by comparing patches restricted to the selected paths.
Squash merges can be recognised when a later destination revision matches every
file changed by the export. Recognising a squash merge marks only the recorded
exported commits as incorporated into the destination.

For existing history or a squash merge that cannot be recognised:

```sh
git pathslice landed specs SOURCE_REVISION
```

This records a checkpoint: the selected changes in that revision and its
ancestors are treated as already accounted for and excluded from later exports.
Verify the revision first. Checkpoints accumulate across branches; use `forget`
to clear mistaken checkpoints before replacing them. Changing the paths or
destination starts a separate scope.

An ordinary clone does not copy export records or the records used to detect
unexpected remote changes when pushing. A checkpoint may be needed for squash
merges if neither export records nor commit trailers identifying the scope are
available, or if the exported files contain additional edits. `Sliced-From:`
trailers alone do not establish that changes were incorporated into the
destination.

## Conflicts and publication

Resolve and stage conflicts in the reported worktree under `.git/pathslice/`,
then run from the source checkout:

```sh
git pathslice continue specs  # resume the update
git pathslice skip specs      # omit the conflicting commit
git pathslice abort specs     # discard the update
```

`continue` preserves commit metadata. `abort` retains the previous slice
branch. If `publish` stopped on a conflict, rerun it after `continue` to
publish.

When a previous publication record exists, pathslice checks that the remote
branch matches the last accepted export before pushing. It uses Git's
`--force-with-lease` option to prevent the push from overwriting changes made
after this check. Unexpected remote changes cause the push to be refused, even
after a background fetch. A new checkout validates the remote export's scope
and source history before replacing it. It also verifies content and commit
metadata: source information in commit trailers alone does not establish that a
commit is unchanged. Unrecognised or altered remote exports are refused. Failed
pushes leave the local export available for retry.

## Other commands

`list` and `status` inspect slices; `rm` removes definitions. `forget` removes
records of previously incorporated changes and checkpoints. It retains the
record of which branches pathslice manages and the records used to check remote
branches before pushing. `forget --branch` also deletes the recorded slice
branch and its management record, provided the branch is unchanged and not in
use. Use `--export-branch NAME` to choose among multiple exports when deleting.
Use `git pathslice COMMAND -h` for options.

## Limits and tests

Source merge commits are not exported. Changes made only in merge resolutions
may therefore be omitted without a conflict. Review the final diff. Renames
crossing a slice boundary become additions or deletions. Path selection does
not check dependencies between specifications and code.

Development uses Python 3.14. Compatibility checks cover Python 3.12 (used by
RavensPort) and 3.14. Tests require Git 2.28 or later.

```sh
python3.14 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m mypy
.venv/bin/python -m ruff check git-pathslice tests
.venv/bin/python -m unittest discover -s tests -v
```

Tests use temporary Git repositories and local remotes. GitHub PR calls are
simulated.
