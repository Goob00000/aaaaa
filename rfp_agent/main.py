"""
RFP Response Agent — CLI entry point.

Commands:
  ingest   Load predefined response library into ChromaDB
  respond  Process a new RFP questions spreadsheet end-to-end

Usage:
  python main.py ingest --library data/predefined_responses.xlsx [--reset]
  python main.py respond --rfp data/new_rfp.xlsx --output data/rfp_response.xlsx [--updated_by "Jane Smith"]

Input spreadsheet (new_rfp.xlsx):
  Required: question
  Optional: any other columns are preserved in the output as-is

Output spreadsheet columns:
  original_question | detected_category | matched_topic | draft_answer |
  updated_by | review_status | match_score | needs_review
"""

import argparse
import sys
import pandas as pd
from pathlib import Path


# ── Output column order ───────────────────────────────────────────────────────

OUTPUT_COLUMNS = [
    "original_question",
    "detected_category",
    "matched_topic",
    "draft_answer",
    "updated_by",
    "review_status",
    "match_score",
    "needs_review",
]

REVIEW_STATUSES = ["Draft", "Pending Review", "Approved", "Published"]


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_ingest(args):
    from ingest import ingest
    ingest(args.library, reset=args.reset)


def cmd_respond(args):
    from agent import RFPAgent

    rfp_path = Path(args.rfp)
    if not rfp_path.exists():
        print(f"Error: RFP file not found: {rfp_path}")
        sys.exit(1)

    df = pd.read_excel(rfp_path)
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]

    if "question" not in df.columns:
        print("Error: input spreadsheet must have a 'question' column")
        sys.exit(1)

    questions = df["question"].dropna().astype(str).str.strip()
    questions = questions[questions != ""]
    total = len(questions)

    if total == 0:
        print("Error: no questions found in the spreadsheet")
        sys.exit(1)

    print(f"Processing {total} questions...\n")
    agent = RFPAgent()

    rows = []
    for i, question in enumerate(questions, 1):
        print(f"[{i}/{total}] Categorizing + matching: {question[:80]}...")
        result = agent.process_question(question, updated_by=args.updated_by)
        print(f"       → {result['detected_category']} | matched: {result['matched_topic'][:60]} | score: {result['match_score']}")
        rows.append(result)

    out_df = pd.DataFrame(rows)[OUTPUT_COLUMNS]
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    _write_output(out_df, output_path)

    flagged = out_df["needs_review"].sum()
    print(f"\nDone. {total} answers drafted → {output_path}")
    if flagged:
        print(f"  {flagged} rows flagged for review (highlighted yellow, status = 'Pending Review')")

    category_counts = out_df["detected_category"].value_counts().to_dict()
    print("\nCategory breakdown:")
    for cat, count in sorted(category_counts.items()):
        print(f"  {cat}: {count}")


# ── Excel writer ──────────────────────────────────────────────────────────────

def _write_output(df: pd.DataFrame, output_path: Path) -> None:
    from openpyxl.styles import PatternFill, Font, Alignment, PatternFill
    from openpyxl.worksheet.datavalidation import DataValidation
    from openpyxl.utils import get_column_letter

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="RFP Responses")
        ws = writer.sheets["RFP Responses"]

        # Column widths
        col_widths = {
            "original_question": 50,
            "detected_category": 22,
            "matched_topic": 30,
            "draft_answer": 80,
            "updated_by": 18,
            "review_status": 18,
            "match_score": 14,
            "needs_review": 14,
        }
        for col_idx, col_name in enumerate(df.columns, 1):
            col_letter = get_column_letter(col_idx)
            ws.column_dimensions[col_letter].width = col_widths.get(col_name, 15)

        # Wrap text for question and answer columns
        for row in ws.iter_rows(min_row=2, max_row=ws.max_row):
            for cell in row:
                cell.alignment = Alignment(wrap_text=True, vertical="top")

        # Header style
        header_fill = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
        header_font = Font(color="FFFFFF", bold=True)
        for cell in ws[1]:
            cell.fill = header_fill
            cell.font = header_font

        # Freeze header row
        ws.freeze_panes = "A2"

        # Dropdown for review_status
        status_col_idx = df.columns.get_loc("review_status") + 1
        status_col_letter = get_column_letter(status_col_idx)
        dv = DataValidation(
            type="list",
            formula1=f'"{",".join(REVIEW_STATUSES)}"',
            allow_blank=False,
            showDropDown=False,
        )
        dv.sqref = f"{status_col_letter}2:{status_col_letter}{len(df) + 1}"
        ws.add_data_validation(dv)

        # Yellow highlight for rows needing review
        yellow = PatternFill(start_color="FFFF99", end_color="FFFF99", fill_type="solid")
        for row_idx, needs in enumerate(df["needs_review"], start=2):
            if needs:
                for col_idx in range(1, len(df.columns) + 1):
                    ws.cell(row=row_idx, column=col_idx).fill = yellow

        # Row height for readability
        for row_idx in range(2, ws.max_row + 1):
            ws.row_dimensions[row_idx].height = 60


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Autonomous RFP Response Agent")
    sub = parser.add_subparsers(dest="command", required=True)

    p_ingest = sub.add_parser("ingest", help="Load predefined response library into knowledge base")
    p_ingest.add_argument("--library", required=True, help="Path to predefined_responses.xlsx")
    p_ingest.add_argument("--reset", action="store_true", help="Wipe and rebuild the collection")
    p_ingest.set_defaults(func=cmd_ingest)

    p_respond = sub.add_parser("respond", help="Process a new RFP questions spreadsheet")
    p_respond.add_argument("--rfp", required=True, help="Path to RFP questions spreadsheet (.xlsx)")
    p_respond.add_argument("--output", default="data/rfp_response.xlsx", help="Output path (.xlsx)")
    p_respond.add_argument("--updated_by", default="AI Draft", help="Name recorded in 'updated_by' column")
    p_respond.set_defaults(func=cmd_respond)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
