# nginv

A real-time terminal dashboard for monitoring multiple nginx log files. Similar to `top` or `bmon`, but for your nginx traffic.

![Python 3.6+](https://img.shields.io/badge/python-3.6+-blue.svg)
![License MIT](https://img.shields.io/badge/license-MIT-green.svg)

## What Does It Do?

**nginv** provides a live, auto-refreshing view of your nginx server traffic across multiple sites:

```
NGINX MONITOR | 09:15:32 | 10s refresh | q:quit r:reset
──────────────────────────────────────────────────────────────────────
Total: 12,456 req | 847.2MB | 1,892 unique IPs | 47 errors
Rate:  42.3 req/s | 2.8MB/s | Interval: 423 req, 156 IPs
Status: 2xx:  412  4xx:    8  5xx:    3
──────────────────────────────────────────────────────────────────────
ACCESS              │ Interval              │ Total
SERVER              │ req   2xx   4xx   5xx │ req      2xx     err
●tangram            │  142   138     3     1 │   4521     4320      47
●blockpuzzle        │   87    85     2     0 │   3210     3150      15
●watersortmerge     │   34    34     0     0 │   1205     1180       3

ERRORS              │ int  total
●tangram            │    0      5
●blockpuzzle        │    1     12
●watersortmerge     │    0      0

──────────────────────────────────────────────────────────────────────
RECENT ERRORS (last 5)
tangram  ACC 09:14:22 404 GET /api/missing/endpoint
blockpuz ERR 09:14:35 [error] upstream timed out (110: Connection timed out)
tangram  ACC 09:15:01 500 POST /api/checkout
```

### Features

- **Auto-discovery**: Automatically scans `/etc/nginx/sites-enabled/` to find all configured log files
- **Real-time tailing**: Monitors logs as they're written, no polling of file contents
- **Summary statistics**: Total requests, bandwidth, unique IPs, request rate, error rate
- **Per-site breakdown**: See traffic for each virtual host separately
- **Error tracking**: Captures last 5 errors from both access logs (4xx/5xx) and error logs
- **Color-coded output**: Green for success, yellow for warnings, red for errors
- **Handles log rotation**: Automatically detects and follows rotated log files
- **Lightweight**: Pure Python, minimal CPU usage

## Requirements

- **Python 3.6+** (uses f-strings and standard library only)
- **Linux/Unix** with `curses` support (included in standard Python on Linux/macOS)
- **Read access** to nginx log files (typically requires `sudo`)
- **nginx** with sites configured in `/etc/nginx/sites-enabled/`

### No Additional Dependencies

nginv uses only Python standard library modules:
- `curses` - terminal UI
- `re` - log parsing
- `os`, `glob` - file discovery
- `threading` - concurrent log tailing
- `collections` - data structures
- `datetime`, `time` - timestamps
- `signal`, `sys`, `argparse` - CLI handling

## Installation

### Quick Install

```bash
# Download the script
sudo curl -o /usr/local/bin/nginv https://your-server.com/nginv.py
sudo chmod +x /usr/local/bin/nginv
```

### Manual Install

```bash
# Copy to a location in your PATH
sudo cp nginv.py /usr/local/bin/nginv
sudo chmod +x /usr/local/bin/nginv
```

### Run Without Installing

```bash
sudo python3 nginv.py
```

## Usage

### Basic Usage (Auto-Discovery)

```bash
sudo nginv
```

This will:
1. Scan `/etc/nginx/sites-enabled/` for all config files
2. Extract `access_log` and `error_log` paths from each config
3. Extract `server_name` to label each site
4. Start monitoring all discovered logs

### Custom Refresh Interval

```bash
# Refresh every 5 seconds instead of default 10
sudo nginv -i 5
```

### Custom Sites Directory

```bash
# Use a different nginx config directory
sudo nginv -d /etc/nginx/conf.d/
```

### Manually Specify Log Files

```bash
# Skip auto-discovery and specify files directly
sudo nginv -f /var/log/nginx/access.log /var/log/nginx/error.log
```

### All Options

```
usage: nginv [-h] [-i INTERVAL] [-d SITES_DIR] [-f FILES [FILES ...]]

Nginx Log Monitor - Auto-discovers logs from nginx config

optional arguments:
  -h, --help            show this help message and exit
  -i INTERVAL, --interval INTERVAL
                        Refresh interval in seconds (default: 10)
  -d SITES_DIR, --sites-dir SITES_DIR
                        Nginx sites-enabled directory (default: /etc/nginx/sites-enabled)
  -f FILES [FILES ...], --files FILES [FILES ...]
                        Manually specify log files (skips auto-discovery)
```

## Keyboard Controls

| Key | Action |
|-----|--------|
| `q` | Quit the monitor |
| `r` | Reset all statistics to zero |

## Nginx Configuration

nginv parses nginx config files looking for these directives:

```nginx
server {
    server_name api.example.com;
    
    access_log /var/log/nginx/example_access.log;
    error_log /var/log/nginx/example_error.log;
    
    # ... rest of config
}
```

### Server Name Extraction

nginv extracts a short name from `server_name` for display:

| server_name | Displayed as |
|-------------|--------------|
| `api.tangram.ninja` | tangram |
| `api.blockpuzzleadventure.com` | blockpuzzleadventure |
| `www.example.com` | example |
| `myapp.io` | myapp |

## Display Explained

### Summary Section

```
Total: 12,456 req | 847.2MB | 1,892 unique IPs | 47 errors
Rate:  42.3 req/s | 2.8MB/s | Interval: 423 req, 156 IPs
Status: 2xx:  412  4xx:    8  5xx:    3
```

- **Total**: Cumulative stats since nginv started (or last reset)
- **Rate**: Requests per second and bandwidth per second
- **Interval**: Stats for the current refresh interval only
- **Status**: HTTP status code breakdown for current interval

### Access Logs Table

```
SERVER              │ req   2xx   4xx   5xx │ req      2xx     err
●tangram            │  142   138     3     1 │   4521     4320      47
```

- **●** Green dot = file exists and is being monitored
- **○** Magenta dot = file not found
- **Interval columns**: Stats since last refresh
- **Total columns**: Cumulative stats

### Error Logs Table

```
ERRORS              │ int  total
●tangram            │    0      5
```

- **int**: Errors in current interval
- **total**: Total errors since start

### Recent Errors

```
tangram  ACC 09:14:22 404 GET /api/missing/endpoint
blockpuz ERR 09:14:35 [error] upstream timed out
```

- **ACC**: Error from access log (4xx/5xx response)
- **ERR**: Error from error log

## Troubleshooting

### "No log files found"

```bash
# Check if your sites-enabled directory is correct
ls -la /etc/nginx/sites-enabled/

# Try specifying a different directory
sudo nginv -d /etc/nginx/conf.d/

# Or specify files manually
sudo nginv -f /var/log/nginx/*.log
```

### "Permission denied"

Log files are typically owned by root or www-data:

```bash
# Run with sudo
sudo nginv

# Or add your user to the adm group (has read access to logs)
sudo usermod -aG adm $USER
# Then log out and back in
```

### "curses not available"

On some minimal Python installations:

```bash
# Debian/Ubuntu
sudo apt-get install python3-curses

# Or use the full Python package
sudo apt-get install python3
```

### Terminal display issues

```bash
# Make sure your terminal supports colors
echo $TERM  # Should be xterm-256color or similar

# Try resizing your terminal to at least 80x24
```

## How It Works

1. **Discovery**: On startup, nginv reads all files in `/etc/nginx/sites-enabled/` and uses regex to find `access_log`, `error_log`, and `server_name` directives.

2. **Tailing**: For each discovered log file, a background thread opens the file, seeks to the end, and continuously reads new lines as they're appended.

3. **Parsing**: Each log line is parsed with regex:
   - Access logs: Extracts IP, method, path, status code, and bytes
   - Error logs: Extracts severity level and message

4. **Aggregation**: Statistics are collected in thread-safe counters, tracking both interval (since last refresh) and total (since start) metrics.

5. **Display**: The curses-based UI refreshes every N seconds, showing aggregated statistics and recent errors.

## License

MIT License - feel free to use, modify, and distribute.

## Contributing

Suggestions and improvements welcome! Common enhancement ideas:

- [ ] Filter by status code
- [ ] Export stats to file/JSON
- [ ] Alert thresholds (e.g., beep on 5xx spike)
- [ ] Historical graphs
- [ ] Support for custom log formats
