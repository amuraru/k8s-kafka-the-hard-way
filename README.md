**Inspired by Kelsey Hightower's [kubernetes-the-hard-way](https://github.com/kelseyhightower/kubernetes-the-hard-way), this tutorial walks you through setting up Kafka on K8s using [BanzaiCloud Kafka Operator](https://github.com/banzaicloud/kafka-operator) on a local [`kind`](https://kind.sigs.k8s.io/) cluster.** 


- [Intro](#intro)
  - [Software versions](#software-versions)
- [Install Kafka in a `kind` k8s cluster](#install-kafka-in-a-kind-k8s-cluster)
  - [Install `kind`](#install-kind)
  - [Create a mini k8s cluster using `kind`](#create-a-mini-k8s-cluster-using-kind)
    - [Create cluster configuration](#create-cluster-configuration)
    - [Start k8s kind cluster](#start-k8s-kind-cluster)
    - [Access k8s](#access-k8s)
  - [Emulate multi-az nodes](#emulate-multi-az-nodes)
- [BanzaiCloud KOperator](#banzaicloud-koperator)
  - [Install pre-reqs](#install-pre-reqs)
    - [Install `cert-manager`](#install-cert-manager)
    - [Install Pravega `zookeeper-operator`](#install-pravega-zookeeper-operator)
      - [Create a ZK cluster with 3 zk nodes](#create-a-zk-cluster-with-3-zk-nodes)
    - [Install Prometheus Operator](#install-prometheus-operator)
      - [Access the dashboards](#access-the-dashboards)
        - [Prometheus](#prometheus)
          - [View all metrics in Prometheus](#view-all-metrics-in-prometheus)
        - [Grafana](#grafana)
        - [Alert Manager](#alert-manager)
  - [BanzaiCloud KOperator](#banzaicloud-koperator-1)
      - [Create a KafkaCluster](#create-a-kafkacluster)
      - [Install Adobe KMinion](#install-adobe-kminion)
      - [Create Prometheus `ServiceMonitor` and AlertManager `PrometheusRule` resources](#create-prometheus-servicemonitor-and-alertmanager-prometheusrule-resources)
      - [Create `PrometheusRule` to enable auto-scaling](#create-prometheusrule-to-enable-auto-scaling)
      - [Load Grafana `Kafka Looking Glass` dashboard](#load-grafana-kafka-looking-glass-dashboard)
      - [Check Cruise Control](#check-cruise-control)
      - [Check Prometheus metrics for kafka](#check-prometheus-metrics-for-kafka)
    - [Debugging](#debugging)
      - [Verify pod images](#verify-pod-images)
    - [Kafka samples](#kafka-samples)
      - [List topics](#list-topics)
      - [Create topic](#create-topic)
      - [Set custom topic retention period](#set-custom-topic-retention-period)
      - [Topic Describe](#topic-describe)
      - [Start Producer perf test](#start-producer-perf-test)
      - [Start Consumer perf test](#start-consumer-perf-test)
      - [Check out Grafana dashboard](#check-out-grafana-dashboard)
- [Disaster scenarios](#disaster-scenarios)
  - [Initial state](#initial-state)
  - [Broker JVM dies, is PV/PVC re-used?](#broker-jvm-dies-is-pvpvc-re-used)
  - [Broker pod deleted, is PV/PVC re-used?](#broker-pod-deleted-is-pvpvc-re-used)

# Intro

This is a quick tutorial on how to run [the fine piece BanzaiCloud Kafka-Operator](https://github.com/banzaicloud/koperator) in a local multi-node kind cluster.

## Software versions

Release pins checked on 2026-10-30:

| Component | Version |
| --- | --- |
| [kind](https://github.com/kubernetes-sigs/kind/releases/tag/v0.33.0) | 0.33.0 |
| Helm | 4.3.1 |
| Kubernetes (kind node image) | 1.36.4 |
| [cert-manager](https://github.com/cert-manager/cert-manager/releases/tag/v1.21.3) | 1.21.3 |
| [ZooKeeper operator](https://github.com/adobe/zookeeper-operator/releases/tag/0.2.15-adobe-20260924) | 0.2.15-adobe-20260924 |
| ZooKeeper | 3.9.6 |
| [kube-prometheus-stack](https://github.com/prometheus-community/helm-charts/releases/tag/kube-prometheus-stack-92.16.0) | 92.16.0 (Prometheus Operator 0.94.2) |
| Prometheus (bundled with monitoring chart) | 3.15.1 |
| Grafana (bundled with monitoring chart) | 13.3.0 |
| Alertmanager (bundled with monitoring chart) | 0.34.2 |
| [KOperator](https://github.com/adobe/koperator/releases/tag/0.32.0) | 0.32.0 |
| [Adobe KMinion image and chart](https://github.com/adobe/kminion/releases/tag/2.3.4-adobe-20261026) | 2.3.4-adobe-20261026 |
| Kafka image | 2.13-3.9.2-jdk21.0.12 |
| [Cruise Control](https://github.com/adobe/cruise-control/releases/tag/3.1.0-adbe-20261029) | 3.1.0-adbe-20261029 |

Kafka stays on the 3.9 release line because this tutorial uses ZooKeeper; Kafka 4.x requires a separate KRaft migration. Kubernetes 1.36.4 is the newest 1.36 image published for kind 0.33.0 and stays within cert-manager 1.21's [supported Kubernetes versions](https://cert-manager.io/docs/releases/). Prometheus, Grafana, and Alertmanager use the versions bundled with the pinned monitoring chart. Use Helm 4 and a kubectl client within one minor version of the cluster.

For this constrained local setup, Kafka requests 1 GiB per broker and ZooKeeper requests 1 GiB per member. These sizes are intended for smoke tests, not the performance tests below. The kind `standard` StorageClass uses local-path storage; PVC sizes do not enforce disk quotas, so monitor actual Docker disk usage.

`monitoring-values.yaml` pins the single Grafana replica to `kafka-worker4` so its image needs to be preloaded only on that worker. Other required setup images are preloaded on all seven kind nodes. If you change Grafana's placement, preload its image on the newly eligible nodes before changing the selector.

These instructions create a fresh cluster. For an existing cluster, follow each project's upgrade instructions and back up persistent data before applying the new versions.

Run the manifest commands below from the root of this repository checkout so they use the same release pins.


# Install Kafka in a `kind` k8s cluster

## Install `kind`

- Check https://github.com/kubernetes-sigs/kind
- Docker required (kind runs nodes and control plane as local docker containers)

```bash

# Select the binary for Linux/macOS and Intel/ARM hosts.
os=$(uname -s | tr '[:upper:]' '[:lower:]')
case "$(uname -m)" in
  x86_64) arch=amd64 ;;
  arm64|aarch64) arch=arm64 ;;
  *) echo "Unsupported architecture" >&2; exit 1 ;;
esac
# renovate: datasource=github-releases depName=kubernetes-sigs/kind
curl -fLo ./kind "https://github.com/kubernetes-sigs/kind/releases/download/v0.33.0/kind-${os}-${arch}"
chmod +x ./kind
mkdir -p ~/bin
mv ./kind ~/bin
export PATH="$HOME/bin:$PATH"
kind version

```

## Create a mini k8s cluster using `kind`


### Create cluster configuration
```bash
mkdir -p ~/.kind
# Create a 7-node cluster: one control plane and six workers.
cat > ~/.kind/kind-config.yaml <<EOF
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
  - role: control-plane
    labels:
      ingress-ready: "true"
  - role: worker
  - role: worker
  - role: worker
  - role: worker
  - role: worker
  - role: worker
EOF
```

### Start k8s kind cluster

```sh
kind create cluster \
--name kafka \
--config ~/.kind/kind-config.yaml \
`# renovate: datasource=docker depName=kindest/node ` \
--image kindest/node:v1.36.4@sha256:099e049362a1526b2db71494e1947aae99bd16290d7c895f2b7ea312e3cbfaed
```

Once the cluster is created your `KUBECONFIG` is updated to include
the new `kind-kafka` cluster context.

Run `kubectl cluster-info --context kind-kafka` to get more info.

Debug: `kind` clusters are running in docker, check containers: `docker ps`

### Access k8s

```sh
# switch to kind cluster context
kubectl config use-context kind-kafka
# test
k get nodes

# To dump kubeconfig
kind get kubeconfig --name kafka

```


## Emulate multi-az nodes

```bash
# place all nodes in the same region
kubectl label nodes kafka-worker kafka-worker2 kafka-worker3 kafka-worker4  kafka-worker5 kafka-worker6 topology.kubernetes.io/region=region1

# emulate 3 AZs:
kubectl label nodes kafka-worker  kafka-worker2 topology.kubernetes.io/zone=az1
kubectl label nodes kafka-worker3 kafka-worker4 topology.kubernetes.io/zone=az2
kubectl label nodes kafka-worker5 kafka-worker6 topology.kubernetes.io/zone=az3

# check
kubectl get nodes --label-columns topology.kubernetes.io/region,topology.kubernetes.io/zone
```


# BanzaiCloud KOperator

## Install pre-reqs

**Note: The installation below assumes you're using Helm 4.**

### Install `cert-manager`

See https://cert-manager.io/docs/installation/kubernetes/#steps

```sh
# Install separately CRDs
# renovate: datasource=github-releases depName=cert-manager/cert-manager
kubectl apply --server-side -f https://github.com/cert-manager/cert-manager/releases/download/v1.21.3/cert-manager.crds.yaml
kubectl create namespace cert-manager

# Install operator using Helm 4
helm repo add cert-manager https://charts.jetstack.io
helm repo update
# renovate: datasource=github-releases depName=cert-manager/cert-manager
helm install cert-manager cert-manager/cert-manager --namespace cert-manager --version v1.21.3
```

### Install Pravega `zookeeper-operator`

Make sure you use **Helm 4**.

```sh
kubectl create ns zookeeper
kubectl apply --server-side -f https://raw.githubusercontent.com/adobe/zookeeper-operator/0.2.15-adobe-20260924/config/crd/bases/zookeeper.pravega.io_zookeeperclusters.yaml

helm install zookeeper-operator --namespace=zookeeper \
--set crd.create=false \
--set image.repository='ghcr.io/adobe/zookeeper-operator' \
--set image.tag='0.2.15-adobe-20260924' \
--version 0.2.15-adobe-20260924 \
oci://ghcr.io/adobe/helm-charts/zookeeper-operator
```

#### Create a ZK cluster with 3 zk nodes

```sh
kubectl create --namespace zookeeper -f - <<EOF
apiVersion: zookeeper.pravega.io/v1beta1
kind: ZookeeperCluster
metadata:
  name: zk
  namespace: zookeeper
spec:
  replicas: 3
  image:
    repository: ghcr.io/adobe/zookeeper-operator/zookeeper
    # renovate: datasource=docker depName=ghcr.io/adobe/zookeeper-operator/zookeeper
    tag: 3.9.6-0.2.15-adobe-20260924
    pullPolicy: IfNotPresent
  config:
    initLimit: 10
    tickTime: 2000
    syncLimit: 5
  probes:
    livenessProbe:
      initialDelaySeconds: 41
  persistence:
    reclaimPolicy: Delete
    spec:
      accessModes:
      - ReadWriteOnce
      resources:
        requests:
          storage: 1Gi
EOF


# Check
kubectl get all -n zookeeper
# ZookeeperCluster up?
kubectl get -w zookeepercluster -n zookeeper -o wide
# Good
```

See more at https://github.com/adobe/zookeeper-operator


### Install Prometheus Operator

```sh

# Match CRDs to the Prometheus Operator bundled with the chart.
kubectl apply --server-side -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/v0.94.2/example/prometheus-operator-crd/monitoring.coreos.com_alertmanagers.yaml
kubectl apply --server-side -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/v0.94.2/example/prometheus-operator-crd/monitoring.coreos.com_alertmanagerconfigs.yaml
kubectl apply --server-side -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/v0.94.2/example/prometheus-operator-crd/monitoring.coreos.com_prometheuses.yaml
kubectl apply --server-side -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/v0.94.2/example/prometheus-operator-crd/monitoring.coreos.com_prometheusrules.yaml
kubectl apply --server-side -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/v0.94.2/example/prometheus-operator-crd/monitoring.coreos.com_servicemonitors.yaml
kubectl apply --server-side -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/v0.94.2/example/prometheus-operator-crd/monitoring.coreos.com_podmonitors.yaml
kubectl apply --server-side -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/v0.94.2/example/prometheus-operator-crd/monitoring.coreos.com_thanosrulers.yaml
kubectl apply --server-side -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/v0.94.2/example/prometheus-operator-crd/monitoring.coreos.com_probes.yaml
kubectl apply --server-side -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/v0.94.2/example/prometheus-operator-crd/monitoring.coreos.com_prometheusagents.yaml
kubectl apply --server-side -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/v0.94.2/example/prometheus-operator-crd/monitoring.coreos.com_scrapeconfigs.yaml

helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update
helm install monitoring --namespace=default prometheus-community/kube-prometheus-stack --version 92.16.0 --set crds.enabled=false -f monitoring-values.yaml

```

#### Access the dashboards

Prometheus, Grafana, and Alertmanager dashboards can be accessed quickly using `kubectl port-forward` after running the quickstart via the commands below.


##### Prometheus

```
kubectl --namespace default port-forward svc/monitoring-kube-prometheus-prometheus 9090
```

Then access via [http://localhost:9090](http://localhost:9090)

###### View all metrics in Prometheus

http://localhost:9090/api/v1/label/__name__/values

##### Grafana

```
# get admin password
kubectl get secret --namespace default monitoring-grafana -o jsonpath="{.data.admin-password}" | base64 --decode ; echo
# proxy
kubectl --namespace default port-forward svc/monitoring-grafana 3000:80
```

Then access via [http://localhost:3000](http://localhost:3000) with user `admin` and the password retrieved from the Secret above.

#####  Alert Manager

```
kubectl --namespace default port-forward svc/monitoring-kube-prometheus-alertmanager 9093
```

Then access via [http://localhost:9093](http://localhost:9093)

```
# check all resources created by helm release
k get all -A -l release=monitoring

```


## BanzaiCloud KOperator

```sh
# new kafka NS
kubectl create ns kafka

# install CRDs first
kubectl apply --server-side=true -f https://raw.githubusercontent.com/adobe/koperator/0.32.0/config/base/crds/kafka.banzaicloud.io_cruisecontroloperations.yaml
kubectl apply --server-side=true -f https://raw.githubusercontent.com/adobe/koperator/0.32.0/config/base/crds/kafka.banzaicloud.io_kafkaclusters.yaml
kubectl apply --server-side=true -f https://raw.githubusercontent.com/adobe/koperator/0.32.0/config/base/crds/kafka.banzaicloud.io_kafkatopics.yaml
kubectl apply --server-side=true -f https://raw.githubusercontent.com/adobe/koperator/0.32.0/config/base/crds/kafka.banzaicloud.io_kafkausers.yaml

# install operator using OCI helm chart
helm install kafka-operator  \
--namespace=kafka \
--set webhook.enabled=false \
--version 0.32.0 \
oci://ghcr.io/adobe/helm-charts/kafka-operator

# Check
kubectl get all -n kafka
# Good

```


### Create a KafkaCluster

```
kubectl create -n kafka -f simplekafkacluster.yaml
# Check CRD created
k get KafkaCluster kafka -n kafka -w -o wide
# See CRD state
k describe KafkaCluster kafka -n kafka

```

#### Install Adobe KMinion

[Adobe KMinion](https://github.com/adobe/kminion) collects broker, topic, consumer-group,
lag, and replica-log-size metrics through the Kafka API. Install it after Kafka is healthy
and the Prometheus Operator CRDs are established. Both its OCI chart and container image
are pinned to `2.3.4-adobe-20261026`; the explicit image override in
`kminion-values.yaml` avoids relying on the chart's image default.

```sh
docker pull ghcr.io/adobe/kminion:2.3.4-adobe-20261026
kind load docker-image --name kafka ghcr.io/adobe/kminion:2.3.4-adobe-20261026

helm install kminion oci://ghcr.io/adobe/helm-charts/kminion \
  --namespace kafka --kube-context kind-kafka \
  --version 2.3.4-adobe-20261026 \
  -f kminion-values.yaml --wait --timeout 180s

kubectl --context kind-kafka --namespace kafka \
  rollout status deployment/kminion --timeout=180s
kubectl --context kind-kafka --namespace kafka \
  get deployment/kminion service/kminion servicemonitor/kminion

# Once Prometheus has scraped the exporter, expect kminion_exporter_up == 1.
kubectl --context kind-kafka --namespace default get --raw \
  '/api/v1/namespaces/default/services/monitoring-kube-prometheus-prometheus:9090/proxy/api/v1/query?query=kminion_exporter_up'
```

The values use the internal bootstrap service, a single exporter replica, partition-level
topic/group metrics, and `adminApi` consumer-group scraping. The chart creates its
ServiceMonitor with `release: monitoring`; target relabeling adds `kafka_cr="kafka"`
so dashboard queries can select this cluster. No external bootstrap port-forward is needed.

KMinion's continuous end-to-end producer/consumer probes are disabled. They would create
and manage a probe topic and generate ongoing traffic; enable them separately only after
checking storage and the known autoscaling behavior. Consumer lag is a committed-offset
measurement, not the broker-to-broker replication lag exposed by Kafka JMX.

`Kafka Looking Glass` uses these KMinion metrics directly, without private recording-rule aliases:

| Dashboard data | Metric |
| --- | --- |
| Kafka API scrape health | `kminion_exporter_up` |
| Consumer-group count | `kminion_kafka_consumer_group_info_count` |
| Committed-offset lag by group/topic | `kminion_kafka_consumer_group_topic_lag` |
| Topic partition counts | `kminion_kafka_topic_info_partitions_count` |
| Broker replica-log bytes | `kminion_kafka_broker_log_dir_size_total_bytes` |
| Topic replica-log bytes | `kminion_kafka_topic_log_dir_size_total_bytes` |

Broker/topic selectors use KMinion's `broker_id` and `topic_name` labels. Kafka JMX panels
continue to use `brokerId`, `topic`, and `partition`; the dashboard translates the selected
IDs rather than matching generated pod-name suffixes.

For reruns, inspect `helm list --namespace kafka --kube-context kind-kafka` first.
Reuse a healthy matching release; if changing values, preserve the release's existing values
and retain the pinned chart/image versions. Inspect
`kubectl --context kind-kafka --namespace kafka logs deployment/kminion --tail=100`
and the Prometheus target error if scraping fails.

#### Create Prometheus `ServiceMonitor` and AlertManager `PrometheusRule` resources

```sh
kubectl apply -n kafka \
-f kafkacluster-prometheus-monitoring.yaml

kubectl apply -n zookeeper \
-f zookeeper-prometheus-monitoring.yaml
```

#### Create `PrometheusRule` to enable auto-scaling

Run the Kafka smoke test before enabling these rules. The monitoring values route scaling alerts
to `http://kafka-operator-alertmanager.kafka.svc:9001/`, the alert receiver installed by the
pinned KOperator chart. The rules must have `release: monitoring` so Prometheus selects them.
The webhook's custom `payload` sends the flat alert array expected by KOperator 0.32.0;
Alertmanager's default webhook envelope is not compatible with that receiver.
Do not deliberately trigger scaling or run the performance tests without checking disk capacity.

Known caveat with the pinned sample rules/operator: background broker requests can exceed the
sample overload threshold even without client traffic. A `PartitionCountLow` alert without
`brokerId` can also hit KOperator 0.32.0's failing fallback broker-selection path. Successful
webhook delivery alone does not validate scale-up/down command execution. Inspect operator
logs and current broker assignments before relying on these rules; do not remove an
automatically added broker or its PVC without checking for data and obtaining approval.

```sh
kubectl apply -n kafka \
-f kafkacluster-prometheus-autoscale.yaml
```


#### Load Grafana `Kafka Looking Glass` dashboard

```sh
kubectl apply -n default \
-f grafana-dashboard.yaml
```
This needs to be created in the same namespace as `grafana` (`default`)

Dashboard should be automatically loaded and available at http://127.0.0.1:3000/d/1a1a1a1a1/kafka-looking-glass

The dashboard ConfigMap uses `grafana_dashboard: '1'`, matching the pinned chart's sidecar selector.
Its defaults select the local `kafka` namespace and cluster, and ZooKeeper panels query `zookeeper`.

Local monitoring limitations:

- The kind local-path provisioner does not expose `kubelet_volume_stats_*` for these PVCs. The dashboard therefore shows KMinion replica-log bytes and requested PVC capacity, clearly labeled as requests rather than quotas or physical free space. Indexes and other files are not included. `RemainingDiskSpaceLow` still has no volume-stat data; check actual disk usage separately. An error-free rule evaluation does not establish disk-based autoscaling.
- Default kind metrics listeners for the controller manager, scheduler, etcd, and kube-proxy are loopback-only. The monitoring chart's corresponding targets remain unreachable until those listeners are reconfigured. Kafka, Cruise Control, and ZooKeeper scraping does not depend on them.
- Envoy, Adobe IMS, and assignment-aware orphan-replica telemetry are not installed. Their panels explicitly show `Not configured`, with original queries retained but not executed, instead of implying a healthy zero or showing an unexplained empty graph. KMinion scrape health is not an external end-to-end availability probe.

Healthy zero-valued counters (digest mismatches, replication lag, failures, reassignments,
and offline log directories) are displayed as zero from real metric samples. Filters such
as `> 0` are not used to discard those healthy samples. Legacy Angular `graph` and `table-old`
panels have been migrated to current time-series/table panels for Grafana 13, including the
panels inside collapsed rows. Run the dashboard regression tests
with `python3 -B -m unittest discover -s tests -v` after changing queries or variables.

#### Check Cruise Control

```
kubectl -n kafka port-forward -n kafka svc/kafka-cruisecontrol-svc 18090:8090
```

#### Check Prometheus metrics for kafka

```sh
kubectl port-forward -n default svc/prometheus-operated 19090:9090
# http://10.131.236.142:19090/graph?g0.range_input=1h&g0.expr=%7B__name__%20%3D~%27kafka.*%27%7D&g0.tab=1

```


### Debugging


```sh

kubectl config set-context --current --namespace=kafka

# See operator logs
k logs  -l app.kubernetes.io/instance=kafka-operator  -c  manager -f
```


#### Verify pod images

```sh
kubectl get pod -o=custom-columns='NAME:.metadata.name,IMAGE:.spec.containers[*].image' --all-namespaces
```


### Kafka samples

#### List topics

```bash
kubectl run kafka-topics --rm -i --tty=true \
--image=ghcr.io/adobe/koperator/kafka:2.13-3.9.2-jdk21.0.12 \
--restart=Never \
-- /opt/kafka/bin/kafka-topics.sh \
--bootstrap-server kafka-headless:29092 \
--list
```

#### Create topic

```bash
kubectl run kafka-topics --rm -i --tty=true \
--image=ghcr.io/adobe/koperator/kafka:2.13-3.9.2-jdk21.0.12 \
--restart=Never \
-- /opt/kafka/bin/kafka-topics.sh \
--bootstrap-server kafka-headless:29092 \
--topic perf_topic \
--replica-assignment 101:201:301,102:202:302,101:201:301,102:202:302,101:201:301,102:202:302,101:201:301,102:202:302,101:201:301,102:202:302,101:201:301,102:202:302 \
--create
```

#### Set custom topic retention period

```bash
kubectl run kafka-topics --rm -i --tty=true \
--image=ghcr.io/adobe/koperator/kafka:2.13-3.9.2-jdk21.0.12 \
--restart=Never \
-- /opt/kafka/bin/kafka-configs.sh \
--bootstrap-server kafka-headless:29092 \
--alter --entity-name perf_topic \
--entity-type topics \
--add-config retention.ms=720000
```

#### Topic Describe

```bash
kubectl run kafka-topics --rm -i --tty=true \
--image=ghcr.io/adobe/koperator/kafka:2.13-3.9.2-jdk21.0.12 \
--restart=Never \
-- /opt/kafka/bin/kafka-topics.sh \
--bootstrap-server kafka-headless:29092 \
--topic perf_topic \
--describe
```

#### Start Producer perf test

```bash
kubectl run kafka-producer-topic \
--image=ghcr.io/adobe/koperator/kafka:2.13-3.9.2-jdk21.0.12 \
--restart=Never \
-- /opt/kafka/bin/kafka-producer-perf-test.sh \
--producer-props bootstrap.servers=kafka-headless:29092 acks=all \
--topic perf_topic \
--record-size 1000 \
--throughput 29000 \
--num-records 21100000000
```

#### Start Consumer perf test

```bash
kubectl run kafka-consumer-test \
--image=ghcr.io/adobe/koperator/kafka:2.13-3.9.2-jdk21.0.12 \
--restart=Never \
-- /opt/kafka/bin/kafka-consumer-perf-test.sh \
--broker-list kafka-headless:29092 \
--group perf-consume \
--messages 10000000000 \
--topic perf_topic \
--show-detailed-stats \
--from-latest \
--timeout 100000
```

#### Check out Grafana dashboard

http://127.0.0.1:3000/d/1a1a1a1a1/kafka-looking-glass

# Disaster scenarios

## Initial state

```sh
# Get Kakfa broker pods
k get pod -l kafka_cr=kafka
NAME         READY   STATUS    RESTARTS   AGE
kafka7fwkf   1/1     Running   0          6h3m
kafka8dksv   1/1     Running   0          6h
kafka9kp6q   1/1     Running   0          6h1m
kafkas6gh4   1/1     Running   0          6h2m
kafkavbsff   1/1     Running   0          6h3m
kafkawn4l6   1/1     Running   0          6h2m

# Get PV and PVC
k get pv,pvc  | grep standard

persistentvolume/pvc-0965737b-0886-4599-99e7-a5dec34b29bb   10Gi       RWO            Delete           Bound    kafka/kafka-301-storage-0-v2w79   standard                19m
persistentvolume/pvc-1adee862-67a3-4be3-85a2-d2048aa71330   10Gi       RWO            Delete           Bound    kafka/kafka-101-storage-0-pss4m   standard                24m
persistentvolume/pvc-2fc31ae1-de91-43dd-a029-d938b7fc9b67   20Gi       RWO            Delete           Bound    zookeeper/data-zk-2               standard                37m
persistentvolume/pvc-314bca5b-8b1e-47cd-b928-a4a2dd85a6c4   10Gi       RWO            Delete           Bound    kafka/kafka-202-storage-0-2r8vm   standard                19m
persistentvolume/pvc-485d4ca7-4129-43a5-b98f-db23ea87a36c   10Gi       RWO            Delete           Bound    kafka/kafka-201-storage-0-nw8vd   standard                19m
persistentvolume/pvc-4e99bb66-161c-4573-bdab-1d44455eeb4f   10Gi       RWO            Delete           Bound    kafka/kafka-302-storage-0-8tsdt   standard                19m
persistentvolume/pvc-9d53fa44-ca21-4bb8-a036-feecee95500a   20Gi       RWO            Delete           Bound    zookeeper/data-zk-1               standard                38m
persistentvolume/pvc-a4b70cdf-28be-4c7c-b18b-1fb070624649   20Gi       RWO            Delete           Bound    zookeeper/data-zk-0               standard                39m
persistentvolume/pvc-fb0571c5-3fe8-4dbc-8ea8-9cf93b8ad2e9   10Gi       RWO            Delete           Bound    kafka/kafka-102-storage-0-qc8bj   standard                19m
persistentvolumeclaim/kafka-101-storage-0-pss4m   Bound    pvc-1adee862-67a3-4be3-85a2-d2048aa71330   10Gi       RWO            standard       24m
persistentvolumeclaim/kafka-102-storage-0-qc8bj   Bound    pvc-fb0571c5-3fe8-4dbc-8ea8-9cf93b8ad2e9   10Gi       RWO            standard       24m
persistentvolumeclaim/kafka-201-storage-0-nw8vd   Bound    pvc-485d4ca7-4129-43a5-b98f-db23ea87a36c   10Gi       RWO            standard       24m
persistentvolumeclaim/kafka-202-storage-0-2r8vm   Bound    pvc-314bca5b-8b1e-47cd-b928-a4a2dd85a6c4   10Gi       RWO            standard       24m
persistentvolumeclaim/kafka-301-storage-0-v2w79   Bound    pvc-0965737b-0886-4599-99e7-a5dec34b29bb   10Gi       RWO            standard       24m
persistentvolumeclaim/kafka-302-storage-0-8tsdt   Bound    pvc-4e99bb66-161c-4573-bdab-1d44455eeb4f   10Gi       RWO            standard       24m


```

## Broker JVM dies, is PV/PVC re-used?


Is the underlying PV/PVC retained and broker pod is rescheduled?
**PASSSED**

```sh
# Kill one broker JVM
k exec -it kafka7fwkf -- kill 1

# Pod is recreated
NAME         READY   STATUS    RESTARTS   AGE
kafka8dksv   1/1     Running   0          6h2m
kafka9kp6q   1/1     Running   0          6h4m
kafkap4h7p   1/1     Running   0          56s  # <----
kafkas6gh4   1/1     Running   0          6h4m
kafkavbsff   1/1     Running   0          6h5m
kafkawn4l6   1/1     Running   0          6h4m


# PV/PVC reused, attached to the new POD : Good!

k get pv,pvc  | grep examplestorageclass
persistentvolume/pvc-1e0b15df-0236-11ea-93d3-0242ac110002   100Gi      RWO            Retain           Bound    kafka/kafka-storager5t9v                    examplestorageclass            7h7m
persistentvolume/pvc-3ab64754-0236-11ea-93d3-0242ac110002   100Gi      RWO            Retain           Bound    kafka/kafka-storage7g8xd                    examplestorageclass            7h6m
persistentvolume/pvc-3ae3ae0c-0236-11ea-93d3-0242ac110002   100Gi      RWO            Retain           Bound    kafka/kafka-storage6sss6                    examplestorageclass            7h6m
persistentvolume/pvc-3b5fd2ad-0236-11ea-93d3-0242ac110002   100Gi      RWO            Retain           Bound    kafka/kafka-storagezs7r7                    examplestorageclass            7h6m
persistentvolume/pvc-a102806f-0239-11ea-93d3-0242ac110002   100Gi      RWO            Retain           Bound    kafka/kafka-storagecp57b                    examplestorageclass            6h42m
persistentvolume/pvc-a12dafe5-0239-11ea-93d3-0242ac110002   100Gi      RWO            Retain           Bound    kafka/kafka-storagekg5j8                    examplestorageclass            6h42m
persistentvolumeclaim/kafka-storage6sss6   Bound    pvc-3ae3ae0c-0236-11ea-93d3-0242ac110002   100Gi      RWO            examplestorageclass   7h6m
persistentvolumeclaim/kafka-storage7g8xd   Bound    pvc-3ab64754-0236-11ea-93d3-0242ac110002   100Gi      RWO            examplestorageclass   7h6m
persistentvolumeclaim/kafka-storagecp57b   Bound    pvc-a102806f-0239-11ea-93d3-0242ac110002   100Gi      RWO            examplestorageclass   6h42m
persistentvolumeclaim/kafka-storagekg5j8   Bound    pvc-a12dafe5-0239-11ea-93d3-0242ac110002   100Gi      RWO            examplestorageclass   6h42m
persistentvolumeclaim/kafka-storager5t9v   Bound    pvc-1e0b15df-0236-11ea-93d3-0242ac110002   100Gi      RWO            examplestorageclass   7h7m
persistentvolumeclaim/kafka-storagezs7r7   Bound    pvc-3b5fd2ad-0236-11ea-93d3-0242ac110002   100Gi      RWO            examplestorageclass   7h6m

```



## Broker pod deleted, is PV/PVC re-used?

**PASSED** - PV is reattached to the new pod

```sh
$ k get pod -l kafka_cr=kafka
NAME         READY   STATUS    RESTARTS   AGE
kafka8dksv   1/1     Running   0          6h12m
kafka9kp6q   1/1     Running   0          6h13m
kafkabvx7m   1/1     Running   0          6m59s
kafkap4h7p   1/1     Running   0          10m
kafkavbsff   1/1     Running   0          6h14m
kafkawn4l6   1/1     Running   0          6h14m


$ k delete pod kafka8dksv
pod "kafka8dksv" deleted

$ k get pod -l kafka_cr=kafka
NAME         READY   STATUS    RESTARTS   AGE
kafka8hn4d   1/1     Running   0          31s # <--recreated
kafka9kp6q   1/1     Running   0          6h14m
kafkabvx7m   1/1     Running   0          7m54s
kafkap4h7p   1/1     Running   0          11m
kafkavbsff   1/1     Running   0          6h15m
kafkawn4l6   1/1     Running   0          6h14m

$ k get pv,pvc -o wide  | grep examplestorageclass
# Same PV/PVCs
persistentvolume/pvc-1e0b15df-0236-11ea-93d3-0242ac110002   100Gi      RWO            Retain           Bound    kafka/kafka-storager5t9v                    examplestorageclass            7h17m
persistentvolume/pvc-3ab64754-0236-11ea-93d3-0242ac110002   100Gi      RWO            Retain           Bound    kafka/kafka-storage7g8xd                    examplestorageclass            7h16m
persistentvolume/pvc-3ae3ae0c-0236-11ea-93d3-0242ac110002   100Gi      RWO            Retain           Bound    kafka/kafka-storage6sss6                    examplestorageclass            7h16m
persistentvolume/pvc-3b5fd2ad-0236-11ea-93d3-0242ac110002   100Gi      RWO            Retain           Bound    kafka/kafka-storagezs7r7                    examplestorageclass            7h16m
persistentvolume/pvc-a102806f-0239-11ea-93d3-0242ac110002   100Gi      RWO            Retain           Bound    kafka/kafka-storagecp57b                    examplestorageclass            6h52m
persistentvolume/pvc-a12dafe5-0239-11ea-93d3-0242ac110002   100Gi      RWO            Retain           Bound    kafka/kafka-storagekg5j8                    examplestorageclass            6h52m
persistentvolumeclaim/kafka-storage6sss6   Bound    pvc-3ae3ae0c-0236-11ea-93d3-0242ac110002   100Gi      RWO            examplestorageclass   7h16m
persistentvolumeclaim/kafka-storage7g8xd   Bound    pvc-3ab64754-0236-11ea-93d3-0242ac110002   100Gi      RWO            examplestorageclass   7h16m
persistentvolumeclaim/kafka-storagecp57b   Bound    pvc-a102806f-0239-11ea-93d3-0242ac110002   100Gi      RWO            examplestorageclass   6h52m
persistentvolumeclaim/kafka-storagekg5j8   Bound    pvc-a12dafe5-0239-11ea-93d3-0242ac110002   100Gi      RWO            examplestorageclass   6h52m
persistentvolumeclaim/kafka-storager5t9v   Bound    pvc-1e0b15df-0236-11ea-93d3-0242ac110002   100Gi      RWO            examplestorageclass   7h17m
persistentvolumeclaim/kafka-storagezs7r7   Bound    pvc-3b5fd2ad-0236-11ea-93d3-0242ac110002   100Gi      RWO            examplestorageclass   7h16m
```
