import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


class StreamingContractTests(unittest.TestCase):
    def test_kafka_exporter_topics_encodings_and_keys_are_explicit(self):
        config = yaml.safe_load((ROOT / "collector" / "otel-collector-kafka.yaml").read_text(encoding="utf-8"))
        exporter = config["exporters"]["kafka"]

        self.assertEqual(exporter["brokers"], ["broker:19092"])
        self.assertEqual(exporter["logs"], {"topic": "aiops.otlp.logs.v1", "encoding": "otlp_proto"})
        self.assertEqual(exporter["metrics"], {"topic": "aiops.otlp.metrics.v1", "encoding": "otlp_proto"})
        self.assertEqual(exporter["traces"], {"topic": "aiops.otlp.traces.v1", "encoding": "otlp_proto"})
        self.assertTrue(exporter["partition_logs_by_trace_id"])
        self.assertTrue(exporter["partition_metrics_by_resource_attributes"])
        self.assertTrue(exporter["partition_traces_by_id"])
        self.assertFalse(exporter["producer"]["allow_auto_topic_creation"])

    def test_streaming_compose_is_opt_in_and_loopback_only(self):
        compose = yaml.safe_load((ROOT / "collector" / "streaming.compose.yaml").read_text(encoding="utf-8"))

        self.assertEqual(compose["services"]["kafka"]["image"], "apache/kafka:4.1.2")
        self.assertEqual(compose["services"]["kafka"]["profiles"], ["streaming"])
        self.assertEqual(compose["services"]["kafka"]["ports"], ["127.0.0.1:9092:9092"])
        self.assertEqual(
            compose["services"]["kafka"]["environment"]["KAFKA_ADVERTISED_LISTENERS"],
            "PLAINTEXT_HOST://localhost:9092,PLAINTEXT://broker:19092",
        )
        self.assertEqual(
            compose["services"]["otel-collector"]["image"],
            "otel/opentelemetry-collector-contrib:0.143.0",
        )
        self.assertEqual(compose["services"]["otel-collector"]["profiles"], ["streaming"])
        self.assertEqual(compose["services"]["otel-collector"]["ports"], ["127.0.0.1:4318:4318"])

    def test_each_signal_pipeline_exports_to_debug_and_kafka(self):
        config = yaml.safe_load((ROOT / "collector" / "otel-collector-kafka.yaml").read_text(encoding="utf-8"))

        self.assertEqual(set(config["service"]["pipelines"]), {"logs", "metrics", "traces"})
        for pipeline in config["service"]["pipelines"].values():
            self.assertEqual(pipeline["exporters"], ["debug", "kafka"])


if __name__ == "__main__":
    unittest.main()
