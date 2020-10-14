**Inspired by Kelsey Hightower's [kubernetes-the-hard-way](https://github.com/kelseyhightower/kubernetes-the-hard-way), this tutorial walks you through setting up Kafka on K8s using [BanzaiCloud Kafka Operator](https://github.com/banzaicloud/kafka-operator) on a local [`kind`](https://kind.sigs.k8s.io/) cluster.** 


- [Intro](#intro)
- [Install Kafka in a `kind` k8s cluster](#install-kafka-in-a-kind-k8s-cluster)
  - [Install `kind`](#install-kind)
  - [Create a mini k8s cluster using `kind`](#create-a-mini-k8s-cluster-using-kind)
    - [Create cluster configuration](#create-cluster-configuration)
    - [Start k8s kind cluster](#start-k8s-kind-cluster)
    - [Access k8s](#access-k8s)
  - [Emulate multi-az nodes](#emulate-multi-az-nodes)
  - [Install custom `StorageClass` for persistent volumes](#install-custom-storageclass-for-persistent-volumes)
- [BanzaiCloud Kafka Operator](#banzaicloud-kafka-operator)
  - [Install pre-reqs](#install-pre-reqs)
    - [Install `cert-manager`](#install-cert-manager)
    - [Install Dell Pravega `zookeeper-operator`](#install-dell-pravega-zookeeper-operator)
      - [Create a ZK cluster with 3 zk nodes](#create-a-zk-cluster-with-3-zk-nodes)
    - [Install Prometheus Operator](#install-prometheus-operator)
      - [Access the dashboards](#access-the-dashboards)
        - [Prometheus](#prometheus)
          - [View all metrics in Prometheus](#view-all-metrics-in-prometheus)
        - [Grafana](#grafana)
        - [Alert Manager](#alert-manager)
  - [BanzaiCloud Kafka Operator](#banzaicloud-kafka-operator-1)
    - [Create a KafkaCluster](#create-a-kafkacluster)
      - [Create Prometheus `ServiceMonitor` and AlertManager `PrometheusRule` resources](#create-prometheus-servicemonitor-and-alertmanager-prometheusrule-resources)
      - [Create `PrometheusRule` to enable auto-scaling](#create-prometheusrule-to-enable-auto-scaling)
      - [Load Grafana `Kafka Looking Glass` dashboard](#load-grafana-kafka-looking-glass-dashboard)
    - [Hack around](#hack-around)
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

This is a quick tutorial on how to run [the fine piece BanzaiCloud Kafka-Operator](https://github.com/banzaicloud/kafka-operator) in a local multi-node kind cluster.


# Install Kafka in a `kind` k8s cluster

## Install `kind`

- Check https://github.com/kubernetes-sigs/kind
- Docker required (kind runs nodes and control plane as local docker containers)

```bash

curl -Lo ./kind "https://github.com/kubernetes-sigs/kind/releases/download/v0.9.0/kind-$(uname)-amd64"
chmod +x ./kind
mv ./kind ~/bin

```

## Create a mini k8s cluster using `kind`


### Create cluster configuration
```bash
mkdir ~/.kind
# Create a 6 node cluster configuration
cat > ~/.kind/kind-config.yaml <<EOF
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
- role: control-plane
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
--image kindest/node:v1.18.8
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

```
# place all nodes in the same region
kubectl label nodes kafka-worker kafka-worker2 kafka-worker3 kafka-worker4  kafka-worker5 kafka-worker6 failure-domain.beta.kubernetes.io/region=same_region

# emulate 3 AZs:
kubectl label nodes kafka-worker  kafka-worker2 failure-domain.beta.kubernetes.io/zone=az1
kubectl label nodes kafka-worker3 kafka-worker4 failure-domain.beta.kubernetes.io/zone=az2
kubectl label nodes kafka-worker5 kafka-worker6 failure-domain.beta.kubernetes.io/zone=az3

# check
kubectl get nodes --label-columns failure-domain.beta.kubernetes.io/region,failure-domain.beta.kubernetes.io/zone
```


# BanzaiCloud Kafka Operator

Installation instructions for [Version 0.12.4](https://github.com/banzaicloud/kafka-operator/tree/v0.12.4#installation)


## Install pre-reqs

**Note: The installation below assumes you're using `helm3`**

### Install `cert-manager`

See https://cert-manager.io/docs/installation/kubernetes/#steps

```sh

# Install separately CRDs
kubectl apply --validate=false -f https://github.com/jetstack/cert-manager/releases/download/v1.0.2/cert-manager.crds.yaml
kubectl create namespace cert-manager

# Install operator using helm3
helm repo add jetstack https://charts.jetstack.io
helm repo update
helm install cert-manager jetstack/cert-manager --namespace cert-manager --version v1.0.2

```

### Install Pravega `zookeeper-operator`

Make sure you use **`helm3`**

```sh
rm -rf /tmp/zookeeper-operator
git clone --single-branch --branch master  https://github.com/adobe/zookeeper-operator /tmp/zookeeper-operator

cd /tmp/zookeeper-operator

kubectl create ns zookeeper

helm template zookeeper-operator --namespace=zookeeper --set image.repository='adobe/zookeeper-operator' --set image.tag='0.2.9-adobe-20201013' ./charts/zookeeper-operator > ./charts/zookeeper-operator.yaml
kubectl apply -n zookeeper -f ./charts/zookeeper-operator.yaml
```

#### Create a ZK cluster with 3 zk nodes

```sh
kubectl apply --namespace zookeeper -f - <<EOF
apiVersion: zookeeper.pravega.io/v1beta1
kind: ZookeeperCluster
metadata:
  name: zk
  namespace: zookeeper
spec:
  replicas: 3
  image:
    repository: adobe/zookeeper
    tag: 3.6.2-0.2.9-adobe-20201013
    pullPolicy: IfNotPresent
  config:
    initLimit: 10
    tickTime: 2000
    syncLimit: 5
  persistence:
    reclaimPolicy: Delete
    spec:
      accessModes:
      - ReadWriteOnce
      resources:
        requests:
          storage: 20Gi
EOF


# Check
kubectl get all -n zookeeper
# SS up?
kubectl get -w statefulset.apps/zk -n zookeeper
# Good
```

See more at https://github.com/pravega/zookeeper-operator


### Install Prometheus Operator

```sh

kubectl apply -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/master/example/prometheus-operator-crd/monitoring.coreos.com_alertmanagers.yaml
kubectl apply -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/master/example/prometheus-operator-crd/monitoring.coreos.com_prometheuses.yaml
kubectl apply -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/master/example/prometheus-operator-crd/monitoring.coreos.com_prometheusrules.yaml
kubectl apply -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/master/example/prometheus-operator-crd/monitoring.coreos.com_servicemonitors.yaml
kubectl apply -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/master/example/prometheus-operator-crd/monitoring.coreos.com_podmonitors.yaml
kubectl apply -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/master/example/prometheus-operator-crd/monitoring.coreos.com_thanosrulers.yaml
kubectl apply -f https://raw.githubusercontent.com/prometheus-operator/prometheus-operator/master/example/prometheus-operator-crd/monitoring.coreos.com_probes.yaml

helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update
helm install monitoring --namespace=default prometheus-community/kube-prometheus-stack --set prometheusOperator.createCustomResource=false

```

#### Access the dashboards

Prometheus, Grafana, and Alertmanager dashboards can be accessed quickly using `kubectl port-forward` after running the quickstart via the commands below. Kubernetes 1.10 or later is required.


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

Then access via [http://localhost:3000](http://localhost:3000) and use the  grafana user:password of `admin:prom-operator`.

#####  Alert Manager

```
kubectl --namespace default port-forward svc/monitoring-kube-prometheus-alertmanager 9093
```

Then access via [http://localhost:9093](http://localhost:9093)

```
# check all resources created by helm release
k get all -A -l release=monitoring

```


## BanzaiCloud Kafka Operator

```sh
# new kafka NS
kubectl create ns kafka

# install operator using upstream helm chart
rm -rf /tmp/kafka-operator
git clone --single-branch --branch master  https://github.com/banzaicloud/kafka-operator /tmp/kafka-operator

cd /tmp/kafka-operator

kubectl apply -f config/base/crds/kafka.banzaicloud.io_kafkaclusters.yaml
kubectl apply -f config/base/crds/kafka.banzaicloud.io_kafkatopics.yaml
kubectl apply -f config/base/crds/kafka.banzaicloud.io_kafkausers.yaml

helm template kafka-operator \
  --namespace=kafka \
  --set webhook.enabled=false \
  --set operator.image.repository=adobe/kafka-operator \
  --set operator.image.tag=0.12.4-adobe-20200920 \
  charts/kafka-operator  > kafka-operator.yaml

kubectl apply -n kafka  -f kafka-operator.yaml

# Check
kubectl get all -n kafka
# Good

```


### Create a KafkaCluster

```
kubectl apply -n kafka -f https://raw.githubusercontent.com/amuraru/k8s-kafka-the-hard-way/master/simplekafkacluster.yaml
# Check CRD created
k get KafkaCluster kafka -n kafka
# See CRD state
k describe KafkaCluster kafka -n kafka

```

#### Create Prometheus `ServiceMonitor` and AlertManager `PrometheusRule` resources

```sh
kubectl apply -n kafka -f https://raw.githubusercontent.com/amuraru/k8s-kafka-operator/master/kafkacluster-prometheus-monitoring.yaml
```

#### Create `PrometheusRule` to enable auto-scaling

```sh
kubectl apply -n kafka -f https://raw.githubusercontent.com/amuraru/k8s-kafka-operator/master/kafkacluster-prometheus-autoscale.yaml
```


#### Load Grafana `Kafka Looking Glass` dashboard

```sh
kubectl apply -n default -f https://raw.githubusercontent.com/amuraru/k8s-kafka-operator/master/grafana-dashboard.yaml
```
This needs to be created in the same namespace as `grafana` (`default`)

Dashboard should be automatically loaded and available at http://127.0.0.1:3000/d/1a1a1a1a1/kafka-looking-glass

### Hack around


```sh

kubectl config set-context --current --namespace=kafka

# See operator logs
k logs  -l app.kubernetes.io/instance=kafka-operator  -c  manager -f

# Check Cruise Control
kubectl port-forward -n kafka svc/kafka-cruisecontrol-svc 18090:8090 --address 10.131.236.142

# Check Prometheus
kubectl port-forward -n default svc/prometheus-operated 19090:9090 --address 10.131.236.142
# http://10.131.236.142:19090/graph?g0.range_input=1h&g0.expr=%7B__name__%20%3D~%27kafka.*%27%7D&g0.tab=1

```

#### Verify pod images

```sh
kubectl get pod -o=custom-columns='NAME:.metadata.name,IMAGE:.spec.containers[*].image' --all-namespaces
```


### Kafka samples

#### List topics

```bash
kubectl run kafka-topics --rm -i --tty=true \
--image=adobe/kafka:2.12-2.5.1 \
--restart=Never \
-- /opt/kafka/bin/kafka-topics.sh \
--bootstrap-server kafka-headless:29092 \
--list
```

#### Create topic

```bash
kubectl run kafka-topics --rm -i --tty=true \
--image=adobe/kafka:2.12-2.5.1 \
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
--image=adobe/kafka:2.12-2.5.1 \
--restart=Never \
-- /opt/kafka/bin/kafka-configs.sh \
--zookeeper zk-client.zookeeper:2181/kafka \
--alter --entity-name perf_topic \
--entity-type topics \
--add-config retention.ms=720000
```

#### Topic Describe

```bash
kubectl run kafka-topics --rm -i --tty=true \
--image=adobe/kafka:2.12-2.5.1 \
--restart=Never \
-- /opt/kafka/bin/kafka-topics.sh \
--bootstrap-server kafka-headless:29092 \
--topic perf_topic \
--describe
```

#### Start Producer perf test

```bash
kubectl run kafka-producer-topic \
--image=adobe/kafka:2.12-2.5.1 \
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
--image=adobe/kafka:2.12-2.5.1 \
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
k get pv,pvc  | grep examplestorageclass

persistentvolume/pvc-1e0b15df-0236-11ea-93d3-0242ac110002   100Gi      RWO            Retain           Bound    kafka/kafka-storager5t9v                    examplestorageclass            6h59m
persistentvolume/pvc-3ab64754-0236-11ea-93d3-0242ac110002   100Gi      RWO            Retain           Bound    kafka/kafka-storage7g8xd                    examplestorageclass            6h58m
persistentvolume/pvc-3ae3ae0c-0236-11ea-93d3-0242ac110002   100Gi      RWO            Retain           Bound    kafka/kafka-storage6sss6                    examplestorageclass            6h58m
persistentvolume/pvc-3b5fd2ad-0236-11ea-93d3-0242ac110002   100Gi      RWO            Retain           Bound    kafka/kafka-storagezs7r7                    examplestorageclass            6h58m
persistentvolume/pvc-a102806f-0239-11ea-93d3-0242ac110002   100Gi      RWO            Retain           Bound    kafka/kafka-storagecp57b                    examplestorageclass            6h33m
persistentvolume/pvc-a12dafe5-0239-11ea-93d3-0242ac110002   100Gi      RWO            Retain           Bound    kafka/kafka-storagekg5j8                    examplestorageclass            6h33m

persistentvolumeclaim/kafka-storage6sss6   Bound    pvc-3ae3ae0c-0236-11ea-93d3-0242ac110002   100Gi      RWO            examplestorageclass   6h58m
persistentvolumeclaim/kafka-storage7g8xd   Bound    pvc-3ab64754-0236-11ea-93d3-0242ac110002   100Gi      RWO            examplestorageclass   6h58m
persistentvolumeclaim/kafka-storagecp57b   Bound    pvc-a102806f-0239-11ea-93d3-0242ac110002   100Gi      RWO            examplestorageclass   6h33m
persistentvolumeclaim/kafka-storagekg5j8   Bound    pvc-a12dafe5-0239-11ea-93d3-0242ac110002   100Gi      RWO            examplestorageclass   6h33m
persistentvolumeclaim/kafka-storager5t9v   Bound    pvc-1e0b15df-0236-11ea-93d3-0242ac110002   100Gi      RWO            examplestorageclass   6h59m
persistentvolumeclaim/kafka-storagezs7r7   Bound    pvc-3b5fd2ad-0236-11ea-93d3-0242ac110002   100Gi      RWO            examplestorageclass   6h58m


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
