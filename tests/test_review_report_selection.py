import unittest

from orchestrator.review_report import select_deep_topics


class ReviewReportSelectionTests(unittest.TestCase):
    def test_four_layer_ready_topic_is_included_without_hidden_ranking(self):
        topics = [
            {"topic_id": "A", "candidate_state": "MAIN_CONTEXT"},
            {"topic_id": "B", "candidate_state": "MAIN_CONTEXT"},
            {"topic_id": "C", "candidate_state": "DEEP_DIVE_CANDIDATE"},
        ]
        xmap = {
            "A": {"review_state": "FOUR_LAYER_READY"},
            "B": {"review_state": "MULTI_LAYER_REVIEW"},
            "C": {"review_state": "MULTI_LAYER_REVIEW"},
        }
        selected = select_deep_topics(topics, xmap)
        self.assertEqual([x["topic_id"] for x in selected], ["A", "C"])

    def test_all_four_layer_ready_topics_are_kept_not_top_n_ranked(self):
        topics = [{"topic_id": str(i), "candidate_state": "MAIN_CONTEXT"} for i in range(9)]
        xmap = {str(i): {"review_state": "FOUR_LAYER_READY"} for i in range(9)}
        selected = select_deep_topics(topics, xmap)
        self.assertEqual(len(selected), 9)


if __name__ == "__main__":
    unittest.main()
