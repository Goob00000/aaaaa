"""
Load predefined response library into ChromaDB for semantic matching.

The predefined_responses spreadsheet is your curated library of approved answers.
Required columns : topic    — short label for what this response covers
                   response — the full approved response text
Optional columns : category — will be auto-assigned on ingest if blank
                   keywords — comma-separated terms to improve matching

Tip: if migrating from a historical Q&A spreadsheet, map:
     question → topic,  answer → response,  keep category as-is.

Usage:
    python main.py ingest --library data/predefined_responses.xlsx [--reset]
"""

import argparse
import hashlib
import anthropic
import os
import pandas as pd
import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

COLLECTION_NAME = "rfp_predefined_responses"
CHROMA_PATH = "knowledge_base"

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

_CATEGORY_PROMPT = f"""Classify the following RFP response topic into exactly one of these categories:
{chr(10).join(f"- {c}" for c in CATEGORIES)}

Topic: {{topic}}
Keywords: {{keywords}}
Response preview: {{preview}}

Reply with only the category name, exactly as written above."""


def _auto_categorize(client: anthropic.Anthropic, topic: str, keywords: str, response_preview: str) -> str:
    prompt = _CATEGORY_PROMPT.format(
        topic=topic,
        keywords=keywords,
        preview=response_preview[:200],
    )
    result = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=20,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = result.content[0].text.strip()
    for cat in CATEGORIES:
        if cat.lower() in raw.lower():
            return cat
    return "Other"


def load_library(path: str) -> pd.DataFrame:
    df = pd.read_excel(path)
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
    required = {"topic", "response"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Spreadsheet missing required columns: {missing}")
    df = df.dropna(subset=["topic", "response"])
    df["topic"] = df["topic"].astype(str).str.strip()
    df["response"] = df["response"].astype(str).str.strip()
    df["category"] = df.get("category", pd.Series([""] * len(df))).fillna("").astype(str).str.strip()
    df["keywords"] = df.get("keywords", pd.Series([""] * len(df))).fillna("").astype(str).str.strip()
    return df


def make_id(topic: str) -> str:
    return hashlib.md5(topic.encode()).hexdigest()


def ingest(library_path: str, reset: bool = False) -> pd.DataFrame:
    df = load_library(library_path)

    needs_categorization = df["category"].eq("").sum()
    claude_client = None
    if needs_categorization > 0:
        print(f"  Auto-categorizing {needs_categorization} entries without a category...")
        claude_client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    for idx, row in df[df["category"] == ""].iterrows():
        df.at[idx, "category"] = _auto_categorize(
            claude_client, row["topic"], row["keywords"], row["response"]
        )

    embed_fn = SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")
    client = chromadb.PersistentClient(path=CHROMA_PATH)

    if reset:
        try:
            client.delete_collection(COLLECTION_NAME)
        except Exception:
            pass

    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=embed_fn,
        metadata={"hnsw:space": "cosine"},
    )

    ids, documents, metadatas = [], [], []
    for _, row in df.iterrows():
        # Embed topic + keywords + response snippet for rich semantic matching
        keyword_part = f" Keywords: {row['keywords']}." if row["keywords"] else ""
        embed_text = f"{row['topic']}.{keyword_part} {row['response'][:300]}"

        ids.append(make_id(row["topic"]))
        documents.append(embed_text)
        metadatas.append({
            "topic": row["topic"],
            "response": row["response"],
            "category": row["category"],
            "keywords": row["keywords"],
        })

    batch_size = 100
    for i in range(0, len(ids), batch_size):
        collection.upsert(
            ids=ids[i:i + batch_size],
            documents=documents[i:i + batch_size],
            metadatas=metadatas[i:i + batch_size],
        )
        print(f"  Ingested {min(i + batch_size, len(ids))}/{len(ids)} predefined responses")

    breakdown = df["category"].value_counts().to_dict()
    print(f"\nDone. {len(ids)} responses loaded into '{COLLECTION_NAME}'.")
    for cat, count in sorted(breakdown.items()):
        print(f"  {cat}: {count}")

    return df


def main():
    parser = argparse.ArgumentParser(description="Ingest predefined RFP response library into ChromaDB")
    parser.add_argument("--library", required=True, help="Path to predefined_responses.xlsx")
    parser.add_argument("--reset", action="store_true", help="Wipe and rebuild the collection")
    args = parser.parse_args()
    ingest(args.library, reset=args.reset)


if __name__ == "__main__":
    main()
