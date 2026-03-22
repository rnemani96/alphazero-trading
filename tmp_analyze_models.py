import sqlite3
import pandas as pd
import os

DB_PATH = "logs/evaluation.db"

def analyze():
    if not os.path.exists(DB_PATH):
        print(f"Error: {DB_PATH} not found.")
        return

    conn = sqlite3.connect(DB_PATH)
    try:
        # Check tables
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = cursor.fetchall()
        print(f"Tables: {tables}")

        table_name = next((t[0] for t in tables if 'signals' in t[0].lower()), None)
        if not table_name:
            print("No signals table found.")
            return

        # Load signals
        df = pd.read_sql_query(f"SELECT * FROM {table_name}", conn)
        print(f"Total signals: {len(df)}")

        if len(df) == 0:
            return

        # 1. Class Balance (Direction)
        print("\n--- Direction Balance ---")
        if 'direction' in df.columns:
            print(df['direction'].value_counts(normalize=True))
        else:
            print("Direction column not found.")

        # 2. Performance Analysis
        col_pnl = next((c for c in df.columns if 'pnl' in c.lower()), None)
        if col_pnl:
            df_closed = df[df[col_pnl].notnull()].copy()
            print(f"\nClosed trades: {len(df_closed)}")
            if len(df_closed) > 0:
                print("\n--- Model Performance ---")
                is_win = (df_closed[col_pnl] > 0).astype(int)
                win_rate = is_win.mean()
                avg_pnl = df_closed[col_pnl].mean()
                print(f"Win Rate: {win_rate:.2%}")
                print(f"Avg PnL: {avg_pnl:.2%}")

                # 3. Overfitting Check (by strategy)
                if 'strategy_id' in df.columns:
                    print("\n--- Top 5 Strategies by Frequency ---")
                    print(df_closed['strategy_id'].value_counts().head(5))

        # 4. Calibration (Confidence vs Accuracy)
        if 'confidence' in df.columns and col_pnl:
            df['win'] = (df[col_pnl] > 0).astype(int)
            print("\n--- Confidence Calibration ---")
            try:
                print(df.groupby(pd.cut(df['confidence'], 5))['win'].mean())
            except:
                print("Could not bin confidence.")

        # 5. Regime Balance
        if 'regime' in df.columns:
            print("\n--- Regime Balance ---")
            print(df['regime'].value_counts())

    except Exception as e:
        print(f"Error: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    analyze()
