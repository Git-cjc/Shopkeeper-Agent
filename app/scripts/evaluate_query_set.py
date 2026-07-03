import argparse
import asyncio
from pathlib import Path

from app.evaluation.runner import (
    evaluate_cases,
    render_summary_markdown,
    select_eval_cases,
    summarize_results,
    write_report_files,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dataset-path",
        type=Path,
        default=Path("app/evaluation/datasets/query_eval_set.yaml"),
    )
    parser.add_argument("--output-dir", type=Path, default=Path("reports/query-eval"))
    parser.add_argument("--case-id")
    parser.add_argument("--tag")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    cases = select_eval_cases(args.dataset_path, case_id=args.case_id, tag=args.tag)
    results = await evaluate_cases(cases)
    summary = summarize_results(results)
    write_report_files(args.output_dir, summary, results)
    print(render_summary_markdown(summary))


if __name__ == "__main__":
    asyncio.run(main())
