"""
Load historical RFP Q&A spreadsheet into ChromaDB for semantic retrieval.

Usage:
    python ingest.py --history data/past_responses.xlsx
"""

import argparse
import hashlib
import pandas as pd
import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

COLLECTION_NAME = "rfp_knowledge_base"
CHROMA_PATH = "knowledge_base"


def load_history(path: str) -> pd.DataFrame:
    df = pd.read_excel(path)
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
    required = {"question", "answer"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Spreadsheet missing required columns: {missing}")
    df = df.dropna(subset=["question", "answer"])
    df["question"] = df["question"].astype(str).str.strip()
    df["answer"] = df["answer"].astype(str).str.strip()
    df["category"] = df.get("category", pd.Series([""] * len(df))).fillna("").astype(str)
    df["date_updated"] = df.get("date_updated", pd.Series([""] * len(df))).fillna("").astype(str)
    df["date_created"] = df.get("date_created", pd.Series([""] * len(df))).fillna("").astype(str)
    df["updated_by"] = df.get("updated_by", pd.Series([""] * len(df))).fillna("").astype(str)
    df["review_status"] = df.get("review_status", pd.Series([""] * len(df))).fillna("").astype(str)
    return df


def make_id(question: str) -> str:
    return hashlib.md5(question.encode()).hexdigest()


def ingest(history_path: str, reset: bool = False) -> None:
    df = load_history(history_path)

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
        ids.append(make_id(row["question"]))
        documents.append(row["question"])
        metadatas.append({
            "answer": row["answer"],
            "category": row["category"],
            "date_updated": row["date_updated"],
            "date_created": row["date_created"],
            "updated_by": row["updated_by"],
            "review_status": row["review_status"],
        })

    # Upsert in batches of 100
    batch_size = 100
    for i in range(0, len(ids), batch_size):
        collection.upsert(
            ids=ids[i:i + batch_size],
            documents=documents[i:i + batch_size],
            metadatas=metadatas[i:i + batch_size],
        )
        print(f"  Ingested {min(i + batch_size, len(ids))}/{len(ids)} records")

    print(f"\nDone. {len(ids)} Q&A pairs loaded into '{COLLECTION_NAME}'.")


def main():
    parser = argparse.ArgumentParser(description="Ingest historical RFP responses into ChromaDB")
    parser.add_argument("--history", required=True, help="Path to past_responses.xlsx")
    parser.add_argument("--reset", action="store_true", help="Wipe and rebuild the collection")
    args = parser.parse_args()
    ingest(args.history, reset=args.reset)


if __name__ == "__main__":
    main()
