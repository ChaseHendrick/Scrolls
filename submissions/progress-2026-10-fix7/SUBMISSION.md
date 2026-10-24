# Submission and release process

This document describes how the contribution package is prepared for a Vesuvius Challenge Progress Prize submission. It does not itself assert that a form was submitted or that an award was made.

## Submit the correct entry

Check the current [official Progress Prize rules](https://scrollprize.org/prizes#progress-prizes) and follow the submission form linked there. Explain the concrete problem, data, implementation, demonstrated benefit and evidence. Supply accessible contribution links, installation instructions, examples, dependency versions and attribution. The submitter completes identity/team information and accepts the form's terms personally.

Keep negative results, comparison settings and limitations with the measurements. A completed run, a passing software test or a feature list is not proof of a better reading method. Explain which components are original contributions and which use existing community work.

## Package and release

Before submission, the owner reviews a finite set of public files: source, tests, documentation, small sanitized measurements and license/attribution notices. A manifest binds those exact bytes. The release step transfers that package into a new branch of the public repository and verifies the resulting commit before its URL is entered in the form.

Only selected public files are transferred. Research history, contact information, credentials, billing, operational identifiers and unrelated work are excluded. Raw scans, meshes, renders, maps, masks, labels and model weights are not committed to Git. Any separately distributed artifact needs an accessible, authorized release and its own license and checksum.

The package's `release.json` records its identity and file hashes. Its prepared state does not imply form submission. Actual confirmation is recorded separately. If submission fails after the package goes public, the release remains public and is not relabeled as submitted.

## Reproduce and correct

Use the package README for exact setup and reproduction instructions. Verify input sources, versions, controls and evaluation scope. Report a discrepancy with the package commit and reproduction steps, without sharing private data.

A corrected package should preserve the original evidence and identify what changed. Release automation must not overwrite an existing reviewed package silently. A new revision receives a separately reviewed identity.

This workflow is for Progress Prize software and evidence. Possible discoveries for the milestone prizes follow their separate disclosure rules; this procedure does not authorize publishing them.
