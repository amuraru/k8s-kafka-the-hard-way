<!--ts-->
   * [Intro](#intro)
   * [Install Kafka in a kind k8s cluster](#install-kafka-in-a-kind-k8s-cluster)
      * [Install kind](#install-kind)
      * [Create a mini k8s cluster using kind](#create-a-mini-k8s-cluster-using-kind)
         * [Create cluster configuration](#create-cluster-configuration)
         * [Start k8s 1.14 cluster](#start-k8s-114-cluster)
         * [Access k8s](#access-k8s)
      * [Emulate multi-az nodes](#emulate-multi-az-nodes)
   * [BanzaiCloud Kafka](#banzaicloud-kafka)
      * [Install pre-reqs](#install-pre-reqs)
         * [Cert-manager](#cert-manager)
         * [Install Zookeeper](#install-zookeeper)
         * [Install Prometheus Operator](#install-prometheus-operator)
         * [Install disk provisioner and custom storage class](#install-disk-provisioner-and-custom-storage-class)
      * [BanzaiCloud Kafka Operator](#banzaicloud-kafka-operator)
         * [Create a KafkaCluster](#create-a-kafkacluster)
         * [Hack around](#hack-around)
         * [Kafka samples](#kafka-samples)
   * [Disaster scenarios](#disaster-scenarios)
      * [Initial state](#initial-state)
      * [Broker JVM dies, is PV/PVC re-used?](#broker-jvm-dies-is-pvpvc-re-used)
      * [Broker pod deleted, is PV/PVC re-used?](#broker-pod-deleted-is-pvpvc-re-used)

<!-- Added by: amuraru, at: Mon Nov 11 11:50:01 EET 2019 -->

<!--te-->


# Intro

This is a quick tutorial on how to run [the fine piece BanzaiCloud Kafka-Operator](https://github.com/banzaicloud/kafka-operator) in a local multi-node kind cluster.



# Install Kafka in a `kind` k8s cluster

## Install `kind`

- Check https://github.com/kubernetes-sigs/kind
- Docker required (kind runs nodes and control plane as local docker containers)

```bash

curl -Lo ./kind https://github.com/kubernetes-sigs/kind/releases/download/v0.5.1/kind-$(uname)-amd64
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
apiVersion: kind.sigs.k8s.io/v1alpha3
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

### Start k8s 1.14 cluster

```sh
kind create cluster \
--name kind \
--config ~/.kind/kind-config.yaml \
--image kindest/node:v1.14.6
```

`kind` clusters are running in docker, check containers: `docker ps`


### Access k8s

```sh
export KUBECONFIG="$(kind get kubeconfig-path --name="kind")"
```


## Emulate multi-az nodes

```
# place all nodes in the same region
kubectl label nodes kind-worker kind-worker2 kind-worker3 kind-worker4  kind-worker5 kind-worker6 failure-domain.beta.kubernetes.io/region=same_region

# emulate 3 AZs:
kubectl label nodes kind-worker  kind-worker2 failure-domain.beta.kubernetes.io/zone=az1
kubectl label nodes kind-worker3 kind-worker4 failure-domain.beta.kubernetes.io/zone=az2
kubectl label nodes kind-worker5 kind-worker6 failure-domain.beta.kubernetes.io/zone=az3

# check
kubectl get nodes --label-columns failure-domain.beta.kubernetes.io/region,failure-domain.beta.kubernetes.io/zone
```

# BanzaiCloud Kafka

- Version 0.7.1: https://github.com/banzaicloud/kafka-operator/blob/0.7.1/README.md#installation


## Install pre-reqs

### Cert-manager


```sh
# pre-create cert-manager namespace and CRDs per their installation instructions
kubectl apply -f https://raw.githubusercontent.com/jetstack/cert-manager/v0.10.1/deploy/manifests/01-namespace.yaml


# Install the CustomResourceDefinitions and cert-manager itself
kubectl apply -f https://github.com/jetstack/cert-manager/releases/download/v0.10.1/cert-manager.yaml

```


### Install Zookeeper


```sh

helm repo add banzaicloud-stable https://kubernetes-charts.banzaicloud.com/
helm repo update
helm fetch banzaicloud-stable/zookeeper-operator --untar -d charts/
helm template --name zookeeper-operator --namespace=zookeeper charts/zookeeper-operator > zk.yaml
kubectl create ns zookeeper
kubectl apply -n zookeeper -f zk.yaml

# Create a ZK cluster with 3 zk nodes
kubectl create --namespace zookeeper -f - <<EOF
apiVersion: zookeeper.pravega.io/v1beta1
kind: ZookeeperCluster
metadata:
  name: example-zookeepercluster
  namespace: zookeeper
spec:
  replicas: 3
EOF


# Check
k get all -n zookeeper
# SS up?
k get statefulset.apps/example-zookeepercluster -n zookeeper
# Good
```

See more at https://github.com/pravega/zookeeper-operator


### Install Prometheus Operator

```sh
kubectl apply -n default -f https://raw.githubusercontent.com/coreos/prometheus-operator/master/bundle.yaml

# check
k get all -A -l app.kubernetes.io/name=prometheus-operator

```


### Install disk provisioner and custom storage class


- Using https://github.com/rancher/local-path-provisioner as this emulates better individual disks

```sh
kubectl apply -f https://raw.githubusercontent.com/rancher/local-path-provisioner/master/deploy/local-path-storage.yaml

# Check
kubectl get all -n local-path-storage

# Create a custom storage class for Kafka
kubectl apply -f - <<EOF
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: examplestorageclass
provisioner: rancher.io/local-path
volumeBindingMode: WaitForFirstConsumer
reclaimPolicy: Retain
EOF

```


## BanzaiCloud Kafka Operator



```sh

rm -rf charts/kafka-operator
helm fetch banzaicloud-stable/kafka-operator --version 0.2.4 --untar -d charts/

kubectl create ns kafka
helm template --name=kafka-operator --namespace=kafka  charts/kafka-operator  > kafka-operator.yaml
kubectl apply -n kafka  -f kafka-operator.yaml

# Check
k get all -n kafka
# Good

```


### Create a KafkaCluster

Version 0.7.1


```
kubectl create -n kafka -f https://raw.githubusercontent.com/amuraru/k8s-kafka-operator/master/simplekafkacluster.yaml

# Create the ServiceMonitors for Prometheus
kubectl create -n default -f https://raw.githubusercontent.com/amuraru/k8s-kafka-operator/master/kafkacluster-prometheus.yaml

# Check CRD created
k get KafkaCluster kafka -n kafka
# See CRD state
k describe KafkaCluster kafka -n kafka

```

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
kubectl get pod -o=custom-columns=NAME:.metadata.name,IMAGE:.spec.containers[*].image --all-namespaces
```



### Kafka samples


1. Create topics and send messages

```sh
kubectl -n kafka run kafka-producer -it --image=wurstmeister/kafka:2.12-2.3.0 --rm=true --restart=Never bash

/opt/kafka/bin/kafka-topics.sh --zookeeper example-zookeepercluster-client.zookeeper:2181 --topic perf-topic --create --partitions 18 --replication-factor 3

/opt/kafka/bin/kafka-producer-perf-test.sh --topic perf-topic --num-records 1000000 --throughput 100000 --record-size 5000 --producer-props bootstrap.servers=kafka-headless:29092

```


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
