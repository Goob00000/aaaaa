"""
Core RFP response agent: retrieves similar past answers and generates drafts via Claude.
"""

import os
import anthropic
import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

COLLECTION_NAME = "rfp_knowledge_base"
CHROMA_PATH = "knowledge_base"
TOP_K = 5
MODEL = "claude-sonnet-4-6"

SYSTEM_PROMPT = """You are an expert proposal writer helping draft responses to RFP (Request for Proposal) questions.

You will be given:
1. The RFP question to answer
2. A set of relevant past answers from previous successful proposals

Your task:
- Write a clear, professional, and concise answer to the question
- Ground your response in the provided past answers — do not invent capabilities, certifications, or facts
- Adapt and synthesize the past answers rather than copy-pasting
- If the past answers do not cover the question well, note what information would be needed to complete the answer
- Use first-person plural (we/our) unless the question specifically requires otherwise
- Keep the tone professional and confident"""


class RFPAgent:
    def __init__(self, chroma_path: str = CHROMA_PATH):
        embed_fn = SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")
        client = chromadb.PersistentClient(path=chroma_path)
        self.collection = client.get_collection(
            name=COLLECTION_NAME,
            embedding_function=embed_fn,
        )
        self.claude = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    def retrieve(self, question: str, category: str = "", top_k: int = TOP_K) -> list[dict]:
        where = {"category": category} if category else None
        results = self.collection.query(
            query_texts=[question],
            n_results=min(top_k, self.collection.count()),
            where=where,
            include=["documents", "metadatas", "distances"],
        )
        pairs = []
        for doc, meta, dist in zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        ):
            pairs.append({
                "question": doc,
                "answer": meta["answer"],
                "category": meta["category"],
                "similarity": round(1 - dist, 3),
            })
        return pairs

    def draft_answer(self, question: str, category: str = "", updated_by: str = "AI Draft") -> dict:
        past = self.retrieve(question, category=category)

        context_blocks = []
        for i, p in enumerate(past, 1):
            context_blocks.append(
                f"[Past answer {i} | category: {p['category']} | similarity: {p['similarity']}]\n"
                f"Q: {p['question']}\n"
                f"A: {p['answer']}"
            )
        context = "\n\n".join(context_blocks)

        user_message = f"""RFP Question:
{question}

---
Relevant past answers for reference:

{context}

---
Please draft a response to the RFP question above."""

        response = self.claude.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )

        low_confidence = past[0]["similarity"] < 0.6 if past else True
        return {
            "question": question,
            "draft_answer": response.content[0].text,
            "updated_by": updated_by,
            "review_status": "Pending Review" if low_confidence else "Draft",
            "sources_used": len(past),
            "top_match_similarity": past[0]["similarity"] if past else 0,
            "needs_review": low_confidence,
        }
