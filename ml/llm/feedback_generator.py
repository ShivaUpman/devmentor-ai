"""
ml/llm/feedback_generator.py — LLM-powered interview feedback

This replaces the rule-based feedback strings from Module 5 with
genuine AI coaching. The LLM receives:
  - The question
  - The ideal answer
  - The candidate's answer
  - Their numeric scores (similarity, confidence, keywords matched)

And returns structured feedback:
  - A concise assessment
  - Specific strengths
  - Specific improvements
  - A follow-up hint question

WHY give the LLM the numeric scores?
  The LLM alone might hallucinate strengths or miss real problems.
  Grounding it with computed scores (similarity=0.32 = weak content match)
  steers the feedback toward honest assessment rather than encouragement.

  This is "LLM as formatter, not judge" — the ML model judges quality,
  the LLM formats the judgment into human-readable coaching.
  Hybrid approaches like this outperform LLM-only systems in reliability.

Interview question: "What is prompt grounding and why does it matter?"
  Grounding = providing factual context that constrains LLM output.
  Without grounding: "Great answer!" even for a 30% similarity score.
  With grounding: "Your answer scored 30% content match — you mentioned
  [X] but missed [Y] and [Z] which are central to this topic."
"""

from typing import Optional
from llm.groq_client import GroqClient, GroqClientError, get_groq_client

FEEDBACK_SYSTEM_PROMPT = """You are an expert technical interviewer at a top tech company.
You provide honest, specific, and encouraging feedback to candidates practicing for interviews.

Your feedback must be:
- Honest: don't sugarcoat a weak answer, but don't be harsh
- Specific: reference what they said (or didn't say)  
- Actionable: tell them exactly what to improve
- Concise: 3-5 sentences total

Respond ONLY with valid JSON in this exact format:
{
  "assessment": "One sentence overall assessment",
  "strengths": "What they did well (one sentence, or null if nothing notable)",
  "improvements": "What to improve with specific concepts to study",
  "hint": "A targeted follow-up question to deepen their understanding"
}"""


class FeedbackGenerator:
    """Generates LLM-powered interview coaching feedback."""

    def __init__(self, groq_client: GroqClient = None):
        self._groq = groq_client

    def _client(self) -> GroqClient:
        if self._groq is None:
            self._groq = get_groq_client()
        return self._groq

    def generate(
        self,
        question: str,
        ideal_answer: str,
        candidate_answer: str,
        similarity_score: float,
        confidence_score: float,
        keywords_matched: list[str],
        topic: str,
        grade: str,
    ) -> dict:
        """
        Generate personalized coaching feedback for one answer.

        Returns dict with: assessment, strengths, improvements, hint
        Falls back to a rule-based response if Groq is unavailable.
        """
        client = self._client()

        if not client.is_available():
            return self._rule_based_fallback(similarity_score, grade, keywords_matched)

        # Build a rich context prompt — grounded in computed scores
        user_message = f"""Topic: {topic}
Grade: {grade} ({similarity_score:.0%} content match, {confidence_score:.0%} communication quality)

Question: {question}

Ideal Answer: {ideal_answer}

Candidate's Answer: {candidate_answer}

Keywords they mentioned: {', '.join(keywords_matched) if keywords_matched else 'none'}

Provide coaching feedback for this candidate."""

        try:
            response = client.complete(
                system_prompt=FEEDBACK_SYSTEM_PROMPT,
                user_message=user_message,
                temperature=0.4,    # Slightly higher temp for varied, natural feedback
                max_tokens=350,
                json_mode=True,
            )

            # Validate and sanitize response
            return {
                "assessment": response.get("assessment", ""),
                "strengths": response.get("strengths"),
                "improvements": response.get("improvements", ""),
                "hint": response.get("hint", ""),
                "generated_by": "groq",
            }

        except (GroqClientError, KeyError) as e:
            return self._rule_based_fallback(similarity_score, grade, keywords_matched)

    def generate_session_summary(
        self,
        topic: str,
        questions: list[str],
        scores: list[float],
        overall_grade: str,
    ) -> dict:
        """
        Generate an end-of-session summary with personalized study recommendations.

        Called when an interview session completes.
        Gives the candidate a holistic view of their performance.
        """
        client = self._client()

        if not client.is_available():
            return {
                "summary": f"Session complete. Overall grade: {overall_grade}.",
                "key_strengths": "Review your session answers above.",
                "study_plan": f"Focus on strengthening your {topic} fundamentals.",
                "generated_by": "fallback",
            }

        avg_score = sum(scores) / len(scores) if scores else 0
        score_list = "\n".join(
            f"Q{i+1}: {score:.0f}%" for i, score in enumerate(scores)
        )

        try:
            response = client.complete(
                system_prompt="""You are a technical interview coach. 
Provide a motivating, honest session summary with a concrete 3-day study plan.
Respond ONLY with valid JSON:
{
  "summary": "2-sentence session overview",
  "key_strengths": "What they demonstrated well",
  "study_plan": "Concrete 3-day plan to improve weak areas",
  "encouragement": "One motivating sentence"
}""",
                user_message=f"""Topic: {topic}
Overall Grade: {overall_grade} (avg {avg_score:.0f}%)
Question scores:
{score_list}

Generate a session summary and study plan.""",
                temperature=0.5,
                max_tokens=400,
                json_mode=True,
            )

            return {**response, "generated_by": "groq"}

        except (GroqClientError, KeyError):
            return {
                "summary": f"Session on {topic} complete. Average score: {avg_score:.0f}%.",
                "key_strengths": "Review the questions where you scored above 70%.",
                "study_plan": f"Spend 3 days reviewing {topic} fundamentals and practice 5 more questions.",
                "encouragement": "Consistent practice is the key to interview success.",
                "generated_by": "fallback",
            }

    def _rule_based_fallback(
        self,
        similarity: float,
        grade: str,
        keywords: list[str],
    ) -> dict:
        """Simple rule-based feedback when Groq is unavailable."""
        if grade == "Excellent":
            assessment = "Strong answer covering the key concepts."
        elif grade == "Good":
            assessment = "Good answer with some gaps in coverage."
        elif grade == "Fair":
            assessment = "Partial answer — review the topic more thoroughly."
        else:
            assessment = "This answer needs significant improvement."

        return {
            "assessment": assessment,
            "strengths": f"Mentioned: {', '.join(keywords[:3])}" if keywords else None,
            "improvements": "Study the ideal answer and identify concepts you missed.",
            "hint": "Can you explain this concept in more detail?",
            "generated_by": "fallback",
        }


_generator: Optional[FeedbackGenerator] = None

def get_feedback_generator() -> FeedbackGenerator:
    global _generator
    if _generator is None:
        _generator = FeedbackGenerator()
    return _generator
