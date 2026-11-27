#!/bin/sh
set -eu

repo=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
work=$(mktemp -d)
trap 'rm -f "$work/rules.yaml" "$work/alerts.test.yaml"; rmdir "$work"' EXIT

yq -e '.spec' "$repo/kafkacluster-prometheus-autoscale.yaml" > "$work/rules.yaml"
image=$(yq -er '.spec.clusterImage' "$repo/simplekafkacluster.yaml")
KAFKA_IMAGE=$image yq -e '
  (.tests[].alert_rule_test[].exp_alerts[]
    | select(.exp_annotations.image == "KAFKA_IMAGE_FROM_CLUSTER_MANIFEST")
    | .exp_annotations.image) = strenv(KAFKA_IMAGE)
' "$repo/tests/prometheus/alerts.test.yaml" > "$work/alerts.test.yaml"

cd "$work"
promtool test rules alerts.test.yaml
