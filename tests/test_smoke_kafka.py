import unittest

from smoke_kafka import committed_at_end, healthy_partitions


TOPIC_DESCRIPTION = """Topic: smoke\tPartitionCount: 3\tReplicationFactor: 3
    Topic: smoke\tPartition: 0\tLeader: 102\tReplicas: 102,302,201\tIsr: 201,102,302\tElr: N/A
    Topic: smoke\tPartition: 1\tLeader: 202\tReplicas: 202,101,301\tIsr: 202,101,301\tElr: N/A
    Topic: smoke\tPartition: 2\tLeader: 302\tReplicas: 302,201,102\tIsr: 302,201,102\tElr: N/A
"""

GROUP_DESCRIPTION = """GROUP TOPIC PARTITION CURRENT-OFFSET LOG-END-OFFSET LAG CONSUMER-ID HOST CLIENT-ID
smoke-group smoke 0 34 34 0 - - -
smoke-group smoke 1 36 36 0 - - -
smoke-group smoke 2 35 35 0 - - -
"""


class SmokeAssertions(unittest.TestCase):
    def test_isr_order_can_differ_from_replica_order(self):
        partitions = healthy_partitions(TOPIC_DESCRIPTION, "smoke")
        self.assertEqual(partitions[0], ("102", frozenset({"102", "302", "201"})))

    def test_missing_partition_or_wrong_isr_or_leader_fails(self):
        descriptions = (
            "",
            "\n".join(TOPIC_DESCRIPTION.splitlines()[:-1]),
            TOPIC_DESCRIPTION.replace("Isr: 201,102,302", "Isr: 201,102"),
            TOPIC_DESCRIPTION.replace("Isr: 201,102,302", "Isr: 201,102,301"),
            TOPIC_DESCRIPTION.replace("Isr: 201,102,302", "Isr: 201,102,302,201"),
            TOPIC_DESCRIPTION.replace("Leader: 102", "Leader: -1"),
        )
        for description in descriptions:
            with self.subTest(description=description):
                self.assertIsNone(healthy_partitions(description, "smoke"))

    def test_committed_offsets_include_all_expected_records(self):
        self.assertTrue(committed_at_end(GROUP_DESCRIPTION, "smoke-group", "smoke", 105))
        self.assertFalse(committed_at_end(GROUP_DESCRIPTION, "smoke-group", "smoke", 100))

    def test_missing_duplicate_uncommitted_and_lagging_offsets_fail(self):
        descriptions = (
            "\n".join(GROUP_DESCRIPTION.splitlines()[:-1]),
            GROUP_DESCRIPTION.replace("smoke-group smoke 2", "smoke-group smoke 0"),
            GROUP_DESCRIPTION.replace("34 34 0", "- 34 -"),
            GROUP_DESCRIPTION.replace("34 34 0", "33 34 1"),
        )
        for description in descriptions:
            with self.subTest(description=description):
                self.assertFalse(committed_at_end(description, "smoke-group", "smoke", 105))
