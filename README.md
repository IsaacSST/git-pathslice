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
git pathslice add docs docs/ --base origin/main --shared
git add .gitpathslices
git commit -m "Define the documentation slice"
```

`add` stores the definition. `update` and `publish` create the slice branch.

`.gitpathslices` uses Git configuration syntax and permits multiple `path`
entries. Local definitions in `.git/config` can add paths or override other
settings. Paths are Git pathspecs relative to the repository root; `add`
also accepts paths relative to the current directory.

## Use

Publish the configured documentation slice from your implementation branch:

```sh
git pathslice publish docs
```

`docs` names the slice defined above: it selects `docs/` and targets
`origin/main`. `publish` fetches the remote, prepares a separate slice branch,
pushes it, then creates a PR or reuses an open one. `pr` is an alias for
`publish`.

Each slice/source pair initially uses `pathslice/<slice>/<source>`.
For a source branch named `feature`, the PR runs from `pathslice/docs/feature`
into `main`. Later runs update that slice branch; the implementation branch
remains unchanged. Only committed changes are eligible; uncommitted edits are
excluded.

A source commit changing `src/parser.rs` and `docs/parser.md` contributes only
the documentation change. The restricted patch and provenance trailers give
it a different commit hash; code retains the destination's version. Merge
the PR through the usual review process. Later exports omit recognised
changes already incorporated into the destination.

While the PR is open, edit the source branch and rerun `publish` to update it.
It exits without publishing if there are no changes. For separate steps:

| Command | Behaviour |
| --- | --- |
| `log docs` | Preview which commits contribute changes, using local refs. |
| `update docs` | Prepare the slice branch locally, without fetching. |
| `update docs --push` | Prepare and push the slice branch, without fetching or opening a PR. |

Use `--from BRANCH` to select another source or `--onto REF` to override the
destination, for example `--from feature --onto origin/main`.
`publish --no-update docs` uses the existing slice branch without exporting
new source changes. It still fetches, pushes and creates or reuses a PR.

Unchanged exports retain their hashes. Destination changes alone do not
rebuild an open PR; `--force-rebuild` requests this and rewrites the export
commits. Conflicts with the destination are reported when Git supports the
check. Identical replay inputs reproduce the same hashes.

Slice branches are recorded locally. Existing branches are accepted only
when recorded for the same slice and source, with no subsequent changes
outside the tool. Source and destination branches cannot be export targets.
These checks also apply to `--force-rebuild` and `publish --no-update`.
For a collision, rename the ordinary branch or use `update --branch NAME`.
An ordinary branch created from a slice remains independent.

## Working with Git

Pathslice installs no hooks. Ordinary Git commands remain available; pathslice
checks before changing branches and reports altered or missing exports in
`status`. It refuses to update branches checked out or used by a rebase or
bisect, including in other worktrees. Changes made directly on an export
remain intact. Transfer intended changes to the source before rebuilding.

After cloning or renaming an export with `git branch -m`, reconnect the local
branch explicitly:

```sh
git pathslice adopt docs --from feature --branch review/docs
```

`adopt` records ownership without changing commits. It requires a matching
local export record or verifies content and commit metadata against the source
patches. Independent edits and unverified conflict resolutions are refused.
If the source was renamed, supply its new name with `--from`.
Renaming locally does not rename a remote branch or an existing PR.

The recorded branch is used by later commands. `update`, `publish`, `log` and
`status` accept `--branch` to choose another; multiple exports for the same
slice and source require an explicit choice. Running from a managed slice
branch uses its recorded source. If Git deletes a recorded export, recreate
it explicitly with `update --branch NAME`.

To continue working on an export as an ordinary branch:

```sh
git pathslice release docs --from feature --branch review/docs
```

`release` removes ownership while retaining the branch and landing records.

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
git pathslice landed docs SOURCE_REVISION
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
git pathslice continue docs  # resume the update
git pathslice skip docs      # omit the conflicting commit
git pathslice abort docs     # discard the update
```

`continue` preserves commit metadata. `abort` retains the previous derived
branch. If `publish` stopped on a conflict, rerun it after `continue` to publish.

Pushes use an explicit lease against the last accepted export. Unexpected
remote changes are refused even after a background fetch. A new checkout
validates the remote export's scope and source history before replacing it.
It also verifies content and commit metadata: provenance trailers alone do not
establish that a commit is unchanged. Unrecognised or altered remote exports
are refused. Failed pushes leave the local export available for retry.

## Other commands

`list` and `status` inspect slices; `rm` removes definitions. `forget` removes
landing records and checkpoints but retains branch ownership and publication
leases. `forget --branch` also deletes the recorded slice branch and its
ownership record, provided the branch is unchanged and not in use. Use
`--export-branch NAME` to choose among multiple exports when deleting.
Use `git pathslice COMMAND -h` for options.

## Limits and tests

Source merge commits are not replayed. Changes made only in merge resolutions
may therefore be omitted without a conflict. Review the final diff.
Renames crossing a slice boundary become additions or deletions. Path
selection does not check dependencies between documentation and code.

Development uses Python 3.14. Compatibility checks cover Python 3.12 and 3.14. Tests require Git 2.28 or later.

```sh
python3.14 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m mypy
.venv/bin/python -m ruff check git-pathslice tests
.venv/bin/python -m unittest discover -s tests -v
```

Tests use temporary Git repositories and local remotes. GitHub PR calls
are simulated.
