"""
RFP response agent: categorize question → match predefined responses → draft answer.
"""

import os
import anthropic
import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

COLLECTION_NAME = "rfp_predefined_responses"
CHROMA_PATH = "knowledge_base"
TOP_K = 3
MODEL = "claude-sonnet-4-6"

CATEGORIES = [
    "Financial/Commercial",
    "Technical",
    "Business/Operations",
    "Legal/Compliance",
    "Security/Privacy",
    "HR/Staffing",
    "Project Management",
    "Other",
]

_CATEGORIZE_PROMPT = f"""You are classifying RFP (Request for Proposal) questions for a proposal team.

Classify the question below into exactly one of these categories:
{chr(10).join(f"- {c}" for c in CATEGORIES)}

Rules:
- Financial/Commercial: pricing, payment terms, costs, contracts, SLAs, penalties, licensing fees
- Technical: architecture, integrations, APIs, infrastructure, performance, technology stack
- Business/Operations: company background, experience, processes, methodology, references, case studies
- Legal/Compliance: regulations, certifications, audits, GDPR, data residency, liability, insurance
- Security/Privacy: data security, access control, encryption, vulnerability management, incident response
- HR/Staffing: team structure, key personnel, qualifications, subcontractors, staff turnover
- Project Management: timelines, milestones, delivery approach, risk management, change management
- Other: anything that does not clearly fit the above

Reply with only the category name, exactly as listed."""

_DRAFT_PROMPT = """You are an expert proposal writer drafting a response to an RFP question.

You will be given:
1. The original RFP question (preserve its meaning exactly)
2. The best-matching predefined responses from the approved response library

Your task:
- Write a clear, professional response that directly answers the question
- Ground your answer strictly in the provided predefined responses — do not invent facts, figures, certifications, or capabilities
- Adapt and tailor the language to fit the specific question asked
- If the predefined responses only partially cover the question, draft what you can and append a [NEEDS INPUT: <what is missing>] note
- Use first-person plural (we/our) throughout
- Be concise — aim for 2–4 paragraphs unless the question demands more detail"""


class RFPAgent:
    def __init__(self, chroma_path: str = CHROMA_PATH):
        embed_fn = SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")
        chroma_client = chromadb.PersistentClient(path=chroma_path)
        self.collection = chroma_client.get_collection(
            name=COLLECTION_NAME,
            embedding_function=embed_fn,
        )
        self.claude = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    # ── Step 1: Categorize ────────────────────────────────────────────────────

    def categorize_question(self, question: str) -> str:
        result = self.claude.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=20,
            system=_CATEGORIZE_PROMPT,
            messages=[{"role": "user", "content": f"Question: {question}"}],
        )
        raw = result.content[0].text.strip()
        for cat in CATEGORIES:
            if cat.lower() in raw.lower():
                return cat
        return "Other"

    # ── Step 2: Match predefined responses ───────────────────────────────────

    def match_responses(self, question: str, category: str, top_k: int = TOP_K) -> list[dict]:
        total = self.collection.count()
        if total == 0:
            return []

        # Try category-filtered search first
        matches = self._query(question, top_k, where={"category": category})

        # Fall back to unfiltered if category yields nothing
        if not matches:
            matches = self._query(question, top_k, where=None)

        return matches

    def _query(self, question: str, top_k: int, where: dict | None) -> list[dict]:
        try:
            results = self.collection.query(
                query_texts=[question],
                n_results=min(top_k, self.collection.count()),
                where=where,
                include=["documents", "metadatas", "distances"],
            )
        except Exception:
            return []

        matches = []
        for meta, dist in zip(results["metadatas"][0], results["distances"][0]):
            matches.append({
                "topic": meta["topic"],
                "response": meta["response"],
                "category": meta["category"],
                "keywords": meta.get("keywords", ""),
                "similarity": round(1 - dist, 3),
            })
        return matches

    # ── Step 3: Draft answer ─────────────────────────────────────────────────

    def _build_context(self, matches: list[dict]) -> str:
        blocks = []
        for i, m in enumerate(matches, 1):
            blocks.append(
                f"[Predefined response {i} | topic: {m['topic']} | "
                f"category: {m['category']} | similarity: {m['similarity']}]\n"
                f"{m['response']}"
            )
        return "\n\n".join(blocks)

    def draft_answer(
        self,
        question: str,
        category: str,
        matches: list[dict],
        updated_by: str = "AI Draft",
    ) -> dict:
        top_similarity = matches[0]["similarity"] if matches else 0.0
        low_confidence = top_similarity < 0.55 or not matches

        context = self._build_context(matches) if matches else "No predefined responses available."

        user_message = (
            f"RFP Question ({category}):\n{question}\n\n"
            f"---\nPredefined responses for reference:\n\n{context}\n\n"
            f"---\nPlease draft a response to the RFP question above."
        )

        response = self.claude.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=_DRAFT_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )

        return {
            "draft_answer": response.content[0].text,
            "matched_topic": matches[0]["topic"] if matches else "",
            "match_score": top_similarity,
            "updated_by": updated_by,
            "review_status": "Pending Review" if low_confidence else "Draft",
            "needs_review": low_confidence,
        }

    # ── Full pipeline ─────────────────────────────────────────────────────────

    def process_question(self, question: str, updated_by: str = "AI Draft") -> dict:
        category = self.categorize_question(question)
        matches = self.match_responses(question, category)
        result = self.draft_answer(question, category, matches, updated_by)
        return {
            "original_question": question,
            "detected_category": category,
            **result,
        }
