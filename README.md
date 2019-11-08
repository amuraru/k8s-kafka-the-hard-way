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
# Create a 7 node cluster configuration
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



# BanzaiCloud Kafka

- Version 0.7.1: https://github.com/banzaicloud/kafka-operator/blob/0.7.1/README.md#installation


## Install pre-reqs

### 1. Cert-manager


```sh
# pre-create cert-manager namespace and CRDs per their installation instructions
kubectl apply -f https://raw.githubusercontent.com/jetstack/cert-manager/v0.10.1/deploy/manifests/01-namespace.yaml


# Install the CustomResourceDefinitions and cert-manager itself
kubectl apply -f https://github.com/jetstack/cert-manager/releases/download/v0.10.1/cert-manager.yaml

```


### 2. Install Zookeeper


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


### Install Kafka Operator


```sh

rm -rf charts/kafka-operator
helm fetch banzaicloud-stable/kafka-operator --version 0.2.4 --untar -d charts/

kubectl create ns kafka
helm template --name=kafka-operator --namespace=kafka  charts/kafka-operator -f koperator/config/samples/example-prometheus-alerts.yaml > kafka-operator.yaml
kubectl apply -n kafka  -f kafka-operator.yaml

# Check
k get all -n kafka
# Good

```


### Create a KafkaCluster

Version 0.7.1


```
cd git-koperator/
cat config/samples/simplekafkacluster.yaml

kubectl create -n kafka -f config/samples/simplekafkacluster.yaml

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



### Kafka samples


1. Create topics and send messages

```sh
kubectl -n kafka run kafka-producer -it --image=wurstmeister/kafka:2.12-2.3.0 --rm=true --restart=Never bash

/opt/kafka/bin/kafka-topics.sh --zookeeper example-zookeepercluster-client.zookeeper:2181 --topic perf-topic --create --partitions 18 --replication-factor 3

/opt/kafka/bin/kafka-producer-perf-test.sh --topic perf-topic --num-records 1000000 --throughput 100000 --record-size 5000 --producer-props bootstrap.servers=kafka-headless:29092

```
