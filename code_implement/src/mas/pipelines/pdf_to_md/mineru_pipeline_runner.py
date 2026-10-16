#!/usr/bin/env python3
"""Run MinerU's pipeline backend directly without the CLI API orchestrator."""

from __future__ import annotations

import argparse
from pathlib import Path

from mineru.cli.common import do_parse, read_fn


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run MinerU pipeline directly for one PDF.")
    parser.add_argument("-p", "--path", required=True, help="Input PDF path.")
    parser.add_argument("-o", "--output", required=True, help="Output directory.")
    parser.add_argument("-b", "--backend", default="pipeline", choices=["pipeline"], help="MinerU backend.")
    parser.add_argument("-m", "--method", default="auto", choices=["auto", "txt", "ocr"], help="Parse method.")
    parser.add_argument("-l", "--lang", default="ch", help="Input language.")
    parser.add_argument("--start", type=int, default=0, help="Starting page, zero based.")
    parser.add_argument("--end", type=int, default=None, help="Ending page, zero based.")
    parser.add_argument("-f", "--formula", type=_bool_arg, default=True, help="Enable formula parsing.")
    parser.add_argument("-t", "--table", type=_bool_arg, default=True, help="Enable table parsing.")
    return parser.parse_args()


def _bool_arg(value: str | bool) -> bool:
    if isinstance(value, bool):
        return value
    return value.lower() in {"1", "true", "yes", "on"}


def main() -> int:
    args = parse_args()
    pdf_path = Path(args.path).resolve()
    output_dir = Path(args.output).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    do_parse(
        str(output_dir),
        [pdf_path.stem],
        [read_fn(pdf_path)],
        [args.lang],
        backend=args.backend,
        parse_method=args.method,
        formula_enable=args.formula,
        table_enable=args.table,
        f_draw_layout_bbox=False,
        f_draw_span_bbox=False,
        f_dump_model_output=True,
        f_dump_middle_json=True,
        f_dump_content_list=True,
        f_dump_orig_pdf=False,
        start_page_id=args.start,
        end_page_id=args.end,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
