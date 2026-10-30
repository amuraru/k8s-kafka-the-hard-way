# Agent instructions

## Task and source of truth

- When the user requests local deployment, execute the playbook in [README.md](README.md). Do not stop after describing the commands.
- Continue until the acceptance checks below pass, or report a specific blocker with diagnostic evidence.
- For documentation-only requests, change documentation without starting a cluster.
- Use `README.md` for release pins, installation commands, namespaces, and service names.
- Use this checkout's YAML manifests. Do not download copies from another branch or recreate the removed setup script.
- Preserve the ZooKeeper-based architecture. A Kafka 4.x or KRaft migration requires a separate request.

## Safety and execution rules

- Default to the kind cluster `kafka` and Kubernetes context `kind-kafka`.
- Before deployment, inspect `git status`, `kind get clusters`, and the available Kubernetes contexts.
- Check that the target context belongs to the intended local kind cluster before every deployment phase.
- Set an explicit context and namespace on Kubernetes commands. Set `--kube-context` on Helm commands.
- Prefer a session-specific kubeconfig. Preserve the user's kubeconfig and its current context.
- Inspect existing clusters, Helm releases, and persistent volumes before deciding whether to reuse them.
- Ask before replacing an existing cluster, deleting persistent data, or changing an unrelated Kubernetes context.
- Ask before installing privileged host dependencies or changing Docker's resource allocation.
- Preserve existing repository changes and host configuration files, including `~/.kind/kind-config.yaml`.
- Use `kubectl` instead of the README's `k` shorthand. Do not assume shell aliases exist.
- Read each command before executing it. Example output, prompts, and historical pod names are not commands.
- Use non-interactive commands. Remove TTY flags from Kafka client examples when no terminal is available.
- Use bounded waits for readiness and command completion. Do not use an indefinite watch or a fixed sleep as proof of readiness.
- Inspect current state before retrying a failed step. Never suppress errors with blanket success handling.
- Keep the cluster running after deployment. Cleanup requires a separate user request.

## Before deployment

1. Read the complete README and the manifests that the playbook applies.
2. Check the host OS and architecture. Use the matching kind binary from the README's pinned release.
3. Check `docker info`, `kind version`, `kubectl version --client`, and `helm version`.
4. Check the README's Helm requirement and Kubernetes client compatibility rule.
5. Check access to the pinned charts, images, and CRD download URLs.
   Build a complete image inventory from the pinned Helm charts rendered with the installation values,
   the README, and this checkout's manifests. Include regular containers, init containers, Helm hooks,
   operator-generated workloads, metrics exporters, and Kafka clients. Inspect the pinned operators'
   defaults for injected helper images that do not appear in chart templates.
6. Check Docker's available CPU, memory, and disk against the manifests' resource requests and PVC sizes.
   Include all six Kafka brokers, three ZooKeeper members, Cruise Control, KMinion, and the monitoring stack.
   Kubernetes nodes inside kind share the Docker host's resources. Summed node capacities do not represent independent hosts.
   Include image-preload storage: host Docker images and each kind node's containerd image store consume
   disk space. Check both Docker filesystem space and the host space backing Docker's disk image.
   Include retained image blobs, unpacked snapshots, and temporary export archives, not only the reported
   image size. Imports can require approximately twice the uncompressed image size per node.
7. Report insufficient resources before deployment. Ask before reducing broker counts, replication, storage, or resource requests.
8. Use a temporary kind configuration if the README's configuration path already contains unrelated settings.

## Execute the README in dependency order

1. Create the seven-node cluster with the README's pinned node image and digest.
   Check that the control-plane node and all six workers reach `Ready`.
   Check that the `standard` StorageClass exists and supports dynamic provisioning.
2. Apply the region and zone labels from the README.
   Check that each of the three zones contains two workers.
   Before installing workloads, preload all images required by the setup into kind:
   - Pull the exact pinned image references for the Docker host's architecture. Do not substitute `latest`.
   - Reuse matching local images and images already present in kind instead of downloading them again.
   - Use `kind load docker-image --name kafka <image>...` to import the images into every cluster node.
     Use bounded batches or bounded concurrency so pulls and imports do not exhaust host resources.
   - Verify the required image references in each node's containerd store with `docker exec <node> crictl images`.
     A successful host-side `docker pull` alone does not make an image available to Kubernetes.
   - Check rendered image pull policies. Use `IfNotPresent` for these pinned local images where supported;
     preloading does not prevent registry access when a workload uses `Always`.
   - If the complete preload does not fit, report the disk shortfall and ask before deleting cached images
     or data. Do not silently skip images, reduce the topology, or preload unrelated host images.
   On reruns, preload only missing images. If a later phase reveals another injected image, preload it
   before continuing and add it to the inventory. Keep this inventory outside the repository unless requested.
   Storage-constrained exception approved for this setup: `monitoring-values.yaml` pins Grafana to
   `kafka-worker4`. Preload the Grafana image on that worker with `kind load docker-image --name kafka
   --nodes kafka-worker4 <grafana-image>` and verify it there. Other required images must be present on
   every node. If the Grafana node selector changes, preload its image on all newly eligible nodes first.
3. Install cert-manager's CRDs and Helm release.
   Wait for CRDs to become `Established` and for all cert-manager deployments to become available.
4. Install the ZooKeeper operator's CRD and Helm release.
   Wait for the operator before creating the three-member ZooKeeper cluster.
   Check the cluster's reported status, all three members, the client service, and bound PVCs.
5. Install the monitoring CRDs and the `monitoring` Helm release in `default`.
   Keep CRDs aligned with the chart's Prometheus Operator version.
   Wait for the operator, Prometheus, Grafana, and Alertmanager workloads to become ready.
6. Install KOperator's CRDs and Helm release in `kafka`.
   Wait for the operator before applying `simplekafkacluster.yaml` in `kafka`.
   Check that all six configured broker IDs register and that Cruise Control becomes ready.
7. Apply `kafkacluster-prometheus-monitoring.yaml` in `kafka`.
   Install the README's pinned Adobe KMinion chart in `kafka` using `kminion-values.yaml`.
   Preload its image first, wait for the deployment, and verify its selected ServiceMonitor
   and `kminion_exporter_up == 1`. Keep end-to-end probes disabled unless explicitly requested.
   Apply `zookeeper-prometheus-monitoring.yaml` in `zookeeper` to include ZooKeeper monitoring.
   Apply `grafana-dashboard.yaml` in `default`.
8. Establish the baseline with the Kafka smoke test below before applying `kafkacluster-prometheus-autoscale.yaml`.
   Check that Prometheus selects the rules and evaluates them without errors.
   Check that Alertmanager routes scaling alerts to KOperator's actual alert webhook.
   A PrometheusRule object alone does not establish a working autoscaling path.
9. Start the dashboard port-forwards described in the README.
   Bind them to loopback only. Record each process handle, log location, and stop command.
   Check each forwarded endpoint with an HTTP request before reporting its URL.

For reruns, reuse matching healthy resources instead of blindly repeating `create` or `helm install` commands.
Use the existing release's values when a Helm update is necessary.
Keep the README's explicit versions when adapting commands for a rerun.
Read each custom resource's status schema before selecting a readiness check. Not every resource exposes a `Ready` condition.

## Kafka smoke test

- Run Kafka clients inside the `kafka` namespace with the Kafka image from `simplekafkacluster.yaml`.
- Use the README's internal bootstrap address. An internal bootstrap service is not necessarily usable from the host.
- Create a uniquely named test topic with three partitions and replication factor three.
- Check topic metadata: every partition needs a leader and three in-sync replicas.
- Produce 100 uniquely identifiable records with `acks=all`.
- Consume from the beginning with a new consumer group and a bounded timeout.
- Check that the consumer receives all 100 records without corruption or duplicates.
- Check for offline partitions and under-replicated partitions after the test.
- Record the test topic and group names. Remove only temporary clients and test resources created by this run.
- Execute the README's large performance tests, broker termination tests, and deliberate scaling tests only on explicit request.

## Done means

- All seven nodes report `Ready`. All three ZooKeeper members and all six configured Kafka brokers report healthy status.
- All expected persistent claims report `Bound`. No required workload remains `Pending` or in `CrashLoopBackOff` or `ImagePullBackOff`.
- The smoke test receives exactly the 100 produced records. Its partitions retain three in-sync replicas.
- Required Kafka, Cruise Control, ZooKeeper, and KMinion scrape targets report `up == 1`.
  KMinion reports `kminion_exporter_up == 1` and exports the topic/group metrics used by Grafana.
  Prometheus evaluates the intended rules without errors. Alertmanager routes scaling alerts to KOperator.
- Prometheus, Grafana, Alertmanager, and Cruise Control respond through the recorded local port-forwards.
  Grafana loads the `Kafka Looking Glass` dashboard with live Kafka data, not only an HTTP success response.

## Diagnose failures and report results

- On failure, inspect pod events, container logs, operator logs, custom resource status, Helm status, and PVC binding.
- Check selectors, namespace discovery, service ports, and exporter metric names when monitoring shows no data.
- Check the installed Prometheus rule selector against the autoscaling manifest's labels.
- Fix reproducible playbook defects with minimal README or manifest changes. Preserve version pins unless the user approves an upgrade.
- Do not hide failures by removing health checks, disabling components, or silently changing the topology.
- After a timeout, report the failing resource, relevant logs, and the next required action. Do not report the deployment as complete.
- In the final report, include the context, deployed versions, readiness results, smoke-test results, and dashboard URLs.
- Include port-forward process details and any remaining warnings or manual actions.
- Explain how to retrieve the Grafana password from its Secret. Do not copy secret values into reports or repository files.
- Distinguish live-cluster validation from static YAML checks and Helm rendering.

## Keep related files consistent

| Change | Also check |
| --- | --- |
| Kafka image | `simplekafkacluster.yaml`, `kafkacluster-prometheus-autoscale.yaml`, and README client examples |
| Operator or chart release | README version table, install commands, and corresponding CRD URLs |
| Metrics, labels, or namespaces | Both monitoring manifests, `kminion-values.yaml`, autoscaling rules, and `grafana-dashboard.yaml` |

For repository changes, run `git diff --check`. Check changed YAML and embedded dashboard JSON for syntax errors.
For deployment changes, repeat the affected live acceptance checks.
