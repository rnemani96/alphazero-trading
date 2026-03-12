// ecosystem.config.js  — PM2 config for AlphaZero Capital
module.exports = {
  apps: [{
    name:           'alphazero-capital',
    script:         'C:\Users\pc\AppData\Local\Programs\Python\Python312\python.EXE',
    args:           'main.py',
    cwd:            'D:\files\ALPHAZERO_COMPLETE_FINAL\ALPHAZERO_COMPLETE',
    watch:          false,
    autorestart:    true,
    restart_delay:  30000,   // 30s before restart
    max_restarts:   10,
    min_uptime:     '30s',
    env: {
      TZ:   'Asia/Kolkata',
      MODE: 'PAPER',
    },
    error_file:  'D:\files\ALPHAZERO_COMPLETE_FINAL\ALPHAZERO_COMPLETE/logs/pm2_error.log',
    out_file:    'D:\files\ALPHAZERO_COMPLETE_FINAL\ALPHAZERO_COMPLETE/logs/pm2_out.log',
    merge_logs:  true,
  }]
};
