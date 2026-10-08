# Optional DigitalOcean workspace for Modal

Recorded 2026-10-08.

**Status: unvalidated fallback procedure.** End-to-end DigitalOcean provisioning, Codex connection and Modal access have not been validated for this repository.

## Why keep this option

A DigitalOcean Droplet can provide a replacement development host when another workspace is unavailable or unsuitable. It would hold the checkout, Python environment and command-line tools used to prepare work and control Modal jobs.

DigitalOcean is optional. A working local computer or another suitable host can perform the same role. Modal runs its remote compute separately; a GPU Droplet is not required merely to launch or monitor Modal jobs.

This guide records a reusable setup option. It does not authorize a server rental or a training run.

## Before provisioning

1. Check whether an existing host can do the work.
2. Confirm the installed Codex DigitalOcean app is authenticated and its SSH-key and Droplet tools are callable. An installed plugin or successful browser sign-in does not establish that a workspace exists or that these tools are available.
3. Read the current installed DigitalOcean provisioning skill and follow its supported app tools and SSH setup. Use the current workflow rather than copying old image identifiers, size availability or integration configuration.
4. Check the proposed region, CPU, memory, disk, current price and intended lifetime. Obtain any budget decision that is not already authorized.
5. Check the Modal account, current usage and remaining authorized compute budget separately. DigitalOcean hosting and Modal compute are separate costs.

## Prepare and verify the host

Use the installed provisioning workflow to create the selected host, wait for initialization, configure SSH and connect the workspace to Codex. Run any local SSH setup on the machine whose SSH configuration Codex will use.

Once connected:

1. Verify that commands execute on the intended host and that its memory, disk and network access meet the workload.
2. Clone the correct repository, select the intended commit and read `AGENTS.md` and the current handoff.
3. Create a Python virtual environment and install Modal using its current installation instructions.
4. Reuse valid Modal authentication where available; otherwise complete Modal setup. Keep credentials and SSH private keys outside Git and logs.
5. Verify the intended Modal profile and use read-only app and volume listings to check access before launching compute.
6. Restore required artifacts into ignored directories. Check recorded hashes, required files and checkpoint readability before declaring recovery complete.
7. Run the repository's relevant preparation checks before starting an authorized job.

Keep private repositories, research material and operational details in their authorized locations. This public repository does not contain the private restore instructions or artifacts.

## Completion and cleanup

Record which checks passed and which remain pending. A reachable host, a connected Modal account, a recoverable checkpoint and a running training job are separate states.

Before retiring the host, verify that required work has been saved elsewhere. Confirm current provider billing and the resources that remain chargeable. Follow the installed workflow's cleanup instructions and obtain authorization before deleting a Droplet or its data.

## Official references

- [DigitalOcean Droplets documentation](https://docs.digitalocean.com/products/droplets/)
- [DigitalOcean SSH connection guide](https://docs.digitalocean.com/products/droplets/how-to/connect-with-ssh/)
- [DigitalOcean Droplet pricing](https://www.digitalocean.com/pricing/droplets)
- [Modal installation and setup](https://modal.com/docs/guide)
- [Modal CLI reference](https://modal.com/docs/reference/cli)
- [Modal pricing](https://modal.com/pricing)

Provider capabilities, prices and the installed Codex workflow can change. Recheck them when using this guide.
