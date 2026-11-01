import unittest

from confidence import _cosine_score, score_confidence


class LightweightConfidenceTests(unittest.TestCase):
    def test_matching_evidence_scores_above_unrelated_evidence(self):
        chunks = [{"text": "Create a customer with POST /customers"}]

        matching = _cosine_score("Create a customer using POST /customers", chunks)
        unrelated = _cosine_score("Read the weather forecast", chunks)

        self.assertGreater(matching, unrelated)
        self.assertGreaterEqual(matching, 0)
        self.assertLessEqual(matching, 1)

    def test_public_confidence_score_remains_bounded(self):
        score = score_confidence(
            "How do I create a customer?",
            "Use POST /customers to create a customer.",
            [{"text": "POST /customers Create a customer"}],
        )

        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 100)


if __name__ == "__main__":
    unittest.main()
