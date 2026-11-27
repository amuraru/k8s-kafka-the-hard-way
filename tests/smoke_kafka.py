"""Run the Kafka smoke tests against the local kind cluster named kafka."""

import argparse
from contextlib import ExitStack
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
from urllib.parse import urlencode, urlparse
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = "kafka-headless:29092"
PROMETHEUS = (
    "/api/v1/namespaces/default/services/monitoring-kube-prometheus-prometheus:9090/proxy"
)


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def run(*args, text=None, timeout=30):
    result = subprocess.run(args, input=text, capture_output=True, text=True, timeout=timeout)
    require(result.returncode == 0, f"{shlex.join(args)} failed:\n{result.stderr}{result.stdout}")
    return result.stdout


def wait_for(probe, description, timeout=120):
    deadline = time.monotonic() + timeout
    error = None
    while time.monotonic() < deadline:
        try:
            value = probe()
            if value:
                return value
        except (RuntimeError, subprocess.TimeoutExpired) as exc:
            error = exc
        time.sleep(2)
    detail = f"\nLast command error: {error}" if error else ""
    raise RuntimeError(f"Timed out after {timeout}s: {description}{detail}")


def healthy_partitions(description, topic):
    rows = re.findall(
        rf"^\s*Topic:\s+{re.escape(topic)}\s+Partition:\s+(\d+)\s+Leader:\s+(-?\d+)"
        r"\s+Replicas:\s+([0-9,]+)\s+Isr:\s+([0-9,]+)(?=\s|$)",
        description,
        re.MULTILINE,
    )
    if len(rows) != 3 or {row[0] for row in rows} != {"0", "1", "2"}:
        return None
    partitions = {}
    for partition, leader, replicas, isr in rows:
        assigned = replicas.split(",")
        in_sync = isr.split(",")
        replica_set = frozenset(assigned)
        if not (len(assigned) == len(in_sync) == len(replica_set) == 3):
            return None
        if replica_set != set(in_sync) or leader not in replica_set:
            return None
        partitions[int(partition)] = (leader, replica_set)
    return partitions


def committed_at_end(description, group, topic, records):
    rows = [row for line in description.splitlines() if (row := line.split())[:2] == [group, topic]]
    return (
        len(rows) == 3
        and all(len(row) >= 6 for row in rows)
        and {row[2] for row in rows} == {"0", "1", "2"}
        and all(row[3].isdigit() and row[3] == row[4] and row[5] == "0" for row in rows)
        and sum(int(row[4]) for row in rows) == records
    )


class SmokeTest:
    def __init__(self, kubeconfig):
        self.kubeconfig = kubeconfig
        self.topic = f"local-smoke-{uuid4().hex[:12]}"
        self.client = f"{self.topic}-client"
        self.group = f"{self.topic}-resume"
        self.replay_group = f"{self.topic}-replay"

    def kubectl(self, *args, namespace="kafka", text=None, timeout=30):
        return run(
            "kubectl", "--kubeconfig", str(self.kubeconfig), "--context", "kind-kafka",
            "--namespace", namespace, "--request-timeout=20s", *args, text=text, timeout=timeout,
        )

    def kafka(self, tool, *args, text=None):
        flags = ("-i",) if text is not None else ()
        return self.kubectl(
            "exec", *flags, self.client, "--", f"/opt/kafka/bin/{tool}.sh",
            "--bootstrap-server", BOOTSTRAP, *args, text=text,
        )

    def check_context(self):
        server = self.kubectl("config", "view", "--minify", "-o", "jsonpath={.clusters[0].cluster.server}")
        require(urlparse(server).hostname in {"127.0.0.1", "::1", "localhost"}, f"Expected a loopback API: {server}")
        nodes = self.kubectl("get", "nodes", "-l", "node-role.kubernetes.io/control-plane", "-o", "name")
        require(nodes.strip() == "node/kafka-control-plane", f"Unexpected control plane: {nodes}")

    def wait_for_partitions(self):
        return wait_for(
            lambda: healthy_partitions(self.kafka("kafka-topics", "--describe", "--topic", self.topic), self.topic),
            f"a leader and three in-sync replicas on every partition of {self.topic}",
            timeout=180,
        )

    def check_lag(self, expected):
        metric = (
            "sum(kminion_kafka_consumer_group_topic_lag{"
            f'namespace="kafka",kafka_cr="kafka",topic_name="{self.topic}",group_id="{self.group}"'
            "})"
        )
        path = f"{PROMETHEUS}/api/v1/query?{urlencode({'query': metric})}"

        def has_expected_sample():
            response = json.loads(self.kubectl("get", "--raw", path, namespace="default"))
            require(response["status"] == "success", f"Prometheus query failed: {response}")
            samples = response["data"]["result"]
            return len(samples) == 1 and float(samples[0]["value"][1]) == expected

        wait_for(has_expected_sample, f"KMinion lag of {expected} for {self.group}")
        print(f"KMinion reported lag={expected} for {self.group}", flush=True)

    def produce(self, records):
        self.kafka(
            "kafka-console-producer", "--topic", self.topic, "--producer-property", "acks=all",
            "--property", "parse.key=true", "--property", "key.separator=:",
            text="".join(f"{record}:{record}\n" for record in records),
        )

    def consume(self, group, records, *, total):
        actual = self.kafka(
            "kafka-console-consumer", "--topic", self.topic, "--group", group,
            "--from-beginning", "--max-messages", str(len(records)), "--timeout-ms", "15000",
        ).splitlines()
        require(sorted(actual) == sorted(records), f"{group}: expected {records!r}; got {actual!r}")
        wait_for(
            lambda: committed_at_end(
                self.kafka("kafka-consumer-groups", "--describe", "--group", group),
                group, self.topic, total,
            ),
            f"{group} to commit all {total} records across three partitions",
            timeout=45,
        )
        print(f"{group} received {len(records)} exact records and committed through record {total}", flush=True)

    def ready_broker(self, broker_id):
        selector = f"app=kafka,kafka_cr=kafka,brokerId={broker_id}"
        pods = json.loads(self.kubectl("get", "pods", "-l", selector, "-o", "json"))["items"]
        if len(pods) != 1 or pods[0]["metadata"].get("deletionTimestamp"):
            return None
        pod = pods[0]
        if any(c["type"] == "Ready" and c["status"] == "True" for c in pod["status"].get("conditions", [])):
            return pod
        return None

    def bound_storage(self, pod):
        claims = [v["persistentVolumeClaim"]["claimName"] for v in pod["spec"]["volumes"] if "persistentVolumeClaim" in v]
        require(claims, f"{pod['metadata']['name']} has no persistent storage claim")
        storage = {}
        for name in claims:
            claim = json.loads(self.kubectl("get", "pvc", name, "-o", "json"))
            volume = claim["spec"].get("volumeName")
            require(claim["status"]["phase"] == "Bound" and volume, f"Claim {name} is not bound")
            storage[name] = (claim["metadata"]["uid"], volume)
        return storage

    def replace_broker(self, partitions, records):
        broker_id = partitions[0][0]
        old_pod = self.ready_broker(broker_id)
        require(old_pod, f"Expected one ready pod for broker {broker_id}")
        storage = self.bound_storage(old_pod)
        name, uid = (old_pod["metadata"][key] for key in ("name", "uid"))
        self.check_context()
        print(f"Replacing broker {broker_id} pod {name}; claims: {', '.join(storage)}", flush=True)
        self.kubectl(
            "delete", "--raw", f"/api/v1/namespaces/kafka/pods/{name}", "-f", "-",
            text=json.dumps({"apiVersion": "v1", "kind": "DeleteOptions", "preconditions": {"uid": uid}}),
        )

        def new_broker():
            pod = self.ready_broker(broker_id)
            return pod if pod and pod["metadata"]["uid"] != uid else None

        new_pod = wait_for(new_broker, f"a ready replacement for broker {broker_id}", timeout=180)
        require(self.bound_storage(new_pod) == storage, f"Broker {broker_id} did not reuse its claims and volumes")
        recovered = self.wait_for_partitions()
        require(
            {p: replicas for p, (_, replicas) in recovered.items()}
            == {p: replicas for p, (_, replicas) in partitions.items()},
            "Replica assignments changed during broker replacement",
        )
        self.consume(self.replay_group, records, total=len(records))
        print(f"Broker {broker_id} recovered on the same storage and all records remained readable", flush=True)

    def delete_test_groups(self):
        groups = self.kafka("kafka-consumer-groups", "--list").splitlines()
        for group in (self.group, self.replay_group):
            if group in groups:
                self.kafka("kafka-consumer-groups", "--delete", "--group", group)

    def exercise(self, replace_broker):
        self.check_context()
        if replace_broker:
            rules = self.kubectl("get", "prometheusrule/kafka-alerts", "--ignore-not-found", "-o", "name")
            require(not rules.strip(), "Run --replace-broker before enabling the sample autoscaling rules")
        image = run("yq", "-er", ".spec.clusterImage", str(ROOT / "simplekafkacluster.yaml")).strip()
        print(f"Smoke topic: {self.topic}; consumer group: {self.group}", flush=True)
        with ExitStack() as cleanup:
            self.kubectl(
                "run", self.client, "--restart=Never", "--image", image,
                "--image-pull-policy=IfNotPresent", "--command", "--", "sleep", "1200",
            )
            cleanup.callback(self.kubectl, "delete", f"pod/{self.client}", "--ignore-not-found", "--timeout=45s", timeout=60)
            self.kubectl("wait", "--for=condition=Ready", f"pod/{self.client}", "--timeout=90s", timeout=100)
            topic = {
                "apiVersion": "kafka.banzaicloud.io/v1alpha1",
                "kind": "KafkaTopic",
                "metadata": {"name": self.topic, "namespace": "kafka"},
                "spec": {
                    "name": self.topic, "clusterRef": {"name": "kafka"}, "partitions": 3,
                    "replicationFactor": 3, "config": {"retention.ms": "720000"},
                },
            }
            self.kubectl("create", "-f", "-", text=json.dumps(topic))
            cleanup.callback(self.kubectl, "delete", f"kafkatopic/{self.topic}", "--ignore-not-found", "--timeout=90s", timeout=105)
            self.kubectl("wait", "--for=jsonpath={.status.state}=created", f"kafkatopic/{self.topic}", "--timeout=90s", timeout=100)
            partitions = self.wait_for_partitions()
            config = self.kafka("kafka-configs", "--describe", "--entity-type", "topics", "--entity-name", self.topic)
            require(re.search(r"\bretention\.ms=720000(?=\s|$)", config), f"Unexpected topic retention:\n{config}")
            print("KOperator created three replicated partitions with 720000 ms retention", flush=True)

            cleanup.callback(self.delete_test_groups)
            initial = [f"{self.topic}-{i:03d}" for i in range(100)]
            appended = [f"{self.topic}-{i:03d}" for i in range(100, 105)]
            self.produce(initial)
            self.consume(self.group, initial, total=100)
            self.check_lag(0)
            self.produce(appended)
            self.check_lag(5)
            self.consume(self.group, appended, total=105)
            self.check_lag(0)
            if replace_broker:
                self.replace_broker(partitions, initial + appended)
            self.wait_for_partitions()
            for flag in ("--unavailable-partitions", "--under-replicated-partitions"):
                listing = self.kafka("kafka-topics", "--describe", flag)
                require(not listing.strip(), f"{flag}:\n{listing}")
            print("No offline or under-replicated partitions", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replace-broker", action="store_true", help="also replace one local broker pod")
    args = parser.parse_args()
    try:
        with TemporaryDirectory(prefix="kind-kafka-smoke-") as temp:
            kubeconfig = Path(temp) / "kubeconfig"
            kubeconfig.touch(mode=0o600)
            kubeconfig.write_text(run("kind", "get", "kubeconfig", "--name", "kafka"))
            SmokeTest(kubeconfig).exercise(args.replace_broker)
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        sys.exit(f"Kafka smoke test failed: {exc}")
    print("Kafka smoke test passed; temporary test resources removed")


if __name__ == "__main__":
    main()
