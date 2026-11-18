# MetaStrip v0.1.0 source release

## Before publication

- Review the exact first-commit manifest and exclude local notes, settings, history, test data, logs, environments, tool downloads, and build outputs.
- Run lint, format checks, the full test suite with optional tools, and a Windows startup check. Record any skips.
- Confirm contributor and asset rights and the scope of Corresponding Source before publishing under [AGPL-3.0-only](../LICENSE).
- Verify that the sidebar **Licenses** dialog shows copyright, warranty, and redistribution terms and links to the full AGPLv3 text.
- Include the complete preferred form for modifying and building the release, including source, assets, and relevant scripts. Preserve copyright, license, and warranty notices. Mark modified covered files or works prominently with the relevant change date as required by AGPLv3 section 5.
- Regenerate and review the exact first-commit manifest after licensing approval, including the preserved MIT notice.
- Set up a private vulnerability reporting route. Avoid using personal contact details in public files.
- Obtain explicit approval before committing, creating a remote repository, pushing, or publishing.

## GitHub settings

- Name: `MetaStrip`
- Description: `Modern desktop utility for removing metadata from files.`
- Topics: `python`, `metadata`, `privacy`, `desktop-app`, `pyside6`, `exiftool`, `ffmpeg`
- Version tag: `v0.1.0`
- Release assets: GitHub-generated source archives only.

## Publication sequence after approval

1. Stage only the reviewed first-commit paths. Review `git diff --cached --name-status` and `git diff --cached --check`, then create the initial commit.

   ```powershell
   git --literal-pathspecs add --pathspec-from-file=artifacts/final-preflight/publication-files.txt
   git diff --cached --name-status
   git diff --cached --check
   git commit -m "Initial MetaStrip v0.1.0 source release"
   ```

2. Create an empty GitHub repository named **MetaStrip**. An empty private repository lets you run GitHub CI and finish the review before changing visibility.
3. Attach the approved remote and push the reviewed branch. The following commands assume the chosen branch is `main` and the remote is named `origin`.

   ```powershell
   git branch -m main
   git remote add origin https://github.com/OWNER/MetaStrip.git
   git push -u origin main
   ```

4. Check the GitHub CI matrix and review the repository in GitHub. Enable private vulnerability reporting if available for the chosen visibility.
5. After approval to publish, change visibility to Public, tag the approved commit, and push the tag.

   ```powershell
   git tag -a v0.1.0 -m "MetaStrip v0.1.0"
   git push origin v0.1.0
   ```

6. Draft the GitHub release from `v0.1.0`. Summarize the supported formats, installation steps, and verification limits. Review the draft and publish it after approval.

Windows executable packaging, signing, and clean-machine binary testing belong to a future release.
