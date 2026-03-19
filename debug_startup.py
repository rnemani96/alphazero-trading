import sys, os, time

# Redirect stdout to a file
log_file = "startup_debug.log"
with open(log_file, "w") as f:
    f.write("STARTING DEBUG IMPORT\n")
    f.flush()

    def log(msg):
        print(msg)
        with open(log_file, "a") as lf:
            lf.write(msg + "\n")
            lf.flush()

    log("Loading basic modules...")
    import logging
    import threading
    import signal
    import webbrowser
    log("Basic modules OK")

    log("Loading config.settings...")
    from config.settings import settings
    log("config.settings OK")

    log("Loading src.data.discovery...")
    from src.data.discovery import get_best_performing_stocks
    log("src.data.discovery OK")

    log("Loading yfinance...")
    import yfinance as yf
    log("yfinance OK")

    log("Loading xgboost...")
    import xgboost as xgb
    log("xgboost OK")

    log("Loading src.data.fetch...")
    from src.data.fetch import DataFetcher
    log("src.data.fetch OK")

    log("Loading src.data.multi_source_data...")
    from src.data.multi_source_data import get_msd, MultiSourceData
    log("src.data.multi_source_data OK")

    log("Loading active_portfolio...")
    from src.risk.active_portfolio import ActivePortfolio
    log("active_portfolio OK")

    log("DONE")
