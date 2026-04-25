"""
RFP Response Agent — CLI entry point.

Commands:
  ingest   Load historical Q&A spreadsheet into ChromaDB
  respond  Generate draft answers for a new RFP spreadsheet

Usage:
  python main.py ingest --history data/past_responses.xlsx [--reset]
  python main.py respond --rfp data/new_rfp.xlsx --output data/rfp_response.xlsx [--updated_by "Jane Smith"]
"""

import argparse
import sys
import pandas as pd
from pathlib import Path


def cmd_ingest(args):
    from ingest import ingest
    ingest(args.history, reset=args.reset)


def cmd_respond(args):
    from agent import RFPAgent

    rfp_path = Path(args.rfp)
    if not rfp_path.exists():
        print(f"Error: RFP file not found: {rfp_path}")
        sys.exit(1)

    df = pd.read_excel(rfp_path)
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]

    if "question" not in df.columns:
        print("Error: RFP spreadsheet must have a 'question' column")
        sys.exit(1)

    agent = RFPAgent()

    results = []
    total = len(df)
    for i, row in df.iterrows():
        question = str(row["question"]).strip()
        if not question:
            continue

        category = str(row.get("category", "")).strip() if "category" in df.columns else ""
        print(f"[{i + 1}/{total}] {question[:80]}...")

        result = agent.draft_answer(question, category=category, updated_by=args.updated_by)
        results.append({
            "question": question,
            "category": category,
            "draft_answer": result["draft_answer"],
            "updated_by": result["updated_by"],
            "review_status": result["review_status"],
            "needs_review": result["needs_review"],
            "top_match_similarity": result["top_match_similarity"],
            "sources_used": result["sources_used"],
        })

    out_df = pd.DataFrame(results)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        out_df.to_excel(writer, index=False, sheet_name="Responses")

        ws = writer.sheets["Responses"]
        from openpyxl.styles import PatternFill
        from openpyxl.worksheet.datavalidation import DataValidation

        # Dropdown for review_status column
        review_status_col = out_df.columns.get_loc("review_status") + 1
        col_letter = ws.cell(row=1, column=review_status_col).column_letter
        dv = DataValidation(
            type="list",
            formula1='"Draft,Pending Review,Approved,Published"',
            allow_blank=False,
            showDropDown=False,
        )
        dv.sqref = f"{col_letter}2:{col_letter}{len(out_df) + 1}"
        ws.add_data_validation(dv)

        # Highlight rows that need human review
        yellow = PatternFill(start_color="FFFF99", end_color="FFFF99", fill_type="solid")
        for row_idx, needs in enumerate(out_df["needs_review"], start=2):
            if needs:
                for col_idx in range(1, len(out_df.columns) + 1):
                    ws.cell(row=row_idx, column=col_idx).fill = yellow

    flagged = out_df["needs_review"].sum()
    print(f"\nDone. {len(results)} answers drafted → {output_path}")
    if flagged:
        print(f"  {flagged} rows flagged for human review (highlighted yellow) — low similarity to past answers")


def main():
    parser = argparse.ArgumentParser(description="Autonomous RFP Response Agent")
    sub = parser.add_subparsers(dest="command", required=True)

    # ingest
    p_ingest = sub.add_parser("ingest", help="Load historical responses into knowledge base")
    p_ingest.add_argument("--history", required=True, help="Path to past_responses.xlsx")
    p_ingest.add_argument("--reset", action="store_true", help="Wipe and rebuild the collection")
    p_ingest.set_defaults(func=cmd_ingest)

    # respond
    p_respond = sub.add_parser("respond", help="Generate draft answers for a new RFP")
    p_respond.add_argument("--rfp", required=True, help="Path to new RFP spreadsheet (.xlsx)")
    p_respond.add_argument("--output", default="data/rfp_response.xlsx", help="Output path")
    p_respond.add_argument("--updated_by", default="AI Draft", help="Name to record in the 'updated_by' field")
    p_respond.set_defaults(func=cmd_respond)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
