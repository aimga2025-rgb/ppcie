from pathlib import Path

import pandas as pd


def main() -> None:
    path = Path(__file__).resolve().parent / "data" / "Book1.xlsx"
    xl = pd.ExcelFile(path)
    print("sheets:", xl.sheet_names)
    for sheet in xl.sheet_names:
        print("\n---", sheet, "---")
        df0 = xl.parse(sheet, nrows=0)
        print("columns (header row):", list(df0.columns))

        raw = xl.parse(sheet, header=None, nrows=15)
        print("\nfirst 15 rows (raw):")
        print(raw.fillna("").to_string(index=False, header=False))


if __name__ == "__main__":
    main()
